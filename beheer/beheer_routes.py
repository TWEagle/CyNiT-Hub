from __future__ import annotations

from flask import Flask
from beheer.main_layout import render_page

from beheer.editors.tools_editor import handle_tools_editor
from beheer.editors.hub_editor import handle_hub_editor


def register_beheer_routes(app: Flask) -> None:
    @app.route("/beheer/tools", methods=["GET", "POST"])
    def beheer_tools():
        return handle_tools_editor()

    @app.get("/beheer/config")
    def beheer_config():
        return render_page(
            title="Config",
            content_html="<div class='panel'><h2>Config</h2><p>TODO</p></div>",
        )

    @app.get("/beheer/theme")
    def beheer_theme():
        return render_page(
            title="Theme",
            content_html="<div class='panel'><h2>Theme</h2><p>TODO</p></div>",
        )

    @app.get("/beheer/logs")
    def beheer_logs():
        return render_page(
            title="Logs",
            content_html="<div class='panel'><h2>Logs</h2><p>TODO</p></div>",
        )

    @app.route("/beheer/hub", methods=["GET", "POST"])
    def beheer_hub():
        return handle_hub_editor()


