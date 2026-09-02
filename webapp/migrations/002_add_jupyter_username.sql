-- Additive-only, same rules as 001: no existing db.py query is affected
-- (list_students/get_student/get_student_by_email all name explicit
-- columns, so a new column is invisible to them).
--
-- Apply with:
--   psql "$DATABASE_URL" -f webapp/migrations/002_add_jupyter_username.sql

ALTER TABLE students ADD COLUMN IF NOT EXISTS jupyter_username TEXT UNIQUE;
