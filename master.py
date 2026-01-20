from __future__ import annotations

import importlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, Response, jsonify, request, send_from_directory

from runtime.hub_logging import setup_logging

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
TOOLS_JSON = CONFIG_DIR / "tools.json"
HUB_SETTINGS_JSON = CONFIG_DIR / "hub_settings.json"
IMAGES_DIR = BASE_DIR / "images"


def load_tools_config() -> List[dict]:
    if not TOOLS_JSON.exists():
        return []
    raw = TOOLS_JSON.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if isinstance(data, dict) and "tools" in data:
        data = data["tools"]
    if not isinstance(data, list):
        return []
    return [t for t in data if isinstance(t, dict)]


def load_hub_settings() -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "flask_app_name": "CyNiT-Hub",
        "brand_tools": "CyNiT Tools",
        "brand_beheer": "CyNiT Beheer",
        "logo_src": "/images/logo.png?v=1",
        "favicon_ico": "/images/logo.ico",
        "home_columns": 3,
        "card_bg": True,
        "card_round": True,
        "button_bg": True,
        "button_rounded": True,
    }
    if not HUB_SETTINGS_JSON.exists():
        return dict(defaults)

    raw = HUB_SETTINGS_JSON.read_text(encoding="utf-8").strip()
    if not raw:
        return dict(defaults)

    try:
        data = json.loads(raw)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            defaults.update(data[0])
        elif isinstance(data, dict):
            defaults.update(data)
    except Exception:
        pass

    try:
        defaults["home_columns"] = int(defaults.get("home_columns", 3) or 3)
    except Exception:
        defaults["home_columns"] = 3

    return dict(defaults)


def _hex_to_rgb(hex_color: str) -> str:
    s = (hex_color or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return "53,230,223"
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
        return f"{r},{g},{b}"
    except Exception:
        return "53,230,223"


def _guess_tool_from_path(path: str, tools_cfg: List[dict]) -> str:
    p = (path or "/").strip()
    if not p.startswith("/"):
        p = "/" + p

    best = ""
    best_len = 0
    for t in tools_cfg:
        wp = (t.get("web_path") or "").strip()
        if not wp:
            continue
        if not wp.startswith("/"):
            wp = "/" + wp
        if p == wp or p.startswith(wp.rstrip("/") + "/"):
            if len(wp) > best_len:
                best_len = len(wp)
                best = str(t.get("id") or wp.strip("/"))
    return best or ""


def create_app(hub_log, errors_log, requests_log, clicks_log, tools_cfg: List[dict]) -> Flask:
    hub = load_hub_settings()
    app_name = str(hub.get("flask_app_name") or "CyNiT-Hub").strip() or "CyNiT-Hub"

    app = Flask(app_name, static_folder="static", static_url_path="/static")
    app.config["FLASK_APP_NAME"] = app_name

    # --------- access logging ----------
    @app.before_request
    def _before():
        request._cynit_t0 = time.perf_counter()  # type: ignore[attr-defined]

    @app.after_request
    def _after(resp: Response):
        try:
            t0 = getattr(request, "_cynit_t0", None)
            ms = int((time.perf_counter() - t0) * 1000) if t0 else -1
            requests_log.info(
                "OK %s %s -> %s (%sms) ip=%s",
                request.method,
                request.path,
                resp.status_code,
                ms,
                request.remote_addr,
            )
        except Exception:
            pass
        return resp

    @app.teardown_request
    def _teardown(exc: Optional[BaseException]):
        if exc is not None:
            errors_log.exception("Unhandled exception on %s %s", request.method, request.path)

    # --------- click logging ----------
    @app.post("/_log/click")
    def log_click():
        data = request.get_json(force=True, silent=True) or {}
        path = str(data.get("path") or "")
        href = str(data.get("href") or "")
        text = str(data.get("text") or "")[:180]
        el_id = str(data.get("id") or "")[:80]
        cls = str(data.get("cls") or "")[:180]
        tag = str(data.get("tag") or "")[:40]

        tool_id = _guess_tool_from_path(path or request.path, tools_cfg)

        clicks_log.info(
            'OK click tool=%s path="%s" href="%s" tag=%s id="%s" class="%s" text="%s" ip=%s',
            tool_id,
            path,
            href,
            tag,
            el_id,
            cls,
            text,
            request.remote_addr,
        )
        return ("", 204)

    # --------- images ----------
    @app.get("/images/<path:filename>")
    def images(filename: str):
        return send_from_directory(IMAGES_DIR, filename)

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(IMAGES_DIR, "logo.ico")

    # --------- HOME (toolcards terug!) ----------
    @app.get("/")
    def home():
        from beheer.main_layout import render_page, load_tools

        hub2 = load_hub_settings()
        cols = int(hub2.get("home_columns", 3) or 3)
        cols = max(1, min(12, cols))

        tools_cards: List[str] = []
        for t in load_tools():
            if not t.get("enabled", True):
                continue
            if t.get("hidden", False):
                continue

            web_path = (t.get("web_path") or "").strip()
            if web_path and not web_path.startswith("/"):
                web_path = "/" + web_path

            icon = t.get("icon_web") or t.get("icon") or "🧩"
            accent = t.get("accent", "#35e6df")
            accent_rgb = _hex_to_rgb(accent)

            accent_mode = (t.get("accent_mode") or "left").strip().lower()
            mode_class = ""
            if accent_mode == "ring":
                mode_class = "accent-ring"
            elif accent_mode == "bg":
                mode_class = "accent-bg"

            accent_width = int(t.get("accent_width") or 5)
            ring_width = int(t.get("ring_width") or 1)
            ring_glow = int(t.get("ring_glow") or 18)

            desc = (t.get("description") or "").strip()

            tools_cards.append(
                f"""
                <a class="toolcard {mode_class}" href="{web_path}"
                   data-log="toolcard:{t.get('id','tool')}"
                   style="--accent:{accent}; --accent-rgb:{accent_rgb};
                          --accent-width:{accent_width}px; --ring-width:{ring_width}px; --ring-glow:{ring_glow}px;">
                  <div class="toolcard-head">
                    <div class="toolcard-icon">{icon}</div>
                    <div>{t.get("name","Tool")}</div>
                  </div>
                  <div class="toolcard-desc">{desc}</div>
                </a>
                """
            )

        content = f"""
          <div class="panel">
            <h2 style="margin:0 0 6px 0;">Home</h2>
            <div class="hint">Tools/cards komen uit <code>config/tools.json</code>.</div>
          </div>

          <div class="cards grid" style="--cols:{cols};">
            {''.join(tools_cards) if tools_cards else '<div class="panel">Geen tools geactiveerd.</div>'}
          </div>
        """
        return render_page(title="Home", content_html=content)

    @app.get("/_health")
    def health():
        return jsonify({"status": "ok"})

    return app


def register_beheer(app: Flask, hub_log) -> None:
    try:
        from beheer import beheer_routes
        beheer_routes.register_beheer_routes(app)
        hub_log.info("Beheer routes registered OK")
    except Exception:
        hub_log.exception("FAILED registering beheer routes")


def register_tools(app: Flask, hub_log) -> None:
    tools = load_tools_config()
    for t in tools:
        if not t.get("enabled", True):
            continue

        script = (t.get("script") or "").strip()
        if not script:
            continue

        module_name = script.replace(".py", "").replace("/", ".").replace("\\", ".")
        if not module_name.startswith("tools."):
            module_name = f"tools.{module_name}"

        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "register_web_routes"):
                hub_log.debug("Registering tool routes: %s", module_name)
                mod.register_web_routes(app)
                hub_log.info("Tool loaded: %s (register_web_routes) OK", module_name)
            else:
                hub_log.warning("Tool module %s has no register_web_routes() OK", module_name)
        except Exception:
            hub_log.exception("FAILED loading tool %s", module_name)


def main() -> None:
    tools_cfg = load_tools_config()
    tool_ids = [str(t.get("id") or "") for t in tools_cfg if isinstance(t, dict) and t.get("id")]

    logs = setup_logging(BASE_DIR, tool_ids)
    hub_log = logs.hub
    errors_log = logs.errors
    requests_log = logs.requests
    clicks_log = logs.clicks

    ssl_ctx = None
    tls_log = BASE_DIR / "logs" / "tls.log"

    try:
        from runtime.tls_cert import ensure_localhost_cert, trust_cert_current_user_windows
        crt, key = ensure_localhost_cert(BASE_DIR, log_file=tls_log)
        trust_cert_current_user_windows(BASE_DIR, log_file=tls_log)
        ssl_ctx = (str(crt), str(key))
        hub_log.info("TLS bootstrap OK")
    except Exception:
        hub_log.exception("TLS bootstrap failed (falling back to HTTP)")

    app = create_app(hub_log, errors_log, requests_log, clicks_log, tools_cfg)
    register_beheer(app, hub_log)
    register_tools(app, hub_log)

    hub_log.info("FLASK_APP_NAME forced: %s OK", app.config.get("FLASK_APP_NAME"))

    if ssl_ctx:
        app.run(host="localhost", port=5000, debug=False, ssl_context=ssl_ctx)
    else:
        app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
