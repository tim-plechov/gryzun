from nicegui import ui

from webapp import data
from webapp.pages.common import require_role, top_nav


@ui.page("/admin")
def admin_page() -> None:
    account = require_role("admin")
    if account is None:
        return
    top_nav()

    with ui.tabs().classes("w-full") as tabs:
        teachers_tab = ui.tab("Teachers & admins")
        students_tab = ui.tab("Students")

    with ui.tab_panels(tabs, value=teachers_tab).classes("w-full"):
        with ui.tab_panel(teachers_tab):
            _teachers_panel()
        with ui.tab_panel(students_tab):
            _students_panel()


def _show_temp_password(who: str, temp_password: str) -> None:
    with ui.dialog() as dialog, ui.card():
        ui.label(f"Password for {who}").classes("text-h6")
        ui.label("Shown once -- copy it now. They should change it after logging in.").classes("text-caption")
        ui.input(value=temp_password).props("readonly").classes("w-72")
        ui.button("Close", on_click=dialog.close)
    dialog.open()


def _teachers_panel() -> None:
    table = ui.table(
        columns=[
            {"name": "full_name", "label": "Name", "field": "full_name", "sortable": True, "align": "left"},
            {"name": "email", "label": "Email", "field": "email", "sortable": True, "align": "left"},
            {"name": "role", "label": "Role", "field": "role", "sortable": True, "align": "left"},
            {"name": "is_active", "label": "Active", "field": "is_active", "sortable": True, "align": "left"},
            {"name": "has_password", "label": "Password set", "field": "has_password", "align": "left"},
        ],
        rows=[],
        row_key="id",
    ).classes("w-full")

    def refresh() -> None:
        table.rows = data.list_teachers_full()
        table.update()
        picker.options = {u["id"]: f"{u['full_name']} <{u['email']}>" for u in table.rows}
        picker.update()

    ui.button("Refresh", on_click=refresh).props("outline")
    refresh()

    ui.separator().classes("q-my-md")
    ui.label("Add a teacher or admin").classes("text-h6")
    with ui.row():
        name_input = ui.input("Full name").classes("w-64")
        email_input = ui.input("Email").classes("w-64")
        role_select = ui.select({"teacher": "teacher", "admin": "admin"}, value="teacher", label="Role").classes("w-32")

    def create() -> None:
        name, email = (name_input.value or "").strip(), (email_input.value or "").strip()
        if not name or not email:
            ui.notify("Full name and email are required.", color="negative")
            return
        user_id, temp_password = data.create_teacher_account(name, email, role_select.value)
        name_input.value = ""
        email_input.value = ""
        refresh()
        _show_temp_password(name, temp_password)

    ui.button("+ Add", on_click=create).props("color=primary")

    ui.separator().classes("q-my-md")
    ui.label("Manage an existing account").classes("text-h6")
    picker = ui.select({}, label="Account").classes("w-96")
    with ui.row():
        def deactivate() -> None:
            if picker.value:
                data.set_user_active(picker.value, False)
                refresh()

        def activate() -> None:
            if picker.value:
                data.set_user_active(picker.value, True)
                refresh()

        def reset_pw() -> None:
            if not picker.value:
                return
            temp_password = data.reset_password("teacher", picker.value)
            label = next((u["full_name"] for u in table.rows if u["id"] == picker.value), "account")
            _show_temp_password(label, temp_password)

        ui.button("Deactivate", on_click=deactivate).props("outline color=negative")
        ui.button("Activate", on_click=activate).props("outline color=positive")
        ui.button("Reset password", on_click=reset_pw).props("outline")


def _students_panel() -> None:
    table = ui.table(
        columns=[
            {"name": "full_name", "label": "Name", "field": "full_name", "sortable": True, "align": "left"},
            {"name": "email", "label": "Email", "field": "email", "sortable": True, "align": "left"},
            {"name": "student_number", "label": "Student #", "field": "student_number", "sortable": True, "align": "left"},
            {"name": "group_name", "label": "Group", "field": "group_name", "sortable": True, "align": "left"},
            {"name": "has_password", "label": "Password set", "field": "has_password", "align": "left"},
        ],
        rows=[],
        row_key="id",
    ).classes("w-full")

    def refresh() -> None:
        table.rows = data.list_students_full()
        table.update()
        picker.options = {s["id"]: f"{s['full_name']} <{s['email']}>" for s in table.rows}
        picker.update()

    ui.button("Refresh", on_click=refresh).props("outline")
    refresh()

    ui.separator().classes("q-my-md")
    ui.label("Add a student").classes("text-h6")
    with ui.row():
        name_input = ui.input("Full name").classes("w-64")
        email_input = ui.input("Email").classes("w-64")
        number_input = ui.input("Student number (optional)").classes("w-40")
        group_input = ui.input("Group (optional)").classes("w-40")

    def create() -> None:
        name, email = (name_input.value or "").strip(), (email_input.value or "").strip()
        if not name or not email:
            ui.notify("Full name and email are required.", color="negative")
            return
        student_id, temp_password = data.create_student_account(
            name, email, (number_input.value or "").strip() or None, (group_input.value or "").strip() or None
        )
        name_input.value = ""
        email_input.value = ""
        number_input.value = ""
        group_input.value = ""
        refresh()
        _show_temp_password(name, temp_password)

    ui.button("+ Add", on_click=create).props("color=primary")

    ui.separator().classes("q-my-md")
    ui.label("Manage an existing account").classes("text-h6")
    picker = ui.select({}, label="Student").classes("w-96")

    def reset_pw() -> None:
        if not picker.value:
            return
        temp_password = data.reset_password("student", picker.value)
        label = next((s["full_name"] for s in table.rows if s["id"] == picker.value), "account")
        _show_temp_password(label, temp_password)

    ui.button("Reset password", on_click=reset_pw).props("outline")
