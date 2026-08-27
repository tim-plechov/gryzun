"""
Ollama-backed helpers: a pre-execution safety check on submitted code, and
post-execution feedback generation for the student. Ollama runs as its own
service (see docker-compose.yml); this module just talks to its HTTP API.
"""

import json
import os
import re

import httpx

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_SAFETY_MODEL = os.getenv("OLLAMA_SAFETY_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b"))
OLLAMA_FEEDBACK_MODEL = os.getenv("OLLAMA_FEEDBACK_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b"))
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))

SAFETY_PROMPT = """You are a security reviewer. You will be shown a Python file that a student \
submitted to an automated grading system. It is about to run, network-disabled, in a locked-down \
sandbox container (no network, limited memory/CPU/pids, read-only filesystem, non-root user, short \
timeout). Despite those sandbox limits, flag anything that looks like a deliberate attempt to break \
out of the sandbox, exhaust host resources, or otherwise cause harm -- e.g. fork bombs, attempts to \
access the Docker socket or filesystem paths outside the sandbox, attempts to detect or disable the \
sandbox, obfuscated/encoded payloads, or code with no plausible relation to solving a programming task.
Ordinary student mistakes (infinite loops, high memory use, crashes, bad algorithms) are NOT dangerous \
-- the sandbox's own limits already handle those; only flag deliberate malicious intent.

Respond with ONLY a JSON object, no other text: {{"dangerous": true|false, "reason": "<one sentence>"}}

Python file:
```python
{code}
```
"""

FEEDBACK_PROMPT = """You are a helpful teaching assistant giving feedback on a student's Python \
solution to a programming task. Be concise (3-6 sentences), specific, and constructive. Do not \
speculate about or reveal exact hidden test inputs/outputs -- you are only told how many hidden \
tests passed, not their content. If sample cases failed, you may reference their actual \
expected/actual values, since those are already visible to the student.

Task: {title}
Task description:
{description}

Result summary:
{summary}

Student code:
```python
{code}
```

Write feedback addressed directly to the student.
"""


def _extract_json_object(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _generate(model: str, prompt: str, temperature: float, want_json: bool) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if want_json:
        payload["format"] = "json"
    resp = httpx.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=OLLAMA_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json().get("response", "")


def check_dangerous(code: str) -> tuple[bool | None, str]:
    """Returns (dangerous, reason). `dangerous` is None if the check itself failed to run/parse."""
    try:
        raw = _generate(OLLAMA_SAFETY_MODEL, SAFETY_PROMPT.format(code=code), temperature=0.0, want_json=True)
    except (httpx.HTTPError, ValueError) as e:
        return None, f"Safety check request failed: {e}"

    parsed = _extract_json_object(raw)
    if parsed is None or "dangerous" not in parsed:
        return None, f"Safety check returned an unparseable response: {raw[:300]!r}"
    return bool(parsed["dangerous"]), str(parsed.get("reason", ""))


def generate_feedback(title: str, description: str, code: str, summary: str) -> str:
    prompt = FEEDBACK_PROMPT.format(title=title, description=description, summary=summary, code=code)
    try:
        return _generate(OLLAMA_FEEDBACK_MODEL, prompt, temperature=0.4, want_json=False).strip()
    except (httpx.HTTPError, ValueError) as e:
        return f"(Automated feedback unavailable: {e})"
