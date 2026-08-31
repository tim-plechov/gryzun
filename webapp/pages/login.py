from nicegui import app, ui

from webapp import data

ROLE_HOME = {"student": "/student", "teacher": "/teacher", "admin": "/teacher"}


@ui.page("/login")
def login_page() -> None:
    if app.storage.user.get("authenticated"):
        ui.navigate.to("/")
        return

    def try_login() -> None:
        account = data.authenticate(email.value or "", password.value or "")
        if account is None:
            ui.notify("Invalid email/password, or this account isn't active.", color="negative")
            return
        app.storage.user["authenticated"] = True
        app.storage.user["account"] = account
        target = app.storage.user.pop("referrer_path", None) or ROLE_HOME.get(account["role"], "/")
        ui.navigate.to(target)

    with ui.card().classes("absolute-center").style("min-width: 340px"):
        ui.label("Gryzun").classes("text-h5")
        ui.label("Sign in with the account your teacher/admin created for you.").classes("text-caption")
        email = ui.input("Email").classes("w-full").props("autofocus")
        password = ui.input("Password", password=True, password_toggle_button=True).classes("w-full")
        password.on("keydown.enter", try_login)
        ui.button("Log in", on_click=try_login).classes("w-full").props("color=primary")
