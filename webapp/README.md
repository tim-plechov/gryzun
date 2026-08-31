# Gryzun web app

A NiceGUI (pure Python, no separate frontend to write) web app that
replaces the two notebooks with a single, login-gated site:

- **Students** log in, see only the tasks their teacher assigned to them,
  submit solutions, and check grades/feedback.
- **Teachers** log in, author tasks with sample/test datasets, assign tasks
  to individual students or whole groups, browse and inspect submissions
  (including hidden test results), and record a human review/score.
- **Admins** additionally manage teacher and student accounts (create,
  deactivate, reset passwords).

There is no self-registration for anyone: an admin creates teacher/admin
accounts, and a teacher or admin creates student accounts. See
`webapp/data.py`'s module docstring for how this app shares the database
with the existing notebooks/`Grader/api.py` without modifying `db.py` or
either of them -- they keep running unchanged.

## One-time setup

1. Apply the additive migration against the same Postgres the rest of
   Gryzun uses:
   ```
   psql "postgresql://<user>:<password>@<host>:<port>/<dbname>" -f webapp/migrations/001_add_auth_and_assignments.sql
   ```
2. Create the first admin account:
   ```
   cd Gryzun
   python -m webapp.create_admin "Your Name" you@example.com
   ```
   This prints a one-time temporary password -- log in with it and change
   it from the account menu (top right).

Accounts created by the *old* notebooks before step 1 (teachers/students
with no password yet) can't log in until an admin uses "Reset password"
on them from the Admin page.

## Running

**Via docker compose** (recommended, alongside the rest of the stack):
add `WEBAPP_STORAGE_SECRET` to your `.env` (see `.env.example`), then
`docker compose up --build` as usual -- the `webapp` service joins `db`,
`minio`, and `api`, and is reachable at `http://localhost:8080`.

**Standalone**, against a Postgres/MinIO/`api.py` already running
elsewhere: copy `webapp/.env.example` to `webapp/.env` and fill it in,
`pip install -r webapp/requirements.txt`, then:
```
python -m webapp.main
```

## Layout

```
webapp/
  main.py           entry point; wires up login-gated routing
  auth.py           password hashing
  data.py           all DB access -- delegates to Grader/db.py unmodified,
                     adds new queries for login/accounts/assignments/review
  create_admin.py   one-off: bootstrap the first admin account
  pages/            the actual UI (login, student, teacher, admin)
  migrations/        additive-only SQL migrations
```
