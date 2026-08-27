"""
Background pipeline for a single submission: LLM safety check -> sandboxed
execution against every task_dataset (sample + test) -> scoring -> LLM
feedback. Invoked from the API as a background task right after a
submission row is created with status='submitted'.
"""

import logging

import db
import llm
import sandbox

logger = logging.getLogger("grader")

# Truncate stored/prompted stdout+stderr so a runaway print loop can't blow
# up the DB row or the feedback prompt.
MAX_SNIPPET_CHARS = 2000


def process_submission(submission_id: str) -> None:
    try:
        _process(submission_id)
    except Exception:
        logger.exception("Grading failed for submission %s", submission_id)
        db.set_submission_status(submission_id, "needs_review")


def _process(submission_id: str) -> None:
    db.set_submission_status(submission_id, "checking")

    submission, _ = db.get_submission(submission_id)
    task = db.get_task(submission["task_id"])
    code = db.read_file_bytes(submission["code_storage_key"]).decode("utf-8", errors="replace")

    dangerous, reason = llm.check_dangerous(code)
    if dangerous is None:
        db.set_submission_result(
            submission_id,
            auto_score=None,
            auto_max_score=None,
            auto_feedback=f"Automated safety check could not be completed: {reason}",
            auto_feedback_model=llm.OLLAMA_SAFETY_MODEL,
            status="needs_review",
        )
        return
    if dangerous:
        db.set_submission_result(
            submission_id,
            auto_score=0,
            auto_max_score=0,
            auto_feedback=f"Submission was not run: flagged as unsafe by automated review ({reason}).",
            auto_feedback_model=llm.OLLAMA_SAFETY_MODEL,
            status="rejected",
        )
        return

    datasets = db.get_task_datasets(submission["task_id"])
    if not datasets:
        db.set_submission_result(
            submission_id,
            auto_score=None,
            auto_max_score=None,
            auto_feedback="This task has no sample or test datasets to check against yet.",
            auto_feedback_model=None,
            status="needs_review",
        )
        return

    results_by_dataset = sandbox.run_all(submission["code_storage_key"], datasets)

    passed_count = 0
    sample_details = []
    test_failed_count = 0

    for ds in datasets:
        result = results_by_dataset[ds["id"]]
        expected = db.read_file_bytes(ds["output_storage_key"]).decode("utf-8", errors="replace")
        passed = result.exit_code == 0 and result.stdout.strip() == expected.strip()

        if passed:
            passed_count += 1
        elif ds["dataset_type"] == "test":
            test_failed_count += 1

        db.insert_test_result(
            submission_id=submission_id,
            task_dataset_id=ds["id"],
            passed=passed,
            stdout=result.stdout[:MAX_SNIPPET_CHARS],
            stderr=result.stderr[:MAX_SNIPPET_CHARS],
            exit_code=result.exit_code,
            execution_time_ms=result.execution_time_ms,
        )

        # Sample cases are visible to students, so it's fine to hand their
        # expected/actual output to the feedback model. Hidden test-case
        # content never goes into the prompt (see summary below).
        if ds["dataset_type"] == "sample":
            sample_details.append(dict(
                passed=passed,
                expected=expected[:MAX_SNIPPET_CHARS],
                actual=result.stdout[:MAX_SNIPPET_CHARS],
                stderr=result.stderr[:MAX_SNIPPET_CHARS],
            ))

    total = len(datasets)
    summary_lines = [f"{passed_count}/{total} total cases passed."]
    for i, d in enumerate(sample_details, 1):
        summary_lines.append(f"Sample case {i}: {'PASSED' if d['passed'] else 'FAILED'}")
        if not d["passed"]:
            summary_lines.append(
                f"  expected: {d['expected']!r}\n  actual: {d['actual']!r}\n  stderr: {d['stderr']!r}"
            )
    if test_failed_count:
        summary_lines.append(f"{test_failed_count} hidden test case(s) failed (details withheld).")
    summary = "\n".join(summary_lines)

    feedback = llm.generate_feedback(task["title"], task["description"], code, summary)

    db.set_submission_result(
        submission_id,
        auto_score=passed_count,
        auto_max_score=total,
        auto_feedback=feedback,
        auto_feedback_model=llm.OLLAMA_FEEDBACK_MODEL,
        status="checked",
    )
