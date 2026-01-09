from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, render_template_string, request, send_from_directory, redirect, url_for

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
IMAGES_DIR = ROOT / "images"
LOGS_DIR = ROOT / "logs"

TOOLS_JSON = CONFIG_DIR / "tools.json"
BEHEER_JSON = CONFIG_DIR / "beheer.json"

# ---- logging (naar logs/app.log) ----
LOGS_DIR.mkdir(parents=True, exist_ok=True)
log_path = LOGS_DIR / "app.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("ctools")


app = Flask(
    __name__,
    static_folder="static",
    static_url_path="/static",
)


# -----------------------------
# Helpers: JSON load/save
# -----------------------------
def _load_json(path: Path, fallback: Any) -> Any:
    try:
        if not path.exists():
            return fallback
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Failed to load json %s: %s", path, exc)
        return fallback


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def load_tools() -> List[Dict[str, Any]]:
    data = _load_json(TOOLS_JSON, fallback=[])
    if isinstance(data, dict):
        data = data.get("tools", [])
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    for t in data:
        if isinstance(t, dict):
            out.append(t)
    return out


def save_tools(tools: List[Dict[str, Any]]) -> None:
    _save_json(TOOLS_JSON, tools)


def load_beheer_items() -> List[Dict[str, Any]]:
    data = _load_json(BEHEER_JSON, fallback=[])
    if isinstance(data, dict):
        data = data.get("items", [])
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in data:
        if isinstance(it, dict):
            out.append(it)
    return out


def is_enabled(item: Dict[str, Any]) -> bool:
    return bool(item.get("enabled", True))


def _norm_path(p: str) -> str:
    p = (p or "").strip()
    if not p:
        return "/"
    if not p.startswith("/"):
        p = "/" + p
    return p


def _clean_hex(c: str) -> str:
    c = (c or "").strip()
    if not c:
        return "#00f700"
    if not c.startswith("#"):
        c = "#" + c
    if len(c) != 7:
        return "#00f700"
    ok = all(ch in "0123456789abcdefABCDEF#" for ch in c)
    return c if ok else "#00f700"


def find_title_for_path(path: str, tools: List[Dict[str, Any]], beheer: List[Dict[str, Any]]) -> str:
    path = _norm_path(path)

    for t in tools:
        wp = _norm_path(str(t.get("web_path", "")))
        if wp != "/" and path.startswith(wp):
            return str(t.get("name") or "CyNiT Tools")

    for b in beheer:
        bp = _norm_path(str(b.get("path", "")))
        if bp != "/" and path.startswith(bp):
            return str(b.get("label") or "Beheer")

    return "CyNiT Tools"


# -----------------------------
# Images served from /images (must stay there)
# -----------------------------
@app.route("/images/<path:filename>")
def images(filename: str):
    return send_from_directory(IMAGES_DIR, filename)


# -----------------------------
# Tool dynamic loader
# -----------------------------
def _module_from_tool(tool: Dict[str, Any]) -> Optional[str]:
    """
    Tries to determine module name for tool import.
    Supports:
      - tool["module"] = "tools.voica1"
      - tool["script"] = "voica1.py"  -> "tools.voica1"
      - tool["script"] = "tools/voica1.py" -> "tools.voica1"
    """
    mod = (tool.get("module") or "").strip()
    if mod:
        return mod

    script = (tool.get("script") or "").strip()
    if not script:
        return None

    script = script.replace("\\", "/")
    if script.endswith(".py"):
        script = script[:-3]
    # strip leading folders
    if "/" in script:
        parts = [p for p in script.split("/") if p]
        # if first part is "tools", drop it
        if parts and parts[0] == "tools":
            parts = parts[1:]
        if not parts:
            return None
        script = parts[-1]

    # final module
    return f"tools.{script}"


def _register_tool_module(modname: str) -> Tuple[bool, str]:
    try:
        mod = importlib.import_module(modname)

        # Preferred: register_web_routes(app, SETTINGS, TOOLS) or (app)
        if hasattr(mod, "register_web_routes"):
            fn = getattr(mod, "register_web_routes")
            try:
                fn(app)  # keep it simple for now
            except TypeError:
                # backward compatible signatures
                fn(app, {}, [])
            return True, "register_web_routes"

        if hasattr(mod, "register_routes"):
            fn = getattr(mod, "register_routes")
            fn(app)
            return True, "register_routes"

        # Blueprint fallback: bp / blueprint
        bp = getattr(mod, "bp", None) or getattr(mod, "blueprint", None)
        if bp is not None:
            app.register_blueprint(bp)
            return True, "blueprint"

        return False, "no register function (needs register_web_routes/register_routes or bp)"
    except Exception as exc:
        return False, f"import/register failed: {exc}"


def register_all_tools() -> None:
    tools = load_tools()
    for t in tools:
        if not is_enabled(t):
            continue
        modname = _module_from_tool(t)
        if not modname:
            continue
        ok, how = _register_tool_module(modname)
        if ok:
            log.info("Tool loaded: %s (%s)", modname, how)
        else:
            log.warning("Tool not loaded: %s (%s)", modname, how)


# -----------------------------
# Base template
# -----------------------------
BASE_HTML = r"""
<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ page_title }}</title>

  <link rel="icon" href="{{ url_for('images', filename='logo.ico') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='cynit.css') }}">
  <script defer src="{{ url_for('static', filename='cynit.js') }}"></script>
</head>

<body class="page">

<header class="topbar">
  <!-- LEFT: Tools menu -->
  <div class="topbar-left">
    <button class="iconbtn iconbtn-big" id="btn-tools" title="Tools" aria-haspopup="true" aria-expanded="false">🔧</button>

    <div class="dropdown" id="menu-tools" aria-label="Tools menu">
      <div class="dropdown-title">Tools</div>

      {% for t in tools_menu %}
        <a class="dropdown-item" href="{{ t.web_path }}">
          <span class="dd-icon">{{ t.icon }}</span>
          <span class="dd-text">
            <span class="dd-name">{{ t.name }}</span>
            {% if t.description %}
              <span class="dd-desc">{{ t.description }}</span>
            {% endif %}
          </span>
        </a>
      {% endfor %}

      {% if tools_menu|length == 0 %}
        <div class="dropdown-empty">Geen tools geactiveerd in config/tools.json</div>
      {% endif %}
    </div>
  </div>

  <!-- CENTER: LOGO + TITLE -->
  <a class="brand" href="/" title="Home">
    <img class="brand-logo" src="{{ url_for('images', filename='logo.png') }}?v=1" alt="CyNiT">
    <span class="brand-title">{{ header_title }}</span>
  </a>

  <!-- RIGHT: Beheer menu -->
  <div class="topbar-right">
    <button class="iconbtn iconbtn-big" id="btn-beheer" title="Beheer" aria-haspopup="true" aria-expanded="false">⚙️</button>

    <div class="dropdown dropdown-right" id="menu-beheer" aria-label="Beheer menu">
      <div class="dropdown-title">Beheer</div>

      {% for b in beheer_menu %}
        <a class="dropdown-item" href="{{ b.path }}">
          <span class="dd-icon">{{ b.icon }}</span>
          <span class="dd-text">
            <span class="dd-name">{{ b.label }}</span>
            {% if b.description %}
              <span class="dd-desc">{{ b.description }}</span>
            {% endif %}
          </span>
        </a>
      {% endfor %}

      {% if beheer_menu|length == 0 %}
        <div class="dropdown-empty">Geen beheer-items geactiveerd in config/beheer.json</div>
      {% endif %}
    </div>
  </div>
</header>

<main class="main">
  {{ content|safe }}
</main>

<footer class="footer">
  CyNiT Hub — footer altijd zichtbaar
</footer>

</body>
</html>
"""


def render_page(content_html: str) -> str:
    tools = load_tools()
    beheer = load_beheer_items()
    page_title = find_title_for_path(request.path, tools, beheer)

    return render_template_string(
        BASE_HTML,
        page_title=page_title,
        header_title=page_title,
        tools_menu=[{
            "name": t.get("name", ""),
            "web_path": _norm_path(str(t.get("web_path", "/"))),
            "icon": t.get("icon", "🧩"),
            "description": t.get("description", "")
        } for t in tools if is_enabled(t)],
        beheer_menu=[{
            "label": b.get("label", ""),
            "path": _norm_path(str(b.get("path", "/"))),
            "icon": b.get("icon", "⚙️"),
            "description": b.get("description", "")
        } for b in beheer if is_enabled(b)],
        content=content_html,
    )


# -----------------------------
# Home: cards from tools.json
# -----------------------------
def render_home(tools: List[Dict[str, Any]]) -> str:
    enabled = [t for t in tools if is_enabled(t)]

    cards_html = []
    for t in enabled:
        name = str(t.get("name") or "Tool")
        desc = str(t.get("description") or "")
        wp = _norm_path(str(t.get("web_path") or "/"))
        icon = str(t.get("icon") or "🧩")
        accent = _clean_hex(str(t.get("accent") or "#00f700"))

        cards_html.append(f"""
          <a class="toolcard" href="{wp}" style="--accent:{accent}">
            <div class="toolcard-head">
              <span class="toolcard-icon">{icon}</span>
              <span class="toolcard-title">{name}</span>
            </div>
            <div class="toolcard-desc">{desc}</div>
            <div class="toolcard-hint">Linkerklik: open • Rechterklik: nieuwe tab</div>
          </a>
        """)

    if not cards_html:
        cards_html.append("""
          <div class="panel">
            <h2>Home</h2>
            <p>Geen tools zichtbaar. Zet <code>enabled: true</code> in <code>config/tools.json</code>.</p>
          </div>
        """)

    return f"""
      <div class="pagewrap">
        <div class="panel">
          <h1>Home</h1>
          <p>Tools/cards komen uit <code>config/tools.json</code>.</p>
        </div>

        <div class="cards">
          {''.join(cards_html)}
        </div>
      </div>
    """


# -----------------------------
# Routes
# -----------------------------
@app.route("/")
def home():
    return render_page(render_home(load_tools()))


# --------- Beheer placeholders ----------
@app.route("/beheer/config")
def beheer_config():
    return render_page("""
      <div class="pagewrap">
        <div class="panel">
          <h1>Beheer • Config</h1>
          <p>Placeholder.</p>
        </div>
      </div>
    """)


@app.route("/beheer/theme")
def beheer_theme():
    return render_page("""
      <div class="pagewrap">
        <div class="panel">
          <h1>Beheer • Theme</h1>
          <p>Placeholder.</p>
        </div>
      </div>
    """)


@app.route("/beheer/logs")
def beheer_logs():
    return render_page("""
      <div class="pagewrap">
        <div class="panel">
          <h1>Beheer • Logs</h1>
          <p>Placeholder. (Stap 7.2)</p>
        </div>
      </div>
    """)


@app.route("/beheer/hub")
def beheer_hub():
    return render_page("""
      <div class="pagewrap">
        <div class="panel">
          <h1>Beheer • Hub</h1>
          <p>Placeholder. (Stap 7.3)</p>
        </div>
      </div>
    """)


# -----------------------------
# Stap 7.1: Tools editor (preserve script/extra fields!)
# -----------------------------
@app.route("/beheer/tools", methods=["GET", "POST"])
def beheer_tools():
    tools = load_tools()

    if request.method == "POST":
        try:
            row_count = int(request.form.get("row_count", "0") or "0")
        except ValueError:
            row_count = 0

        new_tools: List[Dict[str, Any]] = []
        seen_ids = set()

        for i in range(row_count):
            if (request.form.get(f"deleted_{i}", "") or "").strip() == "1":
                continue

            orig_raw = request.form.get(f"orig_{i}", "") or ""
            try:
                orig = json.loads(orig_raw) if orig_raw else {}
            except Exception:
                orig = {}

            tid = (request.form.get(f"id_{i}", "") or "").strip()
            name = (request.form.get(f"name_{i}", "") or "").strip()
            icon = (request.form.get(f"icon_{i}", "") or "").strip()
            web_path = _norm_path((request.form.get(f"web_path_{i}", "") or "").strip())
            desc = (request.form.get(f"description_{i}", "") or "").strip()
            accent = _clean_hex((request.form.get(f"accent_{i}", "") or "").strip())
            enabled = request.form.get(f"enabled_{i}") == "on"

            script = (request.form.get(f"script_{i}", "") or "").strip()
            tool_type = (request.form.get(f"type_{i}", "") or "").strip()

            if not tid:
                tid = f"tool_{i+1}"
            if tid in seen_ids:
                suffix = 2
                base = tid
                while f"{base}_{suffix}" in seen_ids:
                    suffix += 1
                tid = f"{base}_{suffix}"
            seen_ids.add(tid)

            if not name:
                name = tid
            if not icon:
                icon = "🧩"

            # preserve unknown fields from orig, then overwrite our edited fields
            merged: Dict[str, Any] = {}
            if isinstance(orig, dict):
                merged.update(orig)

            merged.update({
                "id": tid,
                "name": name,
                "icon": icon,
                "web_path": web_path,
                "description": desc,
                "accent": accent,
                "enabled": enabled,
            })

            # keep script/type if given or already existed
            if script or "script" in merged:
                merged["script"] = script or merged.get("script", "")
            if tool_type or "type" in merged:
                merged["type"] = tool_type or merged.get("type", "")

            new_tools.append(merged)

        save_tools(new_tools)
        return redirect(url_for("beheer_tools"))

    # GET
    rows = []
    for t in tools:
        rows.append({
            "id": str(t.get("id", "")),
            "name": str(t.get("name", "")),
            "icon": str(t.get("icon", "🧩")),
            "web_path": _norm_path(str(t.get("web_path", "/"))),
            "description": str(t.get("description", "")),
            "accent": _clean_hex(str(t.get("accent", "#00f700"))),
            "enabled": bool(t.get("enabled", True)),
            "script": str(t.get("script", "")),
            "type": str(t.get("type", "")),
            "orig": t,  # full dict preserved
        })

    content = render_template_string(
        r"""
<div class="pagewrap">
  <div class="panel">
    <h1>Beheer • Tools editor</h1>
    <p>Beheer <code>config/tools.json</code> (hide/show + accent + naam/icon + path + script). Onbekende velden blijven behouden.</p>
  </div>

  <form method="post" class="panel">
    <input type="hidden" name="row_count" id="row_count" value="{{ rows|length }}">

    <div class="tools-toolbar">
      <button type="button" class="btn" id="btn-add-tool">➕ Tool toevoegen</button>
      <button type="submit" class="btn btn-primary">💾 Opslaan</button>
      <a class="btn" href="/">↩ Home</a>
    </div>

    <div class="tablewrap">
      <table class="tooltable" id="tooltable">
        <thead>
          <tr>
            <th class="col-move">⇅</th>
            <th class="col-enabled">Aan</th>
            <th class="col-icon">Icon</th>
            <th class="col-name">Naam</th>
            <th class="col-id">ID</th>
            <th class="col-path">Web path</th>
            <th class="col-script">Script</th>
            <th class="col-type">Type</th>
            <th class="col-accent">Accent</th>
            <th class="col-desc">Beschrijving</th>
            <th class="col-del">X</th>
          </tr>
        </thead>
        <tbody id="tooltable-body">
          {% for r in rows %}
          <tr class="toolrow" data-index="{{ loop.index0 }}">
            <td class="col-move">
              <button type="button" class="mini" data-action="up">↑</button>
              <button type="button" class="mini" data-action="down">↓</button>
              <input type="hidden" name="deleted_{{ loop.index0 }}" value="0">
              <input type="hidden" name="orig_{{ loop.index0 }}" value='{{ r.orig|tojson }}'>
            </td>

            <td class="col-enabled">
              <label class="switch">
                <input type="checkbox" name="enabled_{{ loop.index0 }}" {% if r.enabled %}checked{% endif %}>
                <span class="slider"></span>
              </label>
            </td>

            <td class="col-icon">
              <input class="inp inp-icon" name="icon_{{ loop.index0 }}" value="{{ r.icon }}">
            </td>

            <td class="col-name">
              <input class="inp" name="name_{{ loop.index0 }}" value="{{ r.name }}">
            </td>

            <td class="col-id">
              <input class="inp inp-id" name="id_{{ loop.index0 }}" value="{{ r.id }}">
            </td>

            <td class="col-path">
              <input class="inp inp-path" name="web_path_{{ loop.index0 }}" value="{{ r.web_path }}">
            </td>

            <td class="col-script">
              <input class="inp inp-script" name="script_{{ loop.index0 }}" value="{{ r.script }}" placeholder="voica1.py">
            </td>

            <td class="col-type">
              <input class="inp inp-type" name="type_{{ loop.index0 }}" value="{{ r.type }}" placeholder="web">
            </td>

            <td class="col-accent">
              <div class="accentbox">
                <input class="inp inp-accent" name="accent_{{ loop.index0 }}" value="{{ r.accent }}">
                <input type="color" class="colorpick" value="{{ r.accent }}" data-bind="accent">
              </div>
            </td>

            <td class="col-desc">
              <input class="inp" name="description_{{ loop.index0 }}" value="{{ r.description }}">
            </td>

            <td class="col-del">
              <button type="button" class="mini danger" data-action="delete">✖</button>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <p class="hint">
      Script voorbeeld: <code>voica1.py</code> of <code>tools/voica1.py</code>. Web path start met <code>/</code>. Accent is <code>#RRGGBB</code>.
    </p>
  </form>
</div>
        """,
        rows=rows
    )

    return render_page(content)


# ---- IMPORTANT: register tools after routes are defined ----
register_all_tools()


if __name__ == "__main__":
    app.run(debug=True)
