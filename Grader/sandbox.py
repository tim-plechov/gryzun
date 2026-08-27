"""
Runs a student's solution.py against every task_dataset input inside ONE
locked-down, network-disabled sibling container per submission, `exec`-ing
the solution once per input file rather than starting a fresh container per
test case. Container create/start is the dominant cost of a `docker run`,
so reusing one long-lived container for the whole submission is
significantly faster once a task has more than a couple of test cases.

The API container itself runs inside Docker and talks to the *host's* Docker
daemon over a mounted /var/run/docker.sock ("Docker-outside-of-Docker") to
launch the sandbox container as a sibling, rather than nesting a second
Docker daemon inside the API container.

Because the host daemon -- not the API container -- resolves bind-mount
paths, any file handed to `client.containers.run(volumes=...)` must be a path
that exists on the *host* filesystem. Submission code and dataset files live
in MinIO, not on disk, so each run first downloads exactly the files it needs
into a per-run scratch directory, bind-mounts those, and deletes them once
the container's done. SCRATCH_ROOT is where this process sees that scratch
directory (e.g. /scratch inside the API container); HOST_SCRATCH_ROOT is
where the same directory lives on the host (e.g.
/home/tim/PycharmProjects/Gryzun/scratch), and is what actually gets
bind-mounted. When running the API directly on the host (no container),
leave HOST_SCRATCH_ROOT unset -- it defaults to SCRATCH_ROOT.
"""

import os
import shutil
import time
import uuid
from pathlib import Path

import docker
from docker.errors import APIError

import db

SANDBOX_IMAGE = os.getenv("SANDBOX_IMAGE", "gryzun-sandbox:latest")
SANDBOX_TIMEOUT_SECONDS = int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "10"))
SANDBOX_MEM_LIMIT = os.getenv("SANDBOX_MEM_LIMIT", "256m")
SANDBOX_PIDS_LIMIT = int(os.getenv("SANDBOX_PIDS_LIMIT", "64"))
SANDBOX_USER = os.getenv("SANDBOX_USER", "65532:65532")

SCRATCH_ROOT = Path(os.getenv("SCRATCH_ROOT", Path(__file__).parent / "scratch")).resolve()
SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
HOST_SCRATCH_ROOT = Path(os.getenv("HOST_SCRATCH_ROOT", str(SCRATCH_ROOT)))

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


class SandboxResult:
    def __init__(self, stdout: str, stderr: str, exit_code, timed_out: bool, execution_time_ms: int):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.execution_time_ms = execution_time_ms


def run_all(code_storage_key: str, datasets: list[dict]) -> dict:
    """
    Runs code_storage_key's solution.py against every dataset's input, all
    inside one sandbox container (one `docker run`, N `exec`s).
    Returns {dataset_id: SandboxResult}.
    """
    if not datasets:
        return {}

    client = _get_client()

    run_dir = SCRATCH_ROOT / uuid.uuid4().hex
    run_dir.mkdir()
    host_run_dir = HOST_SCRATCH_ROOT / run_dir.name
    try:
        (run_dir / "solution.py").write_bytes(db.read_file_bytes(code_storage_key))
        volumes = {
            str(host_run_dir / "solution.py"): {"bind": "/sandbox/solution.py", "mode": "ro"},
        }
        input_paths = {}
        for ds in datasets:
            input_name = f"input_{ds['id']}.txt"
            (run_dir / input_name).write_bytes(db.read_file_bytes(ds["input_storage_key"]))
            container_path = f"/sandbox/inputs/{ds['id']}.txt"
            volumes[str(host_run_dir / input_name)] = {"bind": container_path, "mode": "ro"}
            input_paths[ds["id"]] = container_path

        # Outer safety net only, in case our own process dies before the finally
        # block runs -- the normal path kills+removes the container right after
        # the last exec, well before this elapses.
        keepalive_seconds = SANDBOX_TIMEOUT_SECONDS * len(datasets) + 60

        container = client.containers.run(
            image=SANDBOX_IMAGE,
            command=["sleep", str(keepalive_seconds)],
            detach=True,
            network_disabled=True,
            mem_limit=SANDBOX_MEM_LIMIT,
            memswap_limit=SANDBOX_MEM_LIMIT,  # = mem_limit -> no extra swap
            nano_cpus=1_000_000_000,  # 1 CPU
            pids_limit=SANDBOX_PIDS_LIMIT,
            read_only=True,
            tmpfs={"/tmp": "size=64m"},
            security_opt=["no-new-privileges"],
            cap_drop=["ALL"],
            user=SANDBOX_USER,
            volumes=volumes,
        )
        try:
            return {ds["id"]: _exec_one(container, input_paths[ds["id"]]) for ds in datasets}
        finally:
            try:
                container.kill()
            except APIError:
                pass
            try:
                container.remove(force=True)
            except APIError:
                pass
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def _exec_one(container, input_container_path: str) -> SandboxResult:
    # `timeout` (GNU coreutils, present in the python:*-slim base image)
    # enforces the per-case limit from inside the container. Sending KILL
    # means the student's code can't catch or ignore it; without
    # --preserve-status, `timeout` itself always exits 124 on a timeout,
    # regardless of which signal killed the child, which is what makes
    # timeout detection below reliable.
    cmd = [
        "sh", "-c",
        f"timeout --signal=KILL {SANDBOX_TIMEOUT_SECONDS}s python /sandbox/solution.py < {input_container_path}",
    ]
    start = time.monotonic()
    exit_code, (stdout_bytes, stderr_bytes) = container.exec_run(cmd, demux=True)
    execution_time_ms = int((time.monotonic() - start) * 1000)

    stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
    stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
    timed_out = exit_code == 124

    if timed_out:
        stderr = f"{stderr}\nExecution timed out after {SANDBOX_TIMEOUT_SECONDS}s." if stderr else \
            f"Execution timed out after {SANDBOX_TIMEOUT_SECONDS}s."

    return SandboxResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        timed_out=timed_out,
        execution_time_ms=execution_time_ms,
    )
