"""Shared header/nav, session helpers, and the change-password dialog used
by every page."""

from nicegui import app, ui

from webapp import data


def current_account() -> dict:
    return app.storage.user.get("account", {})


def require_role(*roles: str) -> dict | None:
    """Call at the top of a page function. Returns the account dict if it
    has one of the given roles, otherwise redirects home and returns None
    -- callers must `return` immediately when they get None back."""
    account = current_account()
    if account.get("role") not in roles:
        ui.navigate.to("/")
        return None
    return account


def logout() -> None:
    app.storage.user.clear()
    ui.navigate.to("/login")


def change_password_dialog(account: dict) -> None:
    with ui.dialog() as dialog, ui.card():
        ui.label("Change password").classes("text-h6")
        old_pw = ui.input("Current password", password=True, password_toggle_button=True).classes("w-72")
        new_pw = ui.input("New password", password=True, password_toggle_button=True).classes("w-72")

        def submit():
            if len(new_pw.value or "") < 8:
                ui.notify("New password must be at least 8 characters.", color="negative")
                return
            if not data.change_own_password(account, old_pw.value, new_pw.value):
                ui.notify("Current password is incorrect.", color="negative")
                return
            ui.notify("Password changed.", color="positive")
            dialog.close()

        with ui.row():
            ui.button("Save", on_click=submit)
            ui.button("Cancel", on_click=dialog.close).props("flat")
    dialog.open()


def top_nav() -> None:
    account = current_account()
    with ui.header().classes("items-center justify-between"):
        with ui.row().classes("items-center gap-4"):
            ui.label("Gryzun").classes("text-bold text-h6")
            if account.get("role") == "student":
                ui.link("My tasks", "/student").classes("text-white")
            if account.get("role") in ("teacher", "admin"):
                ui.link("Teacher", "/teacher").classes("text-white")
            if account.get("role") == "admin":
                ui.link("Admin", "/admin").classes("text-white")
        with ui.row().classes("items-center gap-2"):
            ui.button(f"{account.get('full_name')} ({account.get('role')})", on_click=lambda: change_password_dialog(account)).props("flat color=white")
            ui.button("Log out", on_click=logout).props("flat color=white")
