from __future__ import annotations

import json
import logging
import importlib
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, send_from_directory

log = logging.getLogger("ctools")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s"
)

# =========================
# Paths
# =========================
BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
TOOLS_JSON = CONFIG_DIR / "tools.json"
HUB_SETTINGS_JSON = CONFIG_DIR / "hub_settings.json"
IMAGES_DIR = BASE_DIR / "images"


# =========================
# Config loaders
# =========================
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

    # allow {"tools":[...]}
    if isinstance(data, dict) and "tools" in data:
        data = data["tools"]

    if not isinstance(data, list):
        return []

    return [t for t in data if isinstance(t, dict)]


def load_hub_settings() -> Dict[str, Any]:
    """
    Supports:
      - dict (preferred)
      - legacy: [ { ... } ]
    """
    defaults: Dict[str, Any] = {
        "flask_app_name": "CyNiT-Hub",
        "brand_tools": "CyNiT Tools",
        "brand_beheer": "CyNiT Beheer",
        "logo_src": "/images/logo.png?v=1",
        "favicon_ico": "/images/logo.ico",
        "home_columns": 2,
        "card_bg": True,
        "card_round": True,
        "button_bg": True,
        "button_rounded": True,

        # optional: section ordering (from hub_editor)
        "show_section_order": False,
        "sections_order": ["app", "branding", "layout"],
    }

    if not HUB_SETTINGS_JSON.exists():
        return dict(defaults)

    raw = HUB_SETTINGS_JSON.read_text(encoding="utf-8").strip()
    if not raw:
        return dict(defaults)

    try:
        data = json.loads(raw)

        # legacy: [ { ... } ]
        if isinstance(data, list):
            if data and isinstance(data[0], dict):
                defaults.update(data[0])

        # dict: { ... }
        elif isinstance(data, dict):
            defaults.update(data)

    except Exception:
        pass

    # normalize a bit
    try:
        defaults["home_columns"] = int(defaults.get("home_columns", 2) or 2)
    except Exception:
        defaults["home_columns"] = 2

    for k in ("card_bg", "card_round", "button_bg", "button_rounded", "show_section_order"):
        defaults[k] = bool(defaults.get(k, True if k != "show_section_order" else False))

    # normalize order
    order = defaults.get("sections_order")
    if not isinstance(order, list):
        order = ["app", "branding", "layout"]
    order = [x for x in order if x in ("app", "branding", "layout")]
    for x in ("app", "branding", "layout"):
        if x not in order:
            order.append(x)
    defaults["sections_order"] = order[:3]

    return dict(defaults)


def _hex_to_rgb(accent: str) -> str:
    s = (accent or "").strip().lstrip("#")
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


# =========================
# Flask app factory
# =========================
def create_app() -> Flask:
    hub = load_hub_settings()

    # This affects: "Serving Flask app '...'"
    app_name = str(hub.get("flask_app_name") or "CyNiT-Hub").strip() or "CyNiT-Hub"
    app = Flask(app_name, static_folder="static", static_url_path="/static")

    # forced config (optional use in layout)
    app.config["FLASK_APP_NAME"] = app_name

    # ===== Images =====
    @app.get("/images/<path:filename>")
    def images(filename: str):
        return send_from_directory(IMAGES_DIR, filename)

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(IMAGES_DIR, "logo.ico")

    @app.get("/logo.png")
    def logo_png():
        return send_from_directory(IMAGES_DIR, "logo.png")

    # ===== Home =====
    @app.get("/")
    def home():
        # IMPORTANT: jouw main_layout.py moet load_tools() hebben
        from beheer.main_layout import render_page, load_tools

        hub2 = load_hub_settings()
        cols = int(hub2.get("home_columns", 2) or 2)
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

            tools_cards.append(
                f"""
                <a class="toolcard {mode_class}" href="{web_path}"
                   style="--accent:{accent}; --accent-rgb:{accent_rgb};
                          --accent-width:{accent_width}px; --ring-width:{ring_width}px; --ring-glow:{ring_glow}px;">
                  <div class="toolcard-head">
                    <div class="toolcard-icon">{icon}</div>
                    <div>{t.get("name","Tool")}</div>
                  </div>
                  <div class="toolcard-desc">{t.get("description","")}</div>
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

    return app


# =========================
# Registrations
# =========================
def register_beheer(app: Flask) -> None:
    try:
        from beheer import beheer_routes
        beheer_routes.register_beheer_routes(app)
        log.info("Beheer routes registered")
    except Exception as exc:
        log.exception("FAILED registering beheer routes: %s", exc)


def register_tools(app: Flask) -> None:
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
                mod.register_web_routes(app)
                log.info("Tool loaded: %s (register_web_routes)", module_name)
            else:
                log.warning("Tool module %s has no register_web_routes()", module_name)
        except Exception as exc:
            log.exception("FAILED loading tool %s: %s", module_name, exc)


# =========================
# Main
# =========================
def main() -> None:
    # --- TLS bootstrap (self-signed localhost) ---
    tls_log = BASE_DIR / "logs" / "tls.log"
    ssl_ctx = None

    try:
        from runtime.tls_cert import ensure_localhost_cert, trust_cert_current_user_windows
        crt, key = ensure_localhost_cert(BASE_DIR, log_file=tls_log)
        trust_cert_current_user_windows(BASE_DIR, log_file=tls_log)
        ssl_ctx = (str(crt), str(key))
    except Exception as exc:
        log.exception("TLS bootstrap failed (falling back to HTTP): %s", exc)

    # --- Create app + register routes ---
    app = create_app()
    register_beheer(app)
    register_tools(app)

    log.info("FLASK_APP_NAME forced: %s", app.config.get("FLASK_APP_NAME"))

    # --- Run (exactly once) ---
    # debug=False zodat Flask reloader geen dubbel proces maakt in tray-mode
    if ssl_ctx:
        app.run(host="localhost", port=5000, debug=False, ssl_context=ssl_ctx)
    else:
        app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
