from __future__ import annotations

from flask import Flask, redirect, request

from beheer.main_layout import load_theme_config
from beheer.editors.tools_editor import handle_tools_editor
from beheer.editors.hub_editor import handle_hub_editor
from beheer.editors.theme_editor import handle_theme_editor


def register_beheer_routes(app: Flask) -> None:
    @app.route("/beheer/tools", methods=["GET", "POST"])
    def beheer_tools():
        return handle_tools_editor()

    @app.route("/beheer/hub", methods=["GET", "POST"])
    def beheer_hub():
        return handle_hub_editor()

    @app.route("/beheer/theme", methods=["GET", "POST"])
    def beheer_theme():
        return handle_theme_editor()

    # (placeholder) later
    @app.get("/beheer/config")
    def beheer_config():
        from beheer.main_layout import render_page
        return render_page(
            title="Config",
            content_html="<div class='panel'><h2>Config</h2><p>TODO</p></div>",
        )

    @app.get("/beheer/logs")
    def beheer_logs():
        from beheer.main_layout import render_page
        return render_page(
            title="Logs",
            content_html="<div class='panel'><h2>Logs</h2><p>TODO</p></div>",
        )

    # =========================
    # Theme endpoints
    # =========================
    @app.get("/theme/toggle")
    def theme_toggle():
        cfg = load_theme_config()
        themes = cfg.get("themes", {})
        if not isinstance(themes, dict) or not themes:
            return redirect(request.args.get("back") or "/")

        keys = [k for k in themes.keys()]
        if not keys:
            return redirect(request.args.get("back") or "/")

        active = str(cfg.get("active") or keys[0])
        if active not in keys:
            active = keys[0]

        # toggle: if only 2, flip; else go next
        if len(keys) == 2:
            nxt = keys[1] if active == keys[0] else keys[0]
        else:
            idx = keys.index(active)
            nxt = keys[(idx + 1) % len(keys)]

        cfg["active"] = nxt

        # save
        from beheer.main_layout import _save_theme_config  # type: ignore
        _save_theme_config(cfg)

        return redirect(request.args.get("back") or "/")

    @app.get("/theme/set")
    def theme_set():
        cfg = load_theme_config()
        themes = cfg.get("themes", {})
        name = (request.args.get("name") or "").strip()
        if isinstance(themes, dict) and name in themes:
            cfg["active"] = name
            from beheer.main_layout import _save_theme_config  # type: ignore
            _save_theme_config(cfg)
        return redirect(request.args.get("back") or "/")
