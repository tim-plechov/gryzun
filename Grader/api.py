"""
API for students to submit solutions and poll their grading status/results.

POST /submissions stores the file and returns immediately with a
submission_id (status="submitted"); grading (LLM safety check, sandboxed
execution against every task dataset, scoring, LLM feedback) runs in the
background via grader.process_submission. Poll GET /submissions/{id} for
status and results.
"""

import ast

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile

import db
import grader

app = FastAPI(title="Gryzun grading API")

MAX_UPLOAD_BYTES = 1_000_000  # 1 MB


@app.post("/submissions", status_code=202)
async def submit_solution(
    background_tasks: BackgroundTasks,
    task_id: str = Form(...),
    student_email: str = Form(...),
    student_full_name: str = Form(...),
    file: UploadFile = File(...),
):
    if not (file.filename or "").endswith(".py"):
        raise HTTPException(400, "Solution must be a .py file.")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"File too large (max {MAX_UPLOAD_BYTES} bytes).")

    try:
        source = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "File is not valid UTF-8 text.")

    try:
        ast.parse(source)
    except SyntaxError as e:
        raise HTTPException(400, f"File is not valid Python: {e}")

    task = db.get_task(task_id)
    if task is None:
        raise HTTPException(404, "Task not found.")

    student_id = db.get_or_create_student(student_full_name, student_email)

    meta = db.upload_file(content, file.filename, task_id)
    code_file_id = db.register_file(meta, uploaded_by=None)
    submission_id = db.create_submission(task_id, student_id, code_file_id)

    background_tasks.add_task(grader.process_submission, submission_id)

    return {"submission_id": submission_id, "status": "submitted"}


@app.get("/submissions/{submission_id}")
def read_submission(submission_id: str):
    """
    Deliberately minimal: a student may see the processing status, the LLM
    feedback, and how many cases passed out of how many -- nothing about
    individual cases (stdout/stderr/expected output, which dataset_type they
    were), so hidden-test content can never leak through this endpoint.
    """
    result = db.get_submission(submission_id)
    if result is None:
        raise HTTPException(404, "Submission not found.")
    submission, _test_results = result

    return {
        "id": submission["id"],
        "task_id": submission["task_id"],
        "status": submission["status"],
        "tests_passed": submission["auto_score"],
        "tests_total": submission["auto_max_score"],
        "feedback": submission["auto_feedback"],
        "human_score": submission["human_score"],
        "human_feedback": submission["human_feedback"],
        "final_score": submission["final_score"],
    }


@app.get("/tasks")
def list_published_tasks():
    """Tasks a student is allowed to see and submit against."""
    return db.list_tasks(status="published")


@app.get("/students/{email}/submissions")
def list_my_submissions(email: str, task_id: str | None = None):
    """A student's own submission history -- same redaction as read_submission."""
    student = db.get_student_by_email(email)
    if student is None:
        raise HTTPException(404, "Student not found.")

    submissions = db.list_submissions(task_id=task_id, student_id=student["id"])
    return [
        {
            "id": s["id"],
            "task_id": s["task_id"],
            "task_title": s["task_title"],
            "status": s["status"],
            "tests_passed": s["auto_score"],
            "tests_total": s["auto_max_score"],
            "feedback": s["auto_feedback"],
            "human_score": s["human_score"],
            "human_feedback": s["human_feedback"],
            "final_score": s["final_score"],
            "submitted_at": s["submitted_at"],
        }
        for s in submissions
    ]
