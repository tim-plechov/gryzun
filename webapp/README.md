# Gryzun web app

A NiceGUI (pure Python, no separate frontend to write) web app that
replaces the two notebooks with a single, login-gated site:

- **Students** log in, see only the tasks their teacher assigned to them,
  download sample inputs, submit solutions, and check grades/feedback.
- **Teachers** log in, author tasks with sample/test datasets, assign tasks
  to individual students or whole groups, browse and inspect submissions
  (including hidden test results), and record a human review/score.
- **Admins** can do everything a teacher can, and additionally manage
  accounts: create teachers, admins and students, deactivate/reactivate
  staff, reset passwords, and set students' JupyterHub usernames.

There is no self-registration for anyone: all accounts are created by an
admin from the Admin page. See `webapp/data.py`'s module docstring for how
this app shares the database with the existing notebooks/`Grader/api.py`
without modifying `db.py` or either of them -- they keep running unchanged.

The full tour of the interface is in
[Using the web interface](#using-the-web-interface) below. A
Russian-language user guide for students, teachers and admins is in
[user.md](user.md).

## One-time setup

1. Apply the additive migrations against the same Postgres the rest of
   Gryzun uses (run them in order):
   ```
   psql "postgresql://<user>:<password>@<host>:<port>/<dbname>" -f webapp/migrations/001_add_auth_and_assignments.sql
   psql "postgresql://<user>:<password>@<host>:<port>/<dbname>" -f webapp/migrations/002_add_jupyter_username.sql
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

## JupyterHub integration

If a student has a `jupyter_username` on file (set from the Admin page, or
when they're created), assigning them a task copies its description and
sample input files into their JupyterHub volume on disk, at
`<JUPYTER_VOLUMES_ROOT>/jupyterhub-user-<username>/_data/assigned-tasks/<task>/`
-- the naming DockerSpawner uses by default for one volume per user. This
is best-effort: the task assignment itself always succeeds even if the
student has no Jupyter username yet, or their volume doesn't exist yet
because they've never logged into JupyterHub (the teacher sees which
students failed and why, and can retry with "Re-copy files to Jupyter"
once it's fixed).

This needs the host directory bind-mounted into the `webapp` container
(already wired up in `docker-compose.yml`) and `JUPYTER_VOLUMES_ROOT` set
correctly for your setup -- see `.env.example`. Two things worth verifying
on your actual server, since they weren't testable from here:
- That `jupyterhub-user-<username>/_data` is really the right path for
  your JupyterHub/DockerSpawner config -- some setups use a different
  volume naming pattern.
- That the Jupyter container's own user can actually read the copied
  files. They're written world-readable (0644/0755), which is usually
  enough regardless of UID, but if not, set `JUPYTER_CHOWN_UID`
  (and `JUPYTER_CHOWN_GID`, if different) to chown them to whatever UID
  Jupyter's container runs as.

## Using the web interface

### Roles at a glance

| | Student | Teacher | Admin |
|---|:---:|:---:|:---:|
| Lands on after login | `/student` | `/teacher` | `/teacher` |
| Header links | My tasks | Teacher | Teacher, Admin |
| See tasks | only ones assigned to them | all tasks | all tasks |
| Download task materials | sample **inputs** only, for assigned tasks | description + sample inputs **and** expected outputs | same as teacher |
| Submit solutions | yes (assigned tasks only) | -- | -- |
| Create / edit status / delete tasks | -- | yes | yes |
| Assign tasks to students or groups | -- | yes | yes |
| See submissions | only their own | everyone's | everyone's |
| See hidden test cases, code, stdout/stderr | no | yes | yes |
| Record human score and feedback | -- | yes | yes |
| Create accounts, reset passwords | -- | -- | yes |
| Deactivate/activate teacher/admin accounts | -- | -- | yes |
| Set a student's Jupyter username | -- | -- | yes |
| Change own password | yes | yes | yes |

Teachers aren't scoped to "their own" tasks or students: every teacher
sees and can manage every task, assignment and submission. Admins get the
full Teacher page plus the Admin page; there's no separate admin-only
view of tasks.

### Signing in and the common header

- `/login` takes an email and password (Enter submits). Login fails with
  the same message for a wrong password, an unknown email, a deactivated
  teacher/admin account, or an account that has no password yet (e.g.
  one created by the old notebooks -- an admin must "Reset password" it
  first). Email matching is case-insensitive.
- Any other page visited while logged out redirects to `/login` and, after
  a successful login, back to the page originally requested. Otherwise
  the user lands on their role's home page (`/` does the same redirect).
- Visiting a page for a different role (e.g. a student opening `/admin`)
  just redirects to `/`.
- The header shows the links for the user's role, a button with their
  name and role, which opens the **Change password** dialog (asks for the
  current password; new password must be at least 8 characters), and
  **Log out**.
- The session is stored in a signed cookie (`NICEGUI_STORAGE_SECRET` /
  `WEBAPP_STORAGE_SECRET`); changing that secret logs everyone out. The
  role is captured at login, so role or activation changes take effect
  the next time that person logs in.

### Student interface (`/student`)

A single page, top to bottom:

1. **My tasks** -- a sortable table (title, topic, level, assigned date)
   of the tasks assigned to this student. Assignment, not the task's
   draft/published/archived status, is what decides visibility: an
   assigned task shows up whatever its status, and an unassigned one never
   does.
2. **Submit a solution**
   - Pick a task from the dropdown.
   - **Download sample input(s)** -- a zip with `task.md` (title and
     description) and `sample_N_input.*` files. Expected outputs and the
     hidden test cases are never included. If the student has a Jupyter
     username, the same files were also copied into their JupyterHub home
     under `assigned-tasks/` when the task was assigned.
   - Upload a single `.py` file (it's loaded immediately; the caption shows
     its name and size), then click **Submit**. The file is forwarded to the
     grading API (`Grader/api.py`), which rejects files that aren't `.py`,
     are over 1 MB, aren't UTF-8, or don't parse as Python -- the error is
     shown under the button. On success the page shows the new submission
     id and status `submitted`.
3. **My submissions** -- every submission this student has made: task,
   status, auto score (`tests passed / total`), final score, submitted
   date. Grading runs in the background (safety check, sandboxed run
   against all test cases, LLM feedback), so click **Refresh** to see the
   status move from `submitted` through `checking` to `checked` (or
   `needs_review`/`rejected`).
4. **Feedback for one submission** -- pick a submission and click **Show**
   to see its status, auto score, the automated feedback, and, once a
   teacher has reviewed it, the teacher's feedback and final score.

Students see only aggregate results: never per-test-case results, other
students' submissions, expected outputs, or which cases were sample vs.
hidden.

### Teacher interface (`/teacher`, teachers and admins)

Three tabs.

#### Add task

- **Topic** -- pick an existing one, or type a name and click
  **+ Add topic** to create and select it.
- **Level**, **Title**, **Description** (Markdown), and **Status**
  (`draft` by default; `published` or `archived` also allowed). Title,
  description, topic and level are required.
- Four upload boxes, each accepting multiple files: **Sample input(s)**,
  **Sample output(s)**, **Test input(s)**, **Test output(s)**. Inputs and
  outputs of each kind are paired **by sorted filename**, so the counts
  must match (e.g. `01.in`/`01.out`, `02.in`/`02.out`). Sample cases are
  what students can download; test cases are hidden and used only for
  auto-grading.
- **Create task** saves the task, uploads the files to MinIO, and lists
  each attached case (`sample case 0: 01.in -> 01.out`, ...). The form
  then clears the title, description and uploads, keeping topic/level for
  the next task.

#### Tasks & assignments

- Filter by topic, level and status, then **Refresh**. The table lists
  title, topic, level, status and creation date.
- Choose a task in **Manage this task** to open its controls:
  - **Download sample package (.zip)** -- `task.md` plus sample inputs
    *and* their expected outputs, for checking the task itself. Hidden
    test cases are never exported, even here.
  - **Status** + **Update status** -- switch between draft, published and
    archived. (Status is bookkeeping for teachers; it doesn't change what
    students see -- assignment does.)
  - **Delete task** -- asks for confirmation, then removes the task with
    its datasets and assignments. Blocked if anyone has already submitted
    to it; archive the task instead.
  - **Assign this task to students** -- multi-select students (shown with
    their email and group) and click **Assign selected students**, or pick
    a group and click **Assign group** to assign every student in it.
    Assigning also copies the task description and sample inputs into
    each student's JupyterHub volume (see
    [JupyterHub integration](#jupyterhub-integration)); the notification
    says which students, if any, that copy failed for and why. The
    assignment itself succeeds regardless.
  - **Currently assigned** -- table of assignees (name, email, group,
    assigned date). Pick one in **Manage an assignee** to **Unassign**
    them (their past submissions are kept) or **Re-copy files to Jupyter**
    after fixing whatever made the copy fail.

#### Submissions & review

- Filter by task, student and status (`submitted`, `checking`, `checked`,
  `needs_review`, `rejected`), then **Refresh**. The table shows
  submitted date, student, task, status, auto score and submission id.
- Paste a submission id into **Inspect a submission** and click
  **Inspect** to see:
  - status, student, task, submission time, auto score and the LLM model
    that wrote the feedback;
  - the automated feedback;
  - the task description (collapsed) and the student's code;
  - per-case test results for **all** cases, hidden ones included: type
    (sample/test), passed, exit code, run time, and stdout/stderr
    (truncated to 1000 characters).
- **Review** -- enter a **Human score**, an optional **Final score**
  (defaults to the human score if left empty) and **Feedback to student**,
  then **Save review**. The student sees the feedback and final score in
  their "Feedback for one submission" view. Saving again overwrites the
  previous review and records who reviewed it and when.

### Admin interface (`/admin`, admins only)

Two tabs. Every account created or reset here gets a random 12-character
temporary password, shown **once** in a dialog -- copy it and pass it on;
the user should change it from the header after logging in.

#### Teachers & admins

- Table of staff accounts: name, email, role, active, whether a password
  is set. **Refresh** reloads it.
- **Add a teacher or admin** -- full name, email, role, then **+ Add**.
- **Manage an existing account** -- pick an account, then:
  - **Deactivate** / **Activate** -- a deactivated account can't log in
    (an already-open session lasts until it logs out);
  - **Reset password** -- issues a new temporary password.

#### Students

- Table of students: name, email, student number, group, Jupyter
  username, whether a password is set.
- **Add a student** -- full name and email are required; student number,
  group and Jupyter username are optional. The group is what the
  teacher's **Assign group** uses, so keep group names consistent.
- **Manage an existing account** -- pick a student, then:
  - **Reset password**;
  - **Save Jupyter username** -- sets (or, if left empty, clears) the
    username used to find their JupyterHub volume. Tasks assigned before
    it was set can be copied over with **Re-copy files to Jupyter** on
    the Teacher page.

Student accounts have no activate/deactivate switch; to stop a student
from logging in, reset their password and don't share the new one.

### Typical workflow

1. Admin creates teacher accounts and student accounts (with groups and,
   if JupyterHub is used, Jupyter usernames) and hands out the temporary
   passwords.
2. Teacher creates a task with sample and test cases, then assigns it to
   students or a group.
3. Students download the sample inputs (or find them in JupyterHub),
   write a solution, and submit it.
4. The grading API runs it against every case and writes an auto score
   and feedback.
5. Teacher inspects submissions, especially `needs_review` ones, and
   saves a human score, final score and feedback.
6. Students check their final score and teacher feedback.

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
