from nicegui import events, ui

from webapp import data
from webapp.pages.common import require_role, top_nav

STATUS_OPTIONS = ["draft", "published", "archived"]
SUBMISSION_STATUS_OPTIONS = ["All", "submitted", "checking", "checked", "needs_review", "rejected"]


@ui.page("/teacher")
def teacher_page() -> None:
    account = require_role("teacher", "admin")
    if account is None:
        return
    top_nav()

    with ui.tabs().classes("w-full") as tabs:
        add_tab = ui.tab("Add task")
        manage_tab = ui.tab("Tasks & assignments")
        submissions_tab = ui.tab("Submissions & review")

    with ui.tab_panels(tabs, value=add_tab).classes("w-full"):
        with ui.tab_panel(add_tab):
            _add_task_panel(account)
        with ui.tab_panel(manage_tab):
            _manage_tasks_panel(account)
        with ui.tab_panel(submissions_tab):
            _submissions_panel()


# --------------------------------------------------------------- Add task --

def _add_task_panel(account: dict) -> None:
    topics = data.list_topics()
    levels = data.list_levels()

    topic_select = ui.select({str(t["id"]): t["name"] for t in topics}, label="Topic").classes("w-96")
    with ui.row():
        new_topic_input = ui.input("New topic name").classes("w-72")

        def add_topic() -> None:
            name = (new_topic_input.value or "").strip()
            if not name:
                ui.notify("Topic name is required.", color="negative")
                return
            topic_id = data.create_topic(name)
            topics.append({"id": topic_id, "name": name})
            topic_select.options = {str(t["id"]): t["name"] for t in topics}
            topic_select.value = str(topic_id)
            topic_select.update()
            new_topic_input.value = ""
            ui.notify(f"Added topic {name}.")

        ui.button("+ Add topic", on_click=add_topic)

    level_select = ui.select({str(lv["id"]): lv["name"] for lv in levels}, label="Level").classes("w-72")
    title_input = ui.input("Title").classes("w-full")
    description_input = ui.textarea("Description (markdown supported)").classes("w-full").props("rows=6")
    status_select = ui.select(STATUS_OPTIONS, value="draft", label="Status").classes("w-48")

    ui.label(
        "Each test case needs a matching input file and expected-output file. Upload the input files and "
        "the output files for a type together -- they're paired up in filename order. Sample cases are shown "
        "to students; test cases are hidden and used for auto-grading."
    ).classes("text-caption q-mt-md")

    uploads: dict[str, list[tuple[str, bytes]]] = {"sample_in": [], "sample_out": [], "test_in": [], "test_out": []}
    upload_labels: dict[str, ui.label] = {}

    def make_upload_handler(key: str):
        def handler(e: events.UploadEventArguments) -> None:
            uploads[key].append((e.name, e.content.read()))
            upload_labels[key].set_text(f"{len(uploads[key])} file(s) loaded.")
        return handler

    for key, title in (
        ("sample_in", "Sample input(s)"),
        ("sample_out", "Sample output(s)"),
        ("test_in", "Test input(s)"),
        ("test_out", "Test output(s)"),
    ):
        with ui.row().classes("items-center"):
            ui.label(title).classes("w-40")
            ui.upload(on_upload=make_upload_handler(key), multiple=True, auto_upload=True).classes("w-72")
            upload_labels[key] = ui.label("0 file(s) loaded.").classes("text-caption")

    create_out = ui.column().classes("q-mt-md")

    def create() -> None:
        create_out.clear()
        title = (title_input.value or "").strip()
        description = (description_input.value or "").strip()
        if not title or not description:
            ui.notify("Title and description are required.", color="negative")
            return
        if not topic_select.value or not level_select.value:
            ui.notify("Pick a topic and a level.", color="negative")
            return

        cases = {}
        for dataset_type, in_key, out_key in (("sample", "sample_in", "sample_out"), ("test", "test_in", "test_out")):
            inputs = sorted(uploads[in_key], key=lambda pair: pair[0])
            outputs = sorted(uploads[out_key], key=lambda pair: pair[0])
            if len(inputs) != len(outputs):
                ui.notify(f"{dataset_type}: {len(inputs)} input file(s) but {len(outputs)} output file(s) -- counts must match.", color="negative")
                return
            cases[dataset_type] = list(zip(inputs, outputs))

        task_id = data.create_task(title, description, topic_select.value, level_select.value, account["id"], status_select.value)

        with create_out:
            ui.label(f"Created task {task_id} ({title!r}, status={status_select.value}).").classes("text-positive")
            for dataset_type, pairs in cases.items():
                for order_index, ((in_name, in_content), (out_name, out_content)) in enumerate(pairs):
                    in_meta = data.upload_file(in_content, in_name, task_id)
                    input_file_id = data.register_file(in_meta, uploaded_by=account["id"])
                    out_meta = data.upload_file(out_content, out_name, task_id)
                    output_file_id = data.register_file(out_meta, uploaded_by=account["id"])
                    data.attach_dataset(task_id, input_file_id, output_file_id, dataset_type, order_index)
                    ui.label(f"Attached {dataset_type} case {order_index}: {in_name} -> {out_name}")

        for key in uploads:
            uploads[key] = []
            upload_labels[key].set_text("0 file(s) loaded.")
        title_input.value = ""
        description_input.value = ""

    ui.button("Create task", on_click=create).props("color=primary").classes("q-mt-md")


# ------------------------------------------------------- Tasks & assignments --

def _manage_tasks_panel(account: dict) -> None:
    topics = data.list_topics()
    levels = data.list_levels()
    topic_filter = ui.select({None: "All topics", **{str(t["id"]): t["name"] for t in topics}}, value=None, label="Topic").classes("w-64")
    level_filter = ui.select({None: "All levels", **{str(lv["id"]): lv["name"] for lv in levels}}, value=None, label="Level").classes("w-64")
    status_filter = ui.select({None: "All", **{s: s for s in STATUS_OPTIONS}}, value=None, label="Status").classes("w-48")

    tasks_table = ui.table(
        columns=[
            {"name": "title", "label": "Title", "field": "title", "sortable": True, "align": "left"},
            {"name": "topic", "label": "Topic", "field": "topic", "sortable": True, "align": "left"},
            {"name": "level", "label": "Level", "field": "level", "sortable": True, "align": "left"},
            {"name": "status", "label": "Status", "field": "status", "sortable": True, "align": "left"},
            {"name": "created_at", "label": "Created", "field": "created_at", "sortable": True, "align": "left"},
        ],
        rows=[],
        row_key="id",
    ).classes("w-full")

    task_picker = ui.select({}, label="Manage this task").classes("w-full q-mt-md")

    def refresh_tasks() -> None:
        rows = data.list_tasks(topic_id=topic_filter.value, level_id=level_filter.value, status=status_filter.value)
        tasks_table.rows = rows
        tasks_table.update()
        task_picker.options = {r["id"]: f"{r['title']} ({r['status']})" for r in rows}
        task_picker.update()

    ui.button("Refresh", on_click=refresh_tasks).props("outline")
    refresh_tasks()

    ui.separator().classes("q-my-md")
    assignment_area = ui.column().classes("w-full")

    def render_assignment_area() -> None:
        assignment_area.clear()
        task_id = task_picker.value
        if not task_id:
            return
        students = data.list_students_full()
        groups = data.list_groups()
        with assignment_area:
            with ui.row():
                def download() -> None:
                    zip_path = data.build_task_package(task_id)
                    ui.download(zip_path.read_bytes(), zip_path.name)

                ui.button("Download sample package (.zip)", on_click=download).props("outline")

            ui.label("Assign this task to students").classes("text-subtitle1 q-mt-sm")
            student_select = ui.select(
                {s["id"]: f"{s['full_name']} <{s['email']}>" + (f" [{s['group_name']}]" if s["group_name"] else "") for s in students},
                multiple=True,
                label="Students",
            ).classes("w-full").props("use-chips")

            def notify_assignment_results(results: list[dict]) -> None:
                failed = [r for r in results if r["jupyter_error"]]
                if not failed:
                    ui.notify(f"Assigned {len(results)} student(s); task files copied to their Jupyter folders.", color="positive")
                    return
                detail = "; ".join(f"{r['full_name']}: {r['jupyter_error']}" for r in failed)
                ui.notify(
                    f"Assigned {len(results)} student(s), but Jupyter copy failed for {len(failed)}: {detail}",
                    color="warning", multi_line=True, close_button=True,
                )

            def assign_selected() -> None:
                if not student_select.value:
                    ui.notify("Pick at least one student.", color="negative")
                    return
                results = data.assign_task(task_id, student_select.value, account["id"])
                notify_assignment_results(results)
                render_assignment_area()

            ui.button("Assign selected students", on_click=assign_selected)

            with ui.row().classes("items-center"):
                group_select = ui.select({g: g for g in groups}, label="...or assign a whole group").classes("w-64")

                def assign_group() -> None:
                    if not group_select.value:
                        ui.notify("Pick a group.", color="negative")
                        return
                    results = data.assign_task_to_group(task_id, group_select.value, account["id"])
                    notify_assignment_results(results)
                    render_assignment_area()

                ui.button("Assign group", on_click=assign_group)

            ui.label("Currently assigned").classes("text-subtitle1 q-mt-sm")
            assignees = data.list_assignees(task_id)
            if not assignees:
                ui.label("No one yet.").classes("text-caption")
            else:
                ui.table(
                    columns=[
                        {"name": "full_name", "label": "Name", "field": "full_name", "align": "left"},
                        {"name": "email", "label": "Email", "field": "email", "align": "left"},
                        {"name": "group_name", "label": "Group", "field": "group_name", "align": "left"},
                        {"name": "assigned_at", "label": "Assigned", "field": "assigned_at", "align": "left"},
                    ],
                    rows=assignees,
                    row_key="id",
                ).classes("w-full")

                unassign_select = ui.select(
                    {a["id"]: a["full_name"] for a in assignees}, label="Manage an assignee"
                ).classes("w-72")

                def unassign() -> None:
                    if not unassign_select.value:
                        return
                    data.unassign_task(task_id, unassign_select.value)
                    ui.notify("Unassigned.")
                    render_assignment_area()

                def recopy() -> None:
                    if not unassign_select.value:
                        return
                    student = data.get_student_full(unassign_select.value)
                    error = data.copy_task_to_jupyter(task_id, student) if student else "student not found"
                    if error:
                        ui.notify(f"Jupyter copy failed: {error}", color="negative")
                    else:
                        ui.notify("Copied to their Jupyter folder.", color="positive")

                ui.button("Unassign", on_click=unassign).props("outline color=negative")
                ui.button("Re-copy files to Jupyter", on_click=recopy).props("outline")

    task_picker.on_value_change(render_assignment_area)


# ------------------------------------------------------------ Submissions --

def _submissions_panel() -> None:
    tasks = data.list_tasks()
    students = data.list_students_full()
    task_filter = ui.select({None: "All tasks", **{t["id"]: t["title"] for t in tasks}}, value=None, label="Task").classes("w-72")
    student_filter = ui.select({None: "All students", **{s["id"]: s["full_name"] for s in students}}, value=None, label="Student").classes("w-72")
    status_filter = ui.select(SUBMISSION_STATUS_OPTIONS, value="All", label="Status").classes("w-48")

    subs_table = ui.table(
        columns=[
            {"name": "submitted_at", "label": "Submitted", "field": "submitted_at", "sortable": True, "align": "left"},
            {"name": "student_name", "label": "Student", "field": "student_name", "sortable": True, "align": "left"},
            {"name": "task_title", "label": "Task", "field": "task_title", "sortable": True, "align": "left"},
            {"name": "status", "label": "Status", "field": "status", "sortable": True, "align": "left"},
            {"name": "score", "label": "Score", "field": "score", "sortable": True, "align": "left"},
            {"name": "id", "label": "Submission id", "field": "id", "align": "left"},
        ],
        rows=[],
        row_key="id",
    ).classes("w-full")

    def refresh() -> None:
        status = None if status_filter.value == "All" else status_filter.value
        rows = data.teacher_list_submissions(task_id=task_filter.value, student_id=student_filter.value, status=status)
        for r in rows:
            r["score"] = "" if r["auto_score"] is None else f"{r['auto_score']}/{r['auto_max_score']}"
        subs_table.rows = rows
        subs_table.update()

    ui.button("Refresh", on_click=refresh).props("outline")
    refresh()

    ui.separator().classes("q-my-md")
    ui.label("Inspect a submission").classes("text-h6")
    ui.label("Copy a submission id from the table above.").classes("text-caption")
    sub_id_input = ui.input("Submission id").classes("w-96")
    detail_area = ui.column().classes("w-full q-mt-sm")

    def inspect() -> None:
        detail_area.clear()
        sub_id = (sub_id_input.value or "").strip()
        if not sub_id:
            ui.notify("Enter a submission id.", color="negative")
            return
        detail = data.teacher_get_submission_detail(sub_id)
        if detail is None:
            with detail_area:
                ui.label("No submission with that id.").classes("text-negative")
            return
        s, task, student, code, results = detail["submission"], detail["task"], detail["student"], detail["code"], detail["test_results"]

        with detail_area:
            ui.markdown(
                f"### Submission `{s['id']}`\n"
                f"- **Status:** {s['status']}\n"
                f"- **Student:** {student['full_name']} <{student['email']}>\n"
                f"- **Task:** {task['title']} (`{task['id']}`)\n"
                f"- **Submitted:** {s['submitted_at']}\n"
                f"- **Auto score:** {s['auto_score']} / {s['auto_max_score']} (model: {s['auto_feedback_model'] or '-'})\n"
            )
            ui.markdown("**Automated feedback:**\n\n> " + (s["auto_feedback"] or "_none yet_").replace("\n", "\n> "))
            with ui.expansion("Task description"):
                ui.markdown(task["description"])
            with ui.expansion("Student code", value=True):
                ui.code(code or "(no code file)", language="python").classes("w-full")
            ui.label("Test results (including hidden test cases):").classes("text-subtitle1 q-mt-sm")
            ui.table(
                columns=[
                    {"name": "dataset_type", "label": "Type", "field": "dataset_type", "align": "left"},
                    {"name": "passed", "label": "Passed", "field": "passed", "align": "left"},
                    {"name": "exit_code", "label": "Exit code", "field": "exit_code", "align": "left"},
                    {"name": "execution_time_ms", "label": "Time (ms)", "field": "execution_time_ms", "align": "left"},
                    {"name": "stdout", "label": "stdout", "field": "stdout", "align": "left"},
                    {"name": "stderr", "label": "stderr", "field": "stderr", "align": "left"},
                ],
                rows=[{**r, "stdout": (r["stdout"] or "")[:1000], "stderr": (r["stderr"] or "")[:1000]} for r in results],
                row_key="id",
            ).classes("w-full")

            ui.label("Review").classes("text-h6 q-mt-md")
            with ui.row():
                human_score = ui.number("Human score", value=s["human_score"]).classes("w-40")
                final_score = ui.number("Final score (defaults to human score)", value=s["final_score"]).classes("w-64")
            human_feedback = ui.textarea("Feedback to student", value=s["human_feedback"] or "").classes("w-full").props("rows=4")

            def save_review() -> None:
                from webapp.pages.common import current_account

                reviewer = current_account()
                data.review_submission(
                    s["id"], reviewer["id"], human_score.value, human_feedback.value,
                    final_score=final_score.value if final_score.value is not None else None,
                )
                ui.notify("Review saved.", color="positive")

            ui.button("Save review", on_click=save_review).props("color=primary")

    ui.button("Inspect", on_click=inspect).props("color=info")
