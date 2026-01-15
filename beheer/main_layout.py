
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

from flask import request, url_for

# =========================
# Paths
# =========================
BASE_DIR = Path(__file__).resolve().parents[1]  # CyNiT-Hub/
CONFIG_DIR = BASE_DIR / "config"
TOOLS_JSON = CONFIG_DIR / "tools.json"
HUB_SETTINGS_JSON = CONFIG_DIR / "hub_settings.json"
THEME_JSON = CONFIG_DIR / "theme.json"


# =========================
# Loaders
# =========================
def load_tools() -> List[dict]:
    """Reads config/tools.json; supports either [..] or {"tools":[..]}."""
    if not TOOLS_JSON.exists():
        return []
    raw = TOOLS_JSON.read_text(encoding="utf-8").strip()
    if not raw:
        return []

    data = json.loads(raw)
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
    }

    if not HUB_SETTINGS_JSON.exists():
        return dict(defaults)

    raw = HUB_SETTINGS_JSON.read_text(encoding="utf-8").strip()
    if not raw:
        return dict(defaults)

    try:
        data = json.loads(raw)

        # legacy: [ { ... } ]
        if isinstance(data, list) and data and isinstance(data[0], dict):
            defaults.update(data[0])

        # dict: { ... }
        elif isinstance(data, dict):
            defaults.update(data)
    except Exception:
        pass

    return dict(defaults)


# =========================
# Theme config
# =========================
def _default_theme_config() -> Dict[str, Any]:
    return {
        "active": "dark",
        "themes": {
            "dark": {
                "icon": "🌙",
                "label": "Dark",
                "vars": {
                    "--bg": "#000000",
                    "--text": "#e8f2f2",
                    "--muted": "#9fb3b3",
                    "--border": "rgba(255,255,255,.10)",
                    "--shadow": "0 12px 40px rgba(0,0,0,.55)",
                    "--accent": "#35e6df",
                    "--grad_top": "#08121a",
                    "--grad_bottom": "#000000",
                    "--panel_bg": "rgba(10,15,18,.75)",
                    "--card_bg": "rgba(10,15,18,.68)",
                },
            },
            "light": {
                "icon": "☀️",
                "label": "Light",
                "vars": {
                    "--bg": "#f7fbff",
                    "--text": "#08121a",
                    "--muted": "#355156",
                    "--border": "rgba(0,0,0,.10)",
                    "--shadow": "0 12px 40px rgba(0,0,0,.15)",
                    "--accent": "#0aa6a0",
                    "--grad_top": "#ffffff",
                    "--grad_bottom": "#eaf6ff",
                    "--panel_bg": "rgba(255,255,255,.75)",
                    "--card_bg": "rgba(255,255,255,.72)",
                },
            },
        },
    }


def load_theme_config() -> Dict[str, Any]:
    if not THEME_JSON.exists():
        return _default_theme_config()

    raw = THEME_JSON.read_text(encoding="utf-8").strip()
    if not raw:
        return _default_theme_config()

    try:
        cfg = json.loads(raw)
        if not isinstance(cfg, dict):
            return _default_theme_config()
    except Exception:
        return _default_theme_config()

    # normalize minimal structure
    themes = cfg.get("themes")
    if not isinstance(themes, dict) or not themes:
        cfg = _default_theme_config()
        themes = cfg["themes"]

    active = str(cfg.get("active") or "").strip()
    if active not in themes:
        active = next(iter(themes.keys()))
        cfg["active"] = active

    # normalize each theme
    for k, v in list(themes.items()):
        if not isinstance(v, dict):
            themes[k] = {"icon": "🎨", "label": k, "vars": {}}
            continue
        if "icon" not in v:
            v["icon"] = "🎨"
        if "label" not in v:
            v["label"] = k
        if "vars" not in v or not isinstance(v["vars"], dict):
            v["vars"] = {}

    cfg["themes"] = themes
    return cfg


def _save_theme_config(cfg: Dict[str, Any]) -> None:
    THEME_JSON.parent.mkdir(parents=True, exist_ok=True)
    THEME_JSON.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def _css_escape_val(v: Any) -> str:
    # very light “escape”: just strip newlines to prevent breaking <style>
    s = str(v if v is not None else "").replace("\r", " ").replace("\n", " ").strip()
    return s


def _build_theme_injected_css(cfg: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Returns:
      (active_key, active_icon, css_string)
    """
    themes = cfg.get("themes", {})
    active = str(cfg.get("active") or "").strip()

    if not isinstance(themes, dict) or not themes:
        cfg = _default_theme_config()
        themes = cfg["themes"]
        active = cfg["active"]

    if active not in themes:
        active = next(iter(themes.keys()))

    theme = themes.get(active, {}) if isinstance(themes.get(active), dict) else {}
    icon = str(theme.get("icon") or "🎨")
    vars_map = theme.get("vars", {})
    if not isinstance(vars_map, dict):
        vars_map = {}

    # Ensure minimum defaults exist
    merged = dict(_default_theme_config()["themes"]["dark"]["vars"])
    merged.update(vars_map)

    decls = "\n".join([f"  {k}: {_css_escape_val(v)};" for k, v in merged.items() if str(k).startswith("--")])

    css = f"""
/* ===== THEME INJECT (config/theme.json) ===== */
:root {{
{decls}
}}
/* override body gradient via theme vars */
body, body.page {{
  background: radial-gradient(1200px 700px at 50% 0%, var(--grad_top) 0%, var(--grad_bottom) 60%) !important;
  background-color: var(--bg) !important;
  color: var(--text) !important;
}}
/* panels/cards can follow theme vars without rewriting main.css */
.panel {{
  background: var(--panel_bg) !important;
}}
.toolcard {{
  background: var(--card_bg) !important;
}}
"""
    return active, icon, css


# =========================
# Menu helpers
# =========================
def _tool_items(tools: List[dict]) -> List[dict]:
    items: List[dict] = []
    for t in tools:
        if not t.get("enabled", True):
            continue
        if t.get("hidden", False):
            continue

        web_path = (t.get("web_path") or "").strip()
        if web_path and not web_path.startswith("/"):
            web_path = "/" + web_path

        icon = t.get("icon_web") or t.get("icon") or "🧩"
        items.append(
            {
                "name": t.get("name", t.get("id", "Tool")),
                "icon": icon,
                "desc": t.get("description", ""),
                "href": web_path or "/",
            }
        )
    return items


def _beheer_items() -> List[dict]:
    return [
        {"name": "Tools Editor", "icon": "⚙️", "desc": "Tools beheren", "href": "/beheer/tools"},
        {"name": "Hub Editor",   "icon": "🧭", "desc": "Hub instellingen", "href": "/beheer/hub"},
        {"name": "Theme",        "icon": "🎨", "desc": "Theme configuratie", "href": "/beheer/theme"},
        {"name": "Config",       "icon": "🧾", "desc": "settings.json beheren", "href": "/beheer/config"},
        {"name": "Logs",         "icon": "📜", "desc": "Logs bekijken", "href": "/beheer/logs"},
    ]


# =========================
# Layout renderer
# =========================
def render_page(*, title: str, content_html: str) -> str:
    """
    Renders the hub layout safely, with % formatting so CSS/JS braces { } don't
    conflict with Python formatting.
    """
    path = request.path or ""
    hub = load_hub_settings()

    # Brand selection
    if path.startswith("/beheer"):
        brand = str(hub.get("brand_beheer") or "CyNiT Beheer")
    else:
        brand = str(hub.get("brand_tools") or "CyNiT Tools")

    # Brand | Page (header + <title>)
    page_title = f"{brand} | {title}" if title else brand

    # NOTE: your static files are under /static/css and /static/js
    css_href = url_for("static", filename="css/main.css")
    js_src  = url_for("static", filename="js/main.js")

    logo_src = str(hub.get("logo_src") or "/images/logo.png?v=1")
    favicon_ico = str(hub.get("favicon_ico") or "/images/logo.ico")

    tools = _tool_items(load_tools())
    beheer = _beheer_items()

    body_classes = ["page"]
    body_classes.append("btnbg-on" if hub.get("button_bg", True) else "btnbg-off")
    body_classes.append("btnround-on" if hub.get("button_rounded", True) else "btnround-off")
    body_classes_str = " ".join(body_classes)

    def dd_item(it: dict) -> str:
        return """
        <a class="dropdown-item" href="%(href)s">
          <div class="dd-icon">%(icon)s</div>
          <div class="dd-text">
            <div class="dd-name">%(name)s</div>
            <div class="dd-desc">%(desc)s</div>
          </div>
        </a>
        """ % it

    tools_html = "\n".join(dd_item(it) for it in tools) or '<div class="dropdown-empty">Geen tools</div>'
    beheer_html = "\n".join(dd_item(it) for it in beheer) or '<div class="dropdown-empty">Geen beheer items</div>'

    # theme inject
    theme_cfg = load_theme_config()
    active_key, active_icon, theme_css = _build_theme_injected_css(theme_cfg)
    themes = theme_cfg.get("themes", {})
    if not isinstance(themes, dict):
        themes = {}

    # back url (current page)
    back_url = request.full_path or "/"
    if back_url.endswith("?"):
        back_url = back_url[:-1]
    back_q = quote(back_url, safe="")

    # theme dropdown options
    theme_options = []
    for k, v in themes.items():
        if not isinstance(v, dict):
            v = {}
        icon = str(v.get("icon") or "🎨")
        label = str(v.get("label") or k)
        sel = "selected" if k == active_key else ""
        theme_options.append(f'<option value="{k}" {sel}>{icon} {label}</option>')
    theme_options_html = "\n".join(theme_options) if theme_options else '<option value="dark">🌙 Dark</option>'

    # footer toggle icon: if 2 themes, show opposite; else show active
    toggle_icon = "🎨"
    try:
        keys = list(themes.keys())
        if len(keys) == 2 and active_key in keys:
            other = keys[1] if active_key == keys[0] else keys[0]
            ov = themes.get(other, {})
            if isinstance(ov, dict):
                toggle_icon = str(ov.get("icon") or "🎨")
        else:
            toggle_icon = active_icon
    except Exception:
        toggle_icon = active_icon

    # Build final HTML with % formatting (so { } in CSS/JS are safe)
    html = """<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>%(page_title)s</title>
  <link rel="icon" href="%(favicon_ico)s">
  <link rel="stylesheet" href="%(css_href)s">
  <style>
  %(theme_css)s
  /* header title: shrink smoothly if long */
  .brand-title {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: min(72vw, 860px);
    display: inline-block;
    font-size: clamp(14px, 2.2vw, 24px);
  }
  </style>
</head>

<body class="%(body_classes)s">

<header class="topbar">
  <div class="topbar-left">
    <button id="btn-tools" class="iconbtn iconbtn-big" title="Tools" type="button">🔧</button>
  </div>

  <a class="brand" href="/">
    <img class="brand-logo" src="%(logo_src)s" alt="CyNiT logo">
    <span class="brand-title">%(page_title)s</span>
  </a>

  <div class="topbar-right">
    <button id="btn-beheer" class="iconbtn iconbtn-big" title="Beheer" type="button">⚙️</button>
  </div>
</header>

<div id="menu-tools" class="dropdown">
  <div class="dropdown-title">Tools</div>
  %(tools_html)s
</div>

<div id="menu-beheer" class="dropdown">
  <div class="dropdown-title">Beheer</div>
  %(beheer_html)s
</div>

<main class="main">
  <div class="pagewrap">
    %(content_html)s
  </div>
</main>

<footer class="footer" style="justify-content:space-between; gap:14px;">
  <div style="display:flex; align-items:center; gap:12px; min-width:0;">
    <span style="white-space:nowrap;">© CyNiT 2024 - 2026</span>

    <span class="pill" title="Actieve theme">%(active_icon)s %(active_key)s</span>

    <select id="themeSelect" style="max-width:260px;" title="Theme kiezen">
      %(theme_options_html)s
    </select>

    <a class="btn" href="/theme/toggle?back=%(back_q)s" title="Toggle theme">%(toggle_icon)s</a>
  </div>

  <div style="display:flex; align-items:center; gap:10px;">
    <span class="pill">Theme</span>
  </div>
</footer>

<script>
(function(){
  const sel = document.getElementById("themeSelect");
  if(!sel) return;
  sel.addEventListener("change", function(){
    const name = encodeURIComponent(sel.value || "");
    const back = "%(back_q)s";
    window.location.href = "/theme/set?name=" + name + "&back=" + back;
  });

  // simple dropdown toggles
  const btnTools = document.getElementById("btn-tools");
  const btnBeheer = document.getElementById("btn-beheer");
  const ddTools = document.getElementById("menu-tools");
  const ddBeheer = document.getElementById("menu-beheer");
  function toggle(el){ el && el.classList.toggle("open"); }
  btnTools && btnTools.addEventListener("click", ()=>{ toggle(ddTools); ddBeheer && ddBeheer.classList.remove("open"); });
  btnBeheer && btnBeheer.addEventListener("click", ()=>{ toggle(ddBeheer); ddTools && ddTools.classList.remove("open"); });
  document.addEventListener("click", (e)=>{
    const t = e.target;
    if (!t.closest(".topbar") && !t.closest(".dropdown")) {
      ddTools && ddTools.classList.remove("open");
      ddBeheer && ddBeheer.classList.remove("open");
    }
  });
})();
</script>

<script src="%(js_src)s"></script>
</body>
</html>
""" % {
        "page_title": page_title,
        "favicon_ico": favicon_ico,
        "css_href": css_href,
        "theme_css": theme_css,
        "body_classes": body_classes_str,
        "logo_src": logo_src,
        "tools_html": tools_html,
        "beheer_html": beheer_html,
        "content_html": content_html,
        "active_icon": active_icon,
        "active_key": active_key,
        "theme_options_html": theme_options_html,
        "back_q": back_q,
        "toggle_icon": toggle_icon,
        "js_src": js_src,
    }

    return html
