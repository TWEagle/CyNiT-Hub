from __future__ import annotations

from flask import Flask, redirect, request

from beheer.main_layout import load_theme_config, render_page
from beheer.editors.tools_editor import handle_tools_editor
from beheer.editors.hub_editor import handle_hub_editor
from beheer.editors.theme_editor import handle_theme_editor

from beheer.system_actions import clear_cache, request_restart, watchdog_status


def register_beheer_routes(app: Flask) -> None:
    # -------------------------
    # Editors
    # -------------------------
    @app.route("/beheer/tools", methods=["GET", "POST"])
    def beheer_tools():
        return handle_tools_editor()

    @app.route("/beheer/hub", methods=["GET", "POST"])
    def beheer_hub():
        return handle_hub_editor()

    @app.route("/beheer/theme", methods=["GET", "POST"])
    def beheer_theme():
        return handle_theme_editor()

    # -------------------------
    # Placeholders (als je ze al had)
    # -------------------------
    @app.get("/beheer/config")
    def beheer_config():
        return render_page(
            title="Config",
            content_html="<div class='panel'><h2>Config</h2><div class='hint'>TODO</div></div>",
        )

    @app.get("/beheer/logs")
    def beheer_logs():
        return render_page(
            title="Logs",
            content_html="<div class='panel'><h2>Logs</h2><div class='hint'>TODO</div></div>",
        )

    # -------------------------
    # System / Maintenance
    # -------------------------
    @app.get("/beheer/system")
    def beheer_system():
        wd = watchdog_status(max_age_seconds=15)

        ok = bool(wd.get("ok"))
        emoji = str(wd.get("emoji", "⚫"))
        label = str(wd.get("label", ""))
        detail = str(wd.get("detail", ""))

        # uptime extra (optioneel)
        uptime_txt = ""
        if isinstance(wd.get("uptime_sec"), int) and int(wd["uptime_sec"]) > 0:
            us = int(wd["uptime_sec"])
            h = us // 3600
            m = (us % 3600) // 60
            s = us % 60
            uptime_txt = f" • uptime {h:02d}:{m:02d}:{s:02d}"

        badge_border = "rgba(0,255,0,.35)" if ok else "rgba(255,80,80,.45)"
        badge_bg = "rgba(0,255,0,.08)" if ok else "rgba(255,80,80,.10)"

        badge = f"""
        <span class="pill"
          style="border-color:{badge_border}; background:{badge_bg};">
          {emoji} {label} — {detail}{uptime_txt}
        </span>
        """

        restart_disabled = "" if ok else "disabled"
        restart_hint = (
            "Restart werkt via tray watchdog (master stopt, tray start opnieuw)."
            if ok
            else "Watchdog niet actief → restart is uitgeschakeld (start hub via tray_runner.py)."
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

            <form method="post" action="/beheer/system/restart"
                  onsubmit="return confirm('CyNiT-Hub herstarten?\\n\\n(master stopt, tray watchdog start opnieuw)');">
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
        wd = watchdog_status(max_age_seconds=15)
        if not bool(wd.get("ok")):
            # Zonder watchdog zou je master killen zonder herstart -> block
            return "Watchdog not active - restart blocked", 409

        request_restart()
        return "Restarting...", 200

    # -------------------------
    # Theme quick endpoints
    # -------------------------
    @app.get("/theme/toggle")
    def theme_toggle():
        cfg = load_theme_config()
        themes = cfg.get("themes", {})
        if not isinstance(themes, dict) or not themes:
            return redirect(request.args.get("back") or "/")

        keys = list(themes.keys())
        active = str(cfg.get("active") or keys[0])
        if active not in keys:
            active = keys[0]

        if len(keys) == 2:
            nxt = keys[1] if active == keys[0] else keys[0]
        else:
            nxt = keys[(keys.index(active) + 1) % len(keys)]

        cfg["active"] = nxt

        # save (internal helper)
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
