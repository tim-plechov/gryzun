from nicegui import ui

from webapp.pages.common import current_account
from webapp.pages.login import ROLE_HOME


@ui.page("/")
def index() -> None:
    account = current_account()
    ui.navigate.to(ROLE_HOME.get(account.get("role"), "/login"))
