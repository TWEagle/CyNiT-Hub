#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from flask import Flask, Response, redirect, render_template_string, request, send_from_directory, url_for

# =============================================================================
# Paths
# =============================================================================
ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
TOOLS_DIR = ROOT / "tools"
STATIC_DIR = ROOT / "static"
IMAGES_DIR = ROOT / "images"
LOGS_DIR = ROOT / "logs"

SETTINGS_FILE = CONFIG_DIR / "settings.json"
TOOLS_FILE = CONFIG_DIR / "tools.json"

LOGS_DIR.mkdir(exist_ok=True)

# =============================================================================
# Logging
# =============================================================================
LOG_FILE = LOGS_DIR / "app.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("ctools")

# =============================================================================
# Flask
# =============================================================================
app = Flask(__name__, static_folder="static", static_url_path="/static")

# =============================================================================
# Helpers
# =============================================================================
def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Failed reading JSON %s: %s", path, exc)
        return default


def load_settings() -> Dict[str, Any]:
    return _read_json(SETTINGS_FILE, {}) or {}


def load_tools() -> List[Dict[str, Any]]:
    data = _read_json(TOOLS_FILE, [])
    # tools.json mag array zijn of dict met {"tools":[...]}
    if isinstance(data, dict):
        data = data.get("tools", [])
    if not isinstance(data, list):
        return []
    # filter alleen dicts
    return [t for t in data if isinstance(t, dict)]


def is_enabled(tool: Dict[str, Any]) -> bool:
    # support: enabled of hidden (hidden=true -> niet tonen, maar kan nog enabled zijn)
    if tool.get("enabled") is False:
        return False
    return True


def is_visible(tool: Dict[str, Any]) -> bool:
    if tool.get("hidden") is True:
        return False
    return True


def _norm_path(p: str) -> str:
    p = (p or "/").strip()
    if not p.startswith("/"):
        p = "/" + p
    if len(p) > 1 and p.endswith("/"):
        p = p[:-1]
    return p


def _module_from_tool(tool: Dict[str, Any]) -> str:
    """
    tools.json:
      - script: "voica1.py" (in tools/)
    -> module: "tools.voica1"
    """
    script = (tool.get("script") or "").strip()
    module = (tool.get("module") or "").strip()
    if module:
        return module
    if script.endswith(".py"):
        script = script[:-3]
    if not script:
        return ""
    # tools folder package
    return f"tools.{script}"


def _rule_exists(path: str) -> bool:
    path = _norm_path(path)
    for r in app.url_map.iter_rules():
        if r.rule == path:
            return True
    return False


# =============================================================================
# Layout (one base template)
# =============================================================================
BASE_HTML = """
<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>{{ page_title }}</title>
  <link rel="icon" href="{{ url_for('images_file', filename='logo.ico') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='cynit.css') }}">
  <script defer src="{{ url_for('static', filename='cynit.js') }}"></script>
</head>
<body class="cynit-body">

<header class="header">
  <div class="header-left">
    <button class="iconbtn" type="button" id="toolsBtn" title="Tools">🔧</button>

    <a href="/" class="brand" title="Home">
      <img class="brand-logo" src="{{ url_for('images_file', filename='logo.png') }}?v=1" alt="CyNiT">
      <span class="brand-title">{{ header_title }}</span>
    </a>
  </div>

  <div class="header-right">
    <button class="iconbtn" type="button" id="beheerBtn" title="Beheer">⚙️</button>
  </div>
</header>

<!-- Tools dropdown -->
<div class="dropdown" id="toolsMenu" style="display:none">
  <div class="dropdown-title">Tools</div>
  {% for t in tools_menu %}
    <a class="dropdown-item" href="{{ t.web_path }}">
      <span class="dot" style="background: {{ t.accent }}"></span>
      <span class="dropdown-text">{{ t.icon }} {{ t.name }}</span>
    </a>
  {% endfor %}
  {% if not tools_menu %}
    <div class="dropdown-empty">Geen tools zichtbaar</div>
  {% endif %}
</div>

<!-- Beheer dropdown -->
<div class="dropdown" id="beheerMenu" style="display:none">
  <div class="dropdown-title">Beheer</div>
  <a class="dropdown-item" href="/beheer/tools">🧰 Tools editor</a>
  <a class="dropdown-item" href="/beheer/config">📝 Config</a>
  <a class="dropdown-item" href="/beheer/theme">🎨 Theme</a>
  <a class="dropdown-item" href="/beheer/logs">📜 Logs</a>
</div>

<main class="main">
  {{ content|safe }}
</main>

<footer class="footer">
  <div>CyNiT Hub — footer altijd zichtbaar</div>
</footer>

</body>
</html>
"""


def render_page(content_html: str, title: str = "CyNiT Hub") -> str:
    tools = load_tools()
    tools_menu = []
    for t in tools:
        if not is_enabled(t) or not is_visible(t):
            continue
        tools_menu.append({
            "id": t.get("id", ""),
            "name": t.get("name", t.get("id", "tool")),
            "icon": t.get("icon_web", "🧩"),
            "web_path": _norm_path(t.get("web_path", "/")),
            "accent": t.get("accent", "#00ff66"),
        })

    return render_template_string(
        BASE_HTML,
        page_title=title,
        header_title=title,
        content=content_html,
        tools_menu=tools_menu
    )


# =============================================================================
# Static image routes (must remain in /images folder)
# =============================================================================
@app.route("/images/<path:filename>")
def images_file(filename: str):
    return send_from_directory(IMAGES_DIR, filename)

# Compat routes for legacy tools that still request /logo.png or /favicon.ico
@app.route("/logo.png")
def legacy_logo_png():
    return send_from_directory(IMAGES_DIR, "logo.png")

@app.route("/logo.ico")
def legacy_logo_ico():
    return send_from_directory(IMAGES_DIR, "logo.ico")

@app.route("/favicon.ico")
def legacy_favicon():
    return send_from_directory(IMAGES_DIR, "logo.ico")


# =============================================================================
# Tool loader + fallback
# =============================================================================
TOOL_LOAD_ERRORS: Dict[str, str] = {}

def _register_tool_module(module_name: str) -> Tuple[bool, str]:
    """
    Returns: (ok, how_or_error)
    """
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:
        return False, f"import failed: {exc}"

    fn = None
    how = ""
    if hasattr(mod, "register_web_routes"):
        fn = getattr(mod, "register_web_routes")
        how = "register_web_routes"
    elif hasattr(mod, "register_routes"):
        fn = getattr(mod, "register_routes")
        how = "register_routes"

    if not fn:
        return False, "no register_web_routes/register_routes"

    try:
        fn(app)
        return True, how
    except Exception as exc:
        return False, f"{how} failed: {exc}"


def _add_fallback_route(tool: Dict[str, Any], reason: str) -> None:
    tid = str(tool.get("id") or "tool")
    name = str(tool.get("name") or tid)
    web_path = _norm_path(str(tool.get("web_path") or "/"))
    modname = _module_from_tool(tool) or "(unknown)"

    if web_path == "/" or _rule_exists(web_path):
        return

    endpoint = f"fallback_{tid}"

    def _view(reason=reason, name=name, tid=tid, web_path=web_path, modname=modname):
        html = f"""
        <div class="pagewrap">
          <div class="panel">
            <h1>Tool niet beschikbaar</h1>
            <p><b>{name}</b> (<code>{tid}</code>) kon niet geladen worden.</p>

            <div class="kv">
              <div><b>web_path</b></div><div><code>{web_path}</code></div>
              <div><b>module</b></div><div><code>{modname}</code></div>
              <div><b>reden</b></div><div><code>{reason}</code></div>
            </div>

            <h2>Checklist</h2>
            <ul>
              <li>Bestaat <code>tools/{tid}.py</code> (of klopt <code>script</code> in tools.json)?</li>
              <li>Heeft de tool een functie <code>register_web_routes(app)</code>?</li>
              <li>Staat <code>enabled: true</code> in <code>config/tools.json</code>?</li>
            </ul>

            <a class="btn" href="/">↩ Terug naar home</a>
          </div>
        </div>
        """
        return render_page(html, title=name)

    app.add_url_rule(web_path, endpoint, _view, methods=["GET"])


def register_all_tools() -> None:
    tools = load_tools()
    TOOL_LOAD_ERRORS.clear()

    for t in tools:
        if not is_enabled(t):
            continue

        modname = _module_from_tool(t)
        if not modname:
            reason = "geen module/script gevonden (tools.json mist 'script' of 'module')"
            TOOL_LOAD_ERRORS[str(t.get("id") or t.get("name") or "tool")] = reason
            _add_fallback_route(t, reason)
            continue

        ok, how = _register_tool_module(modname)
        if ok:
            log.info("Tool loaded: %s (%s)", modname, how)
        else:
            reason = f"{modname}: {how}"
            TOOL_LOAD_ERRORS[str(t.get("id") or t.get("name") or "tool")] = reason
            log.warning("Tool not loaded: %s (%s)", modname, how)
            _add_fallback_route(t, reason)


# =============================================================================
# Routes
# =============================================================================
@app.route("/")
def home():
    tools = load_tools()
    cards = []
    for t in tools:
        if not is_enabled(t) or not is_visible(t):
            continue
        cards.append({
            "name": t.get("name", t.get("id", "tool")),
            "icon": t.get("icon_web", "🧩"),
            "path": _norm_path(t.get("web_path", "/")),
            "accent": t.get("accent", "#00ff66"),
            "desc": t.get("description", ""),
        })

    if not cards:
        content = """
        <div class="pagewrap">
          <div class="panel">
            <h1>CyNiT Hub</h1>
            <p>Geen tools zichtbaar. Ga naar ⚙️ → Tools editor en zet tools aan.</p>
          </div>
        </div>
        """
        return render_page(content, title="CyNiT Tools")

    card_html = "".join(
        f"""
        <a class="toolcard" href="{c['path']}" style="--accent:{c['accent']}">
          <div class="toolcard-top">
            <div class="toolcard-icon">{c['icon']}</div>
            <div class="toolcard-title">{c['name']}</div>
          </div>
          <div class="toolcard-desc">{c['desc']}</div>
        </a>
        """
        for c in cards
    )

    content = f"""
    <div class="pagewrap">
      <h1>CyNiT Tools</h1>
      <div class="grid">
        {card_html}
      </div>
    </div>
    """
    return render_page(content, title="CyNiT Tools")


# =============================================================================
# Boot
# =============================================================================
if __name__ == "__main__":
    register_all_tools()
    app.run(debug=True)
