"""
All database access for the web app goes through this one module.

Existing functionality (tasks, files, submissions) is delegated to the
*unmodified* Grader/db.py -- the canonical copy already used by
Grader/api.py and (as a manual copy) by the root-level notebooks -- so
nothing here duplicates or forks its logic. New functionality (login,
account provisioning, task assignments, teacher review) is implemented
here as new queries using db.py's own db.get_conn() connection helper,
against the additive-only columns/table from
webapp/migrations/001_add_auth_and_assignments.sql.

Submitting a solution is the one exception to "direct DB access": grading
requires the sandboxed execution pipeline (grader.py/sandbox.py, which
need the Docker socket and an Ollama server) that already runs inside the
existing Grader/api.py container. Rather than duplicating that pipeline
and its access requirements into this app, student_submit_solution()
forwards the upload to the existing, running POST /submissions endpoint
over HTTP, exactly like Grader/student_interface.ipynb already does.
"""

import os
import sys
from pathlib import Path

import httpx
import psycopg2.extras
from dotenv import load_dotenv

from webapp.auth import generate_temp_password, hash_password, verify_password

# Loaded explicitly (rather than relying on db.py's own load_dotenv(), which
# searches from the current working directory) so `webapp/.env` is found
# regardless of where this process is launched from.
load_dotenv(Path(__file__).resolve().parent / ".env")

_GRADER_DIR = Path(__file__).resolve().parent.parent / "Grader"
if str(_GRADER_DIR) not in sys.path:
    sys.path.insert(0, str(_GRADER_DIR))

import db  # noqa: E402  (Grader/db.py, unmodified -- see module docstring)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# Direct re-exports: pages import everything through `data`, but these are
# plain pass-throughs to the existing db.py for functionality this app
# doesn't change (task/topic/dataset authoring, raw file access).
list_topics = db.list_topics
create_topic = db.create_topic
list_levels = db.list_levels
list_tasks = db.list_tasks
get_task = db.get_task
create_task = db.create_task
upload_file = db.upload_file
register_file = db.register_file
attach_dataset = db.attach_dataset
get_task_datasets = db.get_task_datasets
build_task_package = db.build_task_package
read_file_bytes = db.read_file_bytes


# --------------------------------------------------------------- auth ------

def authenticate(email: str, password: str) -> dict | None:
    """Checks the users table (teachers/admins) then students. Returns an
    account dict with a normalized 'role', or None on any failure."""
    email = email.strip().lower()
    with db.get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT id, full_name, email, role, password_hash, is_active "
                "FROM users WHERE lower(email) = %s",
                (email,),
            )
            row = cur.fetchone()
            if row is not None:
                if not row["is_active"] or not verify_password(password, row["password_hash"]):
                    return None
                return {"id": str(row["id"]), "full_name": row["full_name"], "email": row["email"], "role": row["role"]}

            cur.execute(
                "SELECT id, full_name, email, password_hash FROM students WHERE lower(email) = %s",
                (email,),
            )
            row = cur.fetchone()
            if row is not None and verify_password(password, row["password_hash"]):
                return {"id": str(row["id"]), "full_name": row["full_name"], "email": row["email"], "role": "student"}
            return None


def set_password(role: str, account_id: str, new_password: str) -> None:
    if role not in ("student", "teacher", "admin"):
        raise ValueError(f"unknown role: {role}")
    table = "students" if role == "student" else "users"
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {table} SET password_hash = %s WHERE id = %s", (hash_password(new_password), account_id))


def change_own_password(current_user: dict, old_password: str, new_password: str) -> bool:
    if authenticate(current_user["email"], old_password) is None:
        return False
    set_password(current_user["role"], current_user["id"], new_password)
    return True


def reset_password(role: str, account_id: str) -> str:
    """Admin/teacher action: issues a fresh temp password for an existing
    account (e.g. one created before this migration, or a forgotten one)."""
    temp_password = generate_temp_password()
    set_password(role, account_id, temp_password)
    return temp_password


# ---------------------------------------------------- account provisioning --

def list_teachers_full():
    """Teachers/admins with account status, for the admin user-management page."""
    with db.get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT id, full_name, email, role, is_active, "
                "(password_hash IS NOT NULL) AS has_password "
                "FROM users ORDER BY full_name"
            )
            return [dict(r) for r in cur.fetchall()]


def create_teacher_account(full_name: str, email: str, role: str = "teacher") -> tuple[str, str]:
    """Admin-only. Returns (user_id, temp_password) -- the temp password is
    shown once and never stored in the clear."""
    if role not in ("teacher", "admin"):
        raise ValueError("role must be 'teacher' or 'admin'")
    temp_password = generate_temp_password()
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (full_name, email, role, password_hash) VALUES (%s, %s, %s, %s) RETURNING id",
                (full_name, email, role, hash_password(temp_password)),
            )
            user_id = cur.fetchone()[0]
    return str(user_id), temp_password


def set_user_active(user_id: str, is_active: bool) -> None:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET is_active = %s WHERE id = %s", (is_active, user_id))


def list_students_full():
    """Students with account status and roster fields, for teacher/admin pages."""
    with db.get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT id, full_name, email, student_number, group_name, "
                "(password_hash IS NOT NULL) AS has_password "
                "FROM students ORDER BY full_name"
            )
            return [dict(r) for r in cur.fetchall()]


def create_student_account(full_name: str, email: str, student_number: str | None = None, group_name: str | None = None) -> tuple[str, str]:
    """Teacher-or-admin. Returns (student_id, temp_password)."""
    temp_password = generate_temp_password()
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO students (full_name, email, student_number, group_name, password_hash) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (full_name, email, student_number or None, group_name or None, hash_password(temp_password)),
            )
            student_id = cur.fetchone()[0]
    return str(student_id), temp_password


def list_groups() -> list[str]:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT group_name FROM students WHERE group_name IS NOT NULL ORDER BY group_name")
            return [r[0] for r in cur.fetchall()]


# -------------------------------------------------------- task assignment --

def is_task_assigned(task_id: str, student_id: str) -> bool:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM task_assignments WHERE task_id = %s AND student_id = %s", (task_id, student_id))
            return cur.fetchone() is not None


def list_my_tasks(student_id: str):
    """Tasks assigned to one student -- this, not 'published', is what
    controls what a student can see and submit to."""
    with db.get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT t.id, t.title, tp.name AS topic, lv.name AS level, t.status, ta.assigned_at
                FROM task_assignments ta
                JOIN tasks t   ON t.id = ta.task_id
                JOIN topics tp ON tp.id = t.topic_id
                JOIN levels lv ON lv.id = t.level_id
                WHERE ta.student_id = %s
                ORDER BY ta.assigned_at DESC
                """,
                (student_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def list_assignees(task_id: str):
    with db.get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT s.id, s.full_name, s.email, s.group_name, ta.assigned_at
                FROM task_assignments ta
                JOIN students s ON s.id = ta.student_id
                WHERE ta.task_id = %s
                ORDER BY s.full_name
                """,
                (task_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def assign_task(task_id: str, student_ids: list[str], assigned_by: str) -> None:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            for student_id in student_ids:
                cur.execute(
                    "INSERT INTO task_assignments (task_id, student_id, assigned_by) VALUES (%s, %s, %s) "
                    "ON CONFLICT (task_id, student_id) DO NOTHING",
                    (task_id, student_id, assigned_by),
                )


def assign_task_to_group(task_id: str, group_name: str, assigned_by: str) -> None:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM students WHERE group_name = %s", (group_name,))
            student_ids = [r[0] for r in cur.fetchall()]
            for student_id in student_ids:
                cur.execute(
                    "INSERT INTO task_assignments (task_id, student_id, assigned_by) VALUES (%s, %s, %s) "
                    "ON CONFLICT (task_id, student_id) DO NOTHING",
                    (task_id, student_id, assigned_by),
                )


def unassign_task(task_id: str, student_id: str) -> None:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM task_assignments WHERE task_id = %s AND student_id = %s", (task_id, student_id))


# ------------------------------------------------------- submissions (student) --

def _student_view(row: dict) -> dict:
    """Same redaction as Grader/api.py's read_submission/list_my_submissions:
    no per-case detail, no expected output, no sample-vs-test labeling."""
    return {
        "id": str(row["id"]),
        "task_id": str(row["task_id"]),
        "task_title": row.get("task_title"),
        "status": row["status"],
        "tests_passed": row["auto_score"],
        "tests_total": row["auto_max_score"],
        "feedback": row["auto_feedback"],
        "human_score": row["human_score"],
        "human_feedback": row["human_feedback"],
        "final_score": row["final_score"],
        "submitted_at": row.get("submitted_at"),
    }


def student_list_submissions(student_id: str):
    return [_student_view(r) for r in db.list_submissions(student_id=student_id)]


def student_get_submission(student_id: str, submission_id: str):
    result = db.get_submission(submission_id)
    if result is None:
        return None
    submission, _test_results = result
    if str(submission["student_id"]) != str(student_id):
        return None
    return _student_view(submission)


def student_download_package(task_id: str, student_id: str):
    """Sample (never hidden-test) input/output files for one assigned task,
    as a zip Path -- same package a teacher can export, but gated by
    assignment rather than open to any task_id."""
    if not is_task_assigned(task_id, student_id):
        return None
    return db.build_task_package(task_id)


def student_submit_solution(student: dict, task_id: str, filename: str, content: bytes) -> dict:
    if not is_task_assigned(task_id, student["id"]):
        return {"error": "This task hasn't been assigned to you."}
    try:
        resp = httpx.post(
            f"{API_BASE_URL}/submissions",
            data={
                "task_id": task_id,
                "student_email": student["email"],
                "student_full_name": student["full_name"],
            },
            files={"file": (filename, content, "text/x-python")},
            timeout=30.0,
        )
    except httpx.HTTPError as e:
        return {"error": f"Could not reach the grading service: {e}"}
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        return {"error": str(detail)}
    return resp.json()


# ------------------------------------------------------- submissions (teacher) --

def teacher_list_submissions(task_id: str | None = None, student_id: str | None = None, status: str | None = None):
    return db.list_submissions(task_id=task_id, student_id=student_id, status=status)


def teacher_get_submission_detail(submission_id: str):
    return db.get_submission_detail(submission_id)


def review_submission(submission_id: str, reviewer_id: str, human_score, human_feedback: str, final_score=None) -> None:
    if final_score is None:
        final_score = human_score
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE submissions
                SET human_score = %s, human_feedback = %s, final_score = %s,
                    reviewed_by = %s, reviewed_at = now()
                WHERE id = %s
                """,
                (human_score, human_feedback, final_score, reviewer_id, submission_id),
            )
