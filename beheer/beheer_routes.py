from __future__ import annotations

from flask import Flask, redirect, request

from beheer.main_layout import load_theme_config
from beheer.editors.tools_editor import handle_tools_editor
from beheer.editors.hub_editor import handle_hub_editor
from beheer.editors.theme_editor import handle_theme_editor

from beheer.system_actions import clear_cache, request_restart, watchdog_status


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
    # System / Maintenance
    # =========================
    @app.get("/beheer/system")
    def beheer_system():
        from beheer.main_layout import render_page

        wd_ok, wd_msg = watchdog_status(max_age_seconds=15)

        badge = (
            f"<span class='pill' style='border-color:rgba(0,255,0,.35);background:rgba(0,255,0,.08)'>🟢 Watchdog: {wd_msg}</span>"
            if wd_ok
            else f"<span class='pill' style='border-color:rgba(255,80,80,.45);background:rgba(255,80,80,.10)'>🔴 Watchdog: {wd_msg}</span>"
        )

        restart_disabled = "" if wd_ok else "disabled"
        restart_hint = (
            "Tray runner watchdog is actief → restart werkt (master stopt en tray start opnieuw)."
            if wd_ok
            else "Watchdog niet actief → restart knop is disabled (start hub via tray_runner.py)."
        )

        content = f"""
        <style>
          .btn.danger {{
            border-color: rgba(255,80,80,.35) !important;
          }}
          .btn.danger:disabled {{
            opacity: .45;
            cursor: not-allowed;
          }}
        </style>

        <div class="panel">
          <h2 style="margin:0 0 8px 0;">System / Maintenance</h2>
          <div class="hint">Geavanceerde acties – gebruik met zorg.</div>

          <div style="margin-top:12px; display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
            {badge}
          </div>

          <div style="margin-top:16px; display:grid; gap:14px;">
            <form method="post" action="/beheer/system/clear-cache">
              <button class="btn" type="submit">🧹 Clear cache</button>
              <div class="hint" style="margin-top:6px;">Verwijdert tmp/static cache + __pycache__/*.pyc.</div>
            </form>

            <form method="post" action="/beheer/system/restart" onsubmit="return confirm('CyNiT-Hub herstarten?\\n\\n(master stopt, tray watchdog start opnieuw)');">
              <button class="btn danger" type="submit" {restart_disabled}>🔄 Restart CyNiT-Hub</button>
              <div class="hint" style="margin-top:6px;">{restart_hint}</div>
            </form>
          </div>
        </div>
        """

        return render_page(title="System", content_html=content)

    @app.post("/beheer/system/clear-cache")
    def beheer_clear_cache():
        clear_cache()
        return redirect(request.referrer or "/beheer/system")

    @app.post("/beheer/system/restart")
    def beheer_restart():
        wd_ok, _ = watchdog_status(max_age_seconds=15)
        if not wd_ok:
            # Als watchdog niet draait, herstarten is zinloos: je zou jezelf “dood” maken.
            return "Watchdog not active - restart blocked", 409

        request_restart()
        return "Restarting...", 200

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
