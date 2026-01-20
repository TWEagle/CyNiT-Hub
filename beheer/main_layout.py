from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

from flask import request, url_for

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = BASE_DIR / "config"
TOOLS_JSON = CONFIG_DIR / "tools.json"
HUB_SETTINGS_JSON = CONFIG_DIR / "hub_settings.json"
THEME_JSON = CONFIG_DIR / "theme.json"


# =========================
# Loaders
# =========================
def load_tools_config() -> Dict[str, Any]:
    if not TOOLS_JSON.exists():
        return {"tools": []}
    try:
        data = json.loads(TOOLS_JSON.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"tools": []}


def load_tools() -> List[dict]:
    cfg = load_tools_config()
    tools = cfg.get("tools", [])
    return tools if isinstance(tools, list) else []


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

        # legacy: [ { ... } ]
        if isinstance(data, list):
            if data and isinstance(data[0], dict):
                defaults.update(data[0])

        elif isinstance(data, dict):
            defaults.update(data)

    except Exception:
        pass

    # normalize types
    try:
        defaults["home_columns"] = int(defaults.get("home_columns", 3) or 3)
    except Exception:
        defaults["home_columns"] = 3

    defaults["card_bg"] = bool(defaults.get("card_bg", True))
    defaults["card_round"] = bool(defaults.get("card_round", True))
    defaults["button_bg"] = bool(defaults.get("button_bg", True))
    defaults["button_rounded"] = bool(defaults.get("button_rounded", True))

    return dict(defaults)


def load_theme_config() -> Dict[str, Any]:
    if not THEME_JSON.exists():
        return {"active": "Dark", "themes": {}}
    try:
        data = json.loads(THEME_JSON.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"active": "Dark", "themes": {}}


def _css_escape_val(v: Any) -> str:
    s = str(v)
    return s.replace("\n", " ").replace("\r", " ").strip()


def _build_theme_injected_css(cfg: Dict[str, Any]) -> Tuple[str, str, str]:
    themes = cfg.get("themes", {})
    if not isinstance(themes, dict) or not themes:
        return "Dark", "🌙", ""

    active = str(cfg.get("active") or "")
    if active not in themes:
        active = next(iter(themes.keys()))

    theme = themes.get(active, {})
    if not isinstance(theme, dict):
        theme = {}

    icon = str(theme.get("icon") or "🎨")
    vars_map = theme.get("vars", {})
    if not isinstance(vars_map, dict):
        vars_map = {}

    # defaults so things never break
    defv = {
        "--bg": "#000",
        "--text": "#e8f2f2",
        "--muted": "#9fb3b3",
        "--border": "rgba(255,255,255,.10)",
        "--shadow": "0 12px 40px rgba(0,0,0,.55)",
        "--accent": "#35e6df",
        "--grad_top": "#08121a",
        "--grad_bottom": "#000",
        "--panel_bg": "rgba(10,15,18,.55)",
        "--card_bg": "rgba(10,15,18,.68)",
        "--footer_bg": "rgba(0,0,0,.35)",
    }

    merged = dict(defv)
    merged.update(vars_map)

    decls = "\n".join(
        [f"  {k}: {_css_escape_val(v)};" for k, v in merged.items() if str(k).startswith("--")]
    )

    css = f"""
/* ===== THEME INJECT (config/theme.json) ===== */
:root {{
{decls}
}}
body, body.page {{
  background: radial-gradient(1200px 700px at 50% 0%, var(--grad_top) 0%, var(--grad_bottom) 60%) !important;
  background-color: var(--bg) !important;
  color: var(--text) !important;
}}
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
    path = request.path or ""
    hub = load_hub_settings()

    brand = str(hub.get("brand_beheer") or "CyNiT Beheer") if path.startswith("/beheer") else str(hub.get("brand_tools") or "CyNiT Tools")
    page_title = f"{brand} | {title}" if title else brand

    css_href = url_for("static", filename="css/main.css")
    js_src = url_for("static", filename="js/main.js")
    clicks_js_src = url_for("static", filename="js/click_logger.js")  # ✅ nieuw

    logo_src = str(hub.get("logo_src") or "/images/logo.png?v=1")
    favicon_ico = str(hub.get("favicon_ico") or "/images/logo.ico")

    tools = _tool_items(load_tools())
    beheer = _beheer_items()

    body_classes = ["page"]
    body_classes.append("btnbg-on" if hub.get("button_bg", True) else "btnbg-off")
    body_classes.append("btnround-on" if hub.get("button_rounded", True) else "btnround-off")
    body_classes.append("cardbg-on" if hub.get("card_bg", True) else "cardbg-off")
    body_classes.append("cardround-on" if hub.get("card_round", True) else "cardround-off")
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

    theme_cfg = load_theme_config()
    active_key, active_icon, theme_css = _build_theme_injected_css(theme_cfg)

    themes = theme_cfg.get("themes", {})
    if not isinstance(themes, dict):
        themes = {}

    back_url = request.full_path or "/"
    if back_url.endswith("?"):
        back_url = back_url[:-1]
    back_q = quote(back_url, safe="")

    theme_options = []
    for k, v in themes.items():
        if not isinstance(v, dict):
            v = {}
        icon = str(v.get("icon") or "🎨")
        label = str(v.get("label") or k)
        sel = "selected" if k == active_key else ""
        theme_options.append(f'<option value="{k}" {sel}>{icon} {label}</option>')
    theme_options_html = "\n".join(theme_options) if theme_options else '<option value="Dark">🌙 Dark</option>'

    toggle_icon = active_icon
    try:
        keys = list(themes.keys())
        if len(keys) == 2 and active_key in keys:
            other = keys[1] if active_key == keys[0] else keys[0]
            ov = themes.get(other, {})
            if isinstance(ov, dict):
                toggle_icon = str(ov.get("icon") or toggle_icon)
    except Exception:
        pass

    try:
        home_cols = int(hub.get("home_columns", 3) or 3)
    except Exception:
        home_cols = 3
    home_cols = max(1, min(12, home_cols))

    html = """<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>%(page_title)s</title>
  <link rel="icon" href="%(favicon_ico)s">
  <link rel="stylesheet" href="%(css_href)s">
  <style>
  %(theme_css)s
  :root{ --home-cols: %(home_cols)s; }

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
    <button id="btn-tools" class="iconbtn iconbtn-big" title="Tools" type="button" aria-expanded="false">🔧</button>
  </div>

  <a class="brand" href="/">
    <img class="brand-logo" src="%(logo_src)s" alt="CyNiT logo">
    <span class="brand-title">%(page_title)s</span>
  </a>

  <div class="topbar-right">
    <button id="btn-beheer" class="iconbtn iconbtn-big" title="Beheer" type="button" aria-expanded="false">⚙️</button>
  </div>
</header>

<div id="menu-tools" class="dropdown" role="menu" aria-label="Tools">
  <div class="dropdown-title">Tools</div>
  %(tools_html)s
</div>

<div id="menu-beheer" class="dropdown" role="menu" aria-label="Beheer">
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

<!-- 1) Load main.js: dropdowns + UX -->
<script src="%(js_src)s"></script>

<!-- ✅ 2) Click logger: logt alle clicks naar /_log/click -->
<script src="%(clicks_js_src)s"></script>

<!-- 3) Theme select redirect -->
<script>
(function(){
  const sel = document.getElementById("themeSelect");
  if (!sel) return;
  sel.addEventListener("change", function(){
    const name = encodeURIComponent(sel.value || "");
    const back = "%(back_q)s";
    window.location.href = "/theme/set?name=" + name + "&back=" + back;
  });
})();
</script>

</body>
</html>
""" % {
        "page_title": page_title,
        "favicon_ico": favicon_ico,
        "css_href": css_href,
        "js_src": js_src,
        "clicks_js_src": clicks_js_src,
        "theme_css": theme_css,
        "logo_src": logo_src,
        "body_classes": body_classes_str,
        "tools_html": tools_html,
        "beheer_html": beheer_html,
        "active_icon": active_icon,
        "active_key": active_key,
        "theme_options_html": theme_options_html,
        "toggle_icon": toggle_icon,
        "back_q": back_q,
        "home_cols": home_cols,
        "content_html": content_html,
    }

    return html
