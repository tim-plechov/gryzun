"""
Database + object-storage helpers for the Gryzun task-authoring interface.

Uploaded files (task datasets, student solutions) live in the `files` table's
`storage_key` column, which is an object key ("<task_id>/<hash>_<name>") in
the MinIO bucket named by MINIO_BUCKET -- see upload_file/read_file_bytes.
DOWNLOADS_ROOT is unrelated to that: it's a local scratch directory only for
build_task_package's zip output.
"""

import hashlib
import io
import mimetypes
import os
import re
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from minio import Minio

load_dotenv()

DB_CONFIG = dict(
    host=os.getenv("PGHOST", "localhost"),
    port=os.getenv("PGPORT", "5432"),
    dbname=os.getenv("PGDATABASE", "gryzun"),
    user=os.getenv("PGUSER", "postgres"),
    password=os.getenv("PGPASSWORD", ""),
)

# The MinIO root user/password (needed to start the `minio` service itself)
# double as its access/secret key, so they're the default here too --
# MINIO_ACCESS_KEY/MINIO_SECRET_KEY only need setting separately if you've
# created a dedicated non-root MinIO user.
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY") or os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY") or os.getenv("MINIO_ROOT_PASSWORD", "")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "gryzun")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

_minio_client = None


def _get_minio() -> Minio:
    """Lazy so importing db.py never requires MinIO to be reachable."""
    global _minio_client
    if _minio_client is None:
        client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=MINIO_SECURE)
        if not client.bucket_exists(MINIO_BUCKET):
            client.make_bucket(MINIO_BUCKET)
        _minio_client = client
    return _minio_client


DOWNLOADS_ROOT = Path(os.getenv("DOWNLOADS_ROOT", Path(__file__).parent / "downloads")).resolve()
DOWNLOADS_ROOT.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_conn():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or uuid.uuid4().hex[:8]


# ---------------------------------------------------------------- teachers --

def list_teachers():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT id, full_name, email FROM users "
                "WHERE role IN ('teacher', 'admin') ORDER BY full_name"
            )
            return cur.fetchall()


def create_teacher(full_name: str, email: str) -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (full_name, email, role) "
                "VALUES (%s, %s, 'teacher') RETURNING id",
                (full_name, email),
            )
            return cur.fetchone()[0]


# ------------------------------------------------------------------ topics --

def list_topics():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, name, slug, parent_id FROM topics ORDER BY name")
            return cur.fetchall()


def create_topic(name: str, parent_id: str | None = None) -> str:
    slug = _slugify(name)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO topics (name, slug, parent_id) "
                "VALUES (%s, %s, %s) RETURNING id",
                (name, slug, parent_id),
            )
            return cur.fetchone()[0]


# ------------------------------------------------------------------ levels --

def list_levels():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, code, name FROM levels ORDER BY sort_order")
            return cur.fetchall()


# ---------------------------------------------------------------- students --

def list_students():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, full_name, email FROM students ORDER BY full_name")
            return [dict(r) for r in cur.fetchall()]


def get_student(student_id: str):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT id, full_name, email, student_number, group_name FROM students WHERE id = %s",
                (student_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_student_by_email(email: str):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT id, full_name, email, student_number, group_name FROM students WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_or_create_student(full_name: str, email: str) -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM students WHERE email = %s", (email,))
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute(
                "INSERT INTO students (full_name, email) VALUES (%s, %s) RETURNING id",
                (full_name, email),
            )
            return cur.fetchone()[0]


# ------------------------------------------------------------------- tasks --

def create_task(title, description, topic_id, level_id, author_id, status="draft") -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tasks (title, description, topic_id, level_id, author_id, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (title, description, topic_id, level_id, author_id, status),
            )
            return cur.fetchone()[0]


def get_task(task_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT id, title, description, topic_id, level_id, author_id, status FROM tasks WHERE id = %s",
                (task_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def list_tasks(topic_id=None, level_id=None, status: str | None = None):
    query = """
        SELECT t.id, t.title, tp.name AS topic, lv.name AS level, t.status, t.created_at
        FROM tasks t
        JOIN topics tp ON tp.id = t.topic_id
        JOIN levels lv ON lv.id = t.level_id
        WHERE 1=1
    """
    params = []
    if topic_id:
        query += " AND t.topic_id = %s"
        params.append(topic_id)
    if level_id:
        query += " AND t.level_id = %s"
        params.append(level_id)
    if status:
        query += " AND t.status = %s"
        params.append(status)
    query += " ORDER BY t.created_at DESC"

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]


def get_task_datasets(task_id):
    """All sample + test cases for a task, each with its input/output storage_key."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT td.id, td.dataset_type, td.order_index,
                       fi.storage_key AS input_storage_key,
                       fo.storage_key AS output_storage_key
                FROM task_datasets td
                JOIN files fi ON fi.id = td.input_file_id
                JOIN files fo ON fo.id = td.output_file_id
                WHERE td.task_id = %s
                ORDER BY td.dataset_type, td.order_index
                """,
                (task_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def build_task_package(task_id: str) -> Path:
    """
    Zips the task description plus its *sample* (open) input/output files
    for download. Test/hidden files are deliberately never included -- they
    stay closed even from this teacher-facing export.
    """
    task = get_task(task_id)
    if task is None:
        raise ValueError(f"No task with id {task_id}")

    sample_datasets = [d for d in get_task_datasets(task_id) if d["dataset_type"] == "sample"]

    zip_path = DOWNLOADS_ROOT / f"{task_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("task.md", f"# {task['title']}\n\n{task['description']}\n")
        for i, ds in enumerate(sample_datasets, 1):
            in_suffix = Path(ds["input_storage_key"]).suffix
            out_suffix = Path(ds["output_storage_key"]).suffix
            zf.writestr(f"sample_{i}_input{in_suffix}", read_file_bytes(ds["input_storage_key"]))
            zf.writestr(f"sample_{i}_output{out_suffix}", read_file_bytes(ds["output_storage_key"]))
    return zip_path


# ------------------------------------------------------------------- files --

def upload_file(content: bytes, original_name: str, task_id: str) -> dict:
    """Uploads bytes to MinIO under <task_id>/<hash>_<name> and returns metadata for the `files` row."""
    checksum = hashlib.sha256(content).hexdigest()
    ext = Path(original_name).suffix.lstrip(".").lower() or "bin"
    storage_key = f"{task_id}/{checksum[:16]}_{original_name}"
    mime_type, _ = mimetypes.guess_type(original_name)

    _get_minio().put_object(
        MINIO_BUCKET,
        storage_key,
        io.BytesIO(content),
        length=len(content),
        content_type=mime_type or "application/octet-stream",
    )

    return dict(
        storage_key=storage_key,
        original_name=original_name,
        format=ext,
        mime_type=mime_type,
        size_bytes=len(content),
        checksum=checksum,
    )


def register_file(meta: dict, uploaded_by: str, metadata: dict | None = None) -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO files
                    (storage_key, original_name, format, mime_type, size_bytes, checksum, metadata, uploaded_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    meta["storage_key"],
                    meta["original_name"],
                    meta["format"],
                    meta["mime_type"],
                    meta["size_bytes"],
                    meta["checksum"],
                    psycopg2.extras.Json(metadata or {}),
                    uploaded_by,
                ),
            )
            return cur.fetchone()[0]


def attach_dataset(task_id: str, input_file_id: str, output_file_id: str, dataset_type: str, order_index: int) -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO task_datasets (task_id, input_file_id, output_file_id, dataset_type, order_index)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (task_id, input_file_id, output_file_id, dataset_type, order_index),
            )
            return cur.fetchone()[0]


def read_file_bytes(storage_key: str) -> bytes:
    response = _get_minio().get_object(MINIO_BUCKET, storage_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


# -------------------------------------------------------------- submissions --

def create_submission(task_id: str, student_id: str, code_file_id: str) -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO submissions (task_id, student_id, code_file_id, status)
                VALUES (%s, %s, %s, 'submitted')
                RETURNING id
                """,
                (task_id, student_id, code_file_id),
            )
            return cur.fetchone()[0]


def set_submission_status(submission_id: str, status: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE submissions SET status = %s WHERE id = %s", (status, submission_id))


def set_submission_result(
    submission_id: str,
    *,
    auto_score,
    auto_max_score,
    auto_feedback: str,
    auto_feedback_model: str | None,
    status: str,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE submissions
                SET auto_score = %s, auto_max_score = %s, auto_checked_at = now(),
                    auto_feedback = %s, auto_feedback_model = %s, auto_feedback_generated_at = now(),
                    status = %s
                WHERE id = %s
                """,
                (auto_score, auto_max_score, auto_feedback, auto_feedback_model, status, submission_id),
            )


def insert_test_result(
    submission_id: str,
    task_dataset_id: str,
    passed: bool,
    stdout: str,
    stderr: str,
    exit_code: int | None,
    execution_time_ms: int,
) -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO submission_test_results
                    (submission_id, task_dataset_id, passed, stdout, stderr, exit_code, execution_time_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (submission_id, task_dataset_id, passed, stdout, stderr, exit_code, execution_time_ms),
            )
            return cur.fetchone()[0]


def get_submission(submission_id: str):
    """Returns (submission_dict, [test_result_dict, ...]) or None if not found."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT s.*, f.storage_key AS code_storage_key
                FROM submissions s
                LEFT JOIN files f ON f.id = s.code_file_id
                WHERE s.id = %s
                """,
                (submission_id,),
            )
            submission = cur.fetchone()
            if submission is None:
                return None

            cur.execute(
                """
                SELECT str.id, str.task_dataset_id, td.dataset_type, str.passed,
                       str.stdout, str.stderr, str.exit_code, str.execution_time_ms
                FROM submission_test_results str
                JOIN task_datasets td ON td.id = str.task_dataset_id
                WHERE str.submission_id = %s
                ORDER BY td.dataset_type, td.order_index
                """,
                (submission_id,),
            )
            results = [dict(r) for r in cur.fetchall()]
            return dict(submission), results


def get_submission_detail(submission_id: str):
    """
    Full teacher-facing view of one submission: the submission row, the task
    it was for, the student, the student's own code, and every test result
    -- including hidden ('test') ones -- with full stdout/stderr. Unlike the
    student-facing API, nothing here is redacted.
    """
    result = get_submission(submission_id)
    if result is None:
        return None
    submission, test_results = result
    task = get_task(submission["task_id"])
    student = get_student(submission["student_id"])
    code = None
    if submission.get("code_storage_key"):
        code = read_file_bytes(submission["code_storage_key"]).decode("utf-8", errors="replace")
    return {
        "submission": submission,
        "task": task,
        "student": student,
        "code": code,
        "test_results": test_results,
    }


def list_submissions(task_id: str | None = None, student_id: str | None = None, status: str | None = None):
    """Teacher-facing view across submissions, optionally filtered by task/student/status."""
    query = """
        SELECT s.id, s.status, s.auto_score, s.auto_max_score, s.submitted_at, s.auto_checked_at,
               s.auto_feedback, s.human_score, s.human_feedback, s.final_score,
               t.id AS task_id, t.title AS task_title,
               st.id AS student_id, st.full_name AS student_name, st.email AS student_email
        FROM submissions s
        JOIN tasks t ON t.id = s.task_id
        JOIN students st ON st.id = s.student_id
        WHERE 1=1
    """
    params = []
    if task_id:
        query += " AND s.task_id = %s"
        params.append(task_id)
    if student_id:
        query += " AND s.student_id = %s"
        params.append(student_id)
    if status:
        query += " AND s.status = %s"
        params.append(status)
    query += " ORDER BY s.submitted_at DESC"

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]
