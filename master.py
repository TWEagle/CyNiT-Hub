from __future__ import annotations

import json
import logging
import importlib
from pathlib import Path

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
IMAGES_DIR = BASE_DIR / "images"


def load_tools_config() -> list[dict]:
    if not TOOLS_JSON.exists():
        return []
    data = json.loads(TOOLS_JSON.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "tools" in data:
        data = data["tools"]
    if not isinstance(data, list):
        return []
    return data


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="/static")

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
        from beheer.main_layout import render_page, load_tools

        tools = []
        for t in load_tools():
            if not t.get("enabled", True):
                continue

            web_path = (t.get("web_path") or "").strip()
            if web_path and not web_path.startswith("/"):
                web_path = "/" + web_path

            tools.append(
                f"""
                <a class="toolcard" href="{web_path}" style="--accent:{t.get('accent', '#35e6df')};">
                  <div class="toolcard-head">
                    <div class="toolcard-icon">{t.get("icon","🧩")}</div>
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

          <div class="cards">
            {''.join(tools) if tools else '<div class="panel">Geen tools geactiveerd.</div>'}
          </div>
        """

        # ✅ title = pagina-naam (layout bouwt "CyNiT Tools | Home")
        return render_page(title="Home", content_html=content)

    return app


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

        # "voica1.py" -> "tools.voica1"
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


def main() -> None:
    app = create_app()
    register_beheer(app)
    register_tools(app)
    app.run(debug=True)


if __name__ == "__main__":
    main()
