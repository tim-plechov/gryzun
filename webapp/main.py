"""
Entry point for the Gryzun web app.

Runs standalone alongside the existing stack (teacher_interface.ipynb,
Grader/student_interface.ipynb, Grader/api.py) -- see the module docstring
in webapp/data.py for how it shares the same Postgres/MinIO without
touching any existing code. Run with:

    python -m webapp.main

Requires PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD, MINIO_* (same
variables Grader/db.py already reads), API_BASE_URL (where Grader/api.py
is reachable), and NICEGUI_STORAGE_SECRET (any long random string --
signs the session cookie; keep it stable across restarts or everyone gets
logged out).
"""

import os

from nicegui import Client, app, ui
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

UNRESTRICTED_ROUTES = {"/login"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not app.storage.user.get("authenticated", False):
            if request.url.path in Client.page_routes.values() and request.url.path not in UNRESTRICTED_ROUTES:
                app.storage.user["referrer_path"] = request.url.path
                return RedirectResponse("/login")
        return await call_next(request)


app.add_middleware(AuthMiddleware)

# Import after the middleware is registered -- this is what actually
# registers every @ui.page route.
from webapp.pages import admin, home, login, student, teacher  # noqa: E402,F401

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        title="Gryzun",
        storage_secret=os.environ["NICEGUI_STORAGE_SECRET"],
        reload=False,
    )
