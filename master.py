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


# =========================
# Config loaders
# =========================
def load_tools_config() -> list[dict]:
    """
    Supports:
      - tools.json as LIST
      - tools.json as DICT: {"tools":[...], "ui":{...}}
    """
    if not TOOLS_JSON.exists():
        return []
    raw = TOOLS_JSON.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []

    if isinstance(data, list):
        return [t for t in data if isinstance(t, dict)]

    if isinstance(data, dict) and isinstance(data.get("tools"), list):
        return [t for t in data["tools"] if isinstance(t, dict)]

    return []


def _hex_to_rgb(accent: str) -> str:
    """
    '#00ff66' -> '0,255,102' (fallback: CyNiT accent)
    """
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


def _clamp_int(val, default: int, lo: int, hi: int) -> int:
    try:
        n = int(val)
    except Exception:
        return default
    return max(lo, min(hi, n))


# =========================
# Flask app factory
# =========================
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
        from beheer.main_layout import render_page, load_tools, load_hub_settings

        hub = load_hub_settings()
        cols = _clamp_int(hub.get("home_columns", 2), default=2, lo=1, hi=6)

        tools_cards = []
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
            if accent_mode not in ("left", "ring", "bg"):
                accent_mode = "left"

            accent_width = _clamp_int(t.get("accent_width", 5), default=5, lo=0, hi=40)
            ring_width = _clamp_int(t.get("ring_width", 1), default=1, lo=0, hi=12)
            ring_glow = _clamp_int(t.get("ring_glow", 18), default=18, lo=0, hi=80)

            classes = ["toolcard"]
            if accent_mode == "ring":
                classes.append("accent-ring")
            elif accent_mode == "bg":
                classes.append("accent-bg")

            tools_cards.append(
                f"""
                <a class="{' '.join(classes)}" href="{web_path}"
                   style="
                     --accent:{accent};
                     --accent-rgb:{accent_rgb};
                     --accent-width:{accent_width}px;
                     --ring-width:{ring_width}px;
                     --ring-glow:{ring_glow}px;
                   ">
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
    app = create_app()
    register_beheer(app)
    register_tools(app)
    app.run(debug=True)


if __name__ == "__main__":
    main()
