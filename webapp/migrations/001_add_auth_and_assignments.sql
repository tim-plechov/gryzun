-- Additive-only migration: adds login + task-assignment support without
-- changing any existing column that Grader/db.py (and the two notebooks)
-- already rely on. Every existing query in db.py names its columns
-- explicitly (no `SELECT *` feeding positional unpacking), so these
-- additions are safe to run against a live database.
--
-- Apply with:
--   psql "$DATABASE_URL" -f webapp/migrations/001_add_auth_and_assignments.sql

ALTER TABLE users    ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE users    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE students ADD COLUMN IF NOT EXISTS password_hash TEXT;

-- Rows created by the existing notebooks (before this migration) will have
-- password_hash = NULL and can't log into the web app until an admin sets a
-- password for them via the admin "set/reset password" action.

CREATE TABLE IF NOT EXISTS task_assignments (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id      UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    student_id   UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    assigned_by  UUID NOT NULL REFERENCES users(id),
    assigned_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (task_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_assignments_student ON task_assignments(student_id);
CREATE INDEX IF NOT EXISTS idx_assignments_task    ON task_assignments(task_id);
