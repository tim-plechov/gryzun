from nicegui import events, ui

from webapp import data
from webapp.pages.common import require_role, top_nav


@ui.page("/student")
def student_page() -> None:
    account = require_role("student")
    if account is None:
        return
    top_nav()

    ui.label("My tasks").classes("text-h6 q-mt-md")
    ui.label("Only tasks your teacher has assigned to you show up here.").classes("text-caption")
    tasks = data.list_my_tasks(account["id"])
    ui.table(
        columns=[
            {"name": "title", "label": "Title", "field": "title", "sortable": True, "align": "left"},
            {"name": "topic", "label": "Topic", "field": "topic", "sortable": True, "align": "left"},
            {"name": "level", "label": "Level", "field": "level", "sortable": True, "align": "left"},
            {"name": "assigned_at", "label": "Assigned", "field": "assigned_at", "sortable": True, "align": "left"},
        ],
        rows=tasks,
        row_key="id",
    ).classes("w-full")

    ui.separator().classes("q-my-md")
    ui.label("Submit a solution").classes("text-h6")
    task_options = {t["id"]: f"{t['title']} ({t['topic']} / {t['level']})" for t in tasks}
    task_select = ui.select(task_options, label="Task").classes("w-96")

    def download_samples() -> None:
        if not task_select.value:
            ui.notify("Pick a task first.", color="negative")
            return
        zip_path = data.student_download_package(task_select.value, account["id"])
        if zip_path is None:
            ui.notify("This task hasn't been assigned to you.", color="negative")
            return
        ui.download(zip_path.read_bytes(), zip_path.name)

    ui.button("Download sample input/output", on_click=download_samples).props("outline")

    uploaded: dict = {}
    upload_label = ui.label("No file uploaded yet.").classes("text-caption")

    def handle_upload(e: events.UploadEventArguments) -> None:
        uploaded["name"] = e.name
        uploaded["content"] = e.content.read()
        upload_label.set_text(f"Loaded {e.name} ({len(uploaded['content'])} bytes).")

    ui.upload(label="Solution (.py file)", on_upload=handle_upload, auto_upload=True).props("accept=.py").classes("w-96")

    submit_result = ui.column()

    def do_submit() -> None:
        submit_result.clear()
        if not task_select.value:
            ui.notify("Pick a task.", color="negative")
            return
        if "content" not in uploaded:
            ui.notify("Upload a .py file first.", color="negative")
            return
        result = data.student_submit_solution(account, task_select.value, uploaded["name"], uploaded["content"])
        with submit_result:
            if "error" in result:
                ui.label(f"Error: {result['error']}").classes("text-negative")
            else:
                ui.label(f"Submitted -- id {result['submission_id']}, status {result['status']}.").classes("text-positive")
        refresh_submissions()

    ui.button("Submit", on_click=do_submit).props("color=primary")

    ui.separator().classes("q-my-md")
    ui.label("My submissions").classes("text-h6")
    subs_table = ui.table(
        columns=[
            {"name": "task_title", "label": "Task", "field": "task_title", "sortable": True, "align": "left"},
            {"name": "status", "label": "Status", "field": "status", "sortable": True, "align": "left"},
            {"name": "score", "label": "Auto score", "field": "score", "sortable": True, "align": "left"},
            {"name": "final_score", "label": "Final score", "field": "final_score", "sortable": True, "align": "left"},
            {"name": "submitted_at", "label": "Submitted", "field": "submitted_at", "sortable": True, "align": "left"},
        ],
        rows=[],
        row_key="id",
    ).classes("w-full")

    def refresh_submissions() -> None:
        rows = data.student_list_submissions(account["id"])
        for r in rows:
            r["score"] = "" if r["tests_passed"] is None else f"{r['tests_passed']}/{r['tests_total']}"
        subs_table.rows = rows
        subs_table.update()
        detail_select.options = {r["id"]: f"{r['task_title']} -- {r['status']}" for r in rows}
        detail_select.update()

    ui.button("Refresh", on_click=refresh_submissions).props("outline")

    ui.separator().classes("q-my-md")
    ui.label("Feedback for one submission").classes("text-h6")
    detail_select = ui.select({}, label="Submission").classes("w-96")
    feedback_area = ui.markdown("")

    def show_feedback() -> None:
        if not detail_select.value:
            return
        row = data.student_get_submission(account["id"], detail_select.value)
        if row is None:
            feedback_area.set_content("_Not found._")
            return
        text = f"**{row['task_title']}** -- status: {row['status']}\n\n"
        if row["tests_passed"] is not None:
            text += f"Auto score: {row['tests_passed']} / {row['tests_total']}\n\n"
        if row["feedback"]:
            text += f"**Automated feedback:**\n\n> {row['feedback']}\n\n"
        if row["human_feedback"]:
            text += f"**Teacher feedback:**\n\n> {row['human_feedback']}\n\n"
        if row["final_score"] is not None:
            text += f"**Final score:** {row['final_score']}\n"
        feedback_area.set_content(text)

    ui.button("Show", on_click=show_feedback).props("outline")

    refresh_submissions()
