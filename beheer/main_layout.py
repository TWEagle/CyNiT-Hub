from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from flask import url_for, request

# =========================
# Paths
# =========================
BASE_DIR = Path(__file__).resolve().parents[1]  # CyNiT-Hub/
CONFIG_DIR = BASE_DIR / "config"
TOOLS_JSON = CONFIG_DIR / "tools.json"
HUB_SETTINGS_JSON = CONFIG_DIR / "hub_settings.json"


# =========================
# Loaders
# =========================
def load_tools() -> List[dict]:
    if not TOOLS_JSON.exists():
        return []
    data = json.loads(TOOLS_JSON.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "tools" in data:
        data = data["tools"]
    if not isinstance(data, list):
        return []
    return data


def load_hub_settings() -> Dict[str, Any]:
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
        return defaults

    raw = HUB_SETTINGS_JSON.read_text(encoding="utf-8").strip()
    if not raw:
        return defaults

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            defaults.update(data)
    except Exception:
        pass

    return defaults


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


def _tool_items(tools: List[dict]) -> List[dict]:
    items = []
    for t in tools:
        if not t.get("enabled", True):
            continue
        if t.get("hidden", False):
            continue

        web_path = (t.get("web_path") or "").strip()
        if web_path and not web_path.startswith("/"):
            web_path = "/" + web_path

        icon = t.get("icon_web") or t.get("icon") or "🧩"

        items.append({
            "name": t.get("name", t.get("id", "Tool")),
            "icon": icon,
            "desc": t.get("description", ""),
            "href": web_path or "/",
        })
    return items


def _beheer_items() -> List[dict]:
    return [
        {"name": "Tools Editor", "icon": "⚙️", "desc": "Tools beheren", "href": "/beheer/tools"},
        {"name": "Config",       "icon": "🧾", "desc": "settings.json beheren", "href": "/beheer/config"},
        {"name": "Theme",        "icon": "🎨", "desc": "theme.json beheren", "href": "/beheer/theme"},
        {"name": "Logs",         "icon": "📜", "desc": "logs viewer", "href": "/beheer/logs"},
        {"name": "Hub Editor",   "icon": "🧭", "desc": "hub settings", "href": "/beheer/hub"},
    ]


# =========================
# Layout renderer
# =========================
def render_page(*, title: str, content_html: str) -> str:
    path = request.path or ""
    hub = load_hub_settings()

    if path.startswith("/beheer"):
        brand = hub.get("brand_beheer", "CyNiT Beheer")
    else:
        brand = hub.get("brand_tools", "CyNiT Tools")

    page_title = f"{brand} | {title}" if title else brand

    css_href = url_for("static", filename="main.css")
    js_src = url_for("static", filename="main.js")

    logo_src = hub.get("logo_src") or "/images/logo.png?v=1"
    favicon_ico = hub.get("favicon_ico") or "/images/logo.ico"

    tools = _tool_items(load_tools())
    beheer = _beheer_items()

    body_classes = ["page"]
    body_classes.append("btnbg-on" if hub.get("button_bg", True) else "btnbg-off")
    body_classes.append("btnround-on" if hub.get("button_rounded", True) else "btnround-off")

    def dd_item(it: dict) -> str:
        return f"""
        <a class="dropdown-item" href="{it["href"]}">
          <div class="dd-icon">{it["icon"]}</div>
          <div class="dd-text">
            <div class="dd-name">{it["name"]}</div>
            <div class="dd-desc">{it["desc"]}</div>
          </div>
        </a>
        """

    tools_html = "\n".join(dd_item(it) for it in tools) or '<div class="dropdown-empty">Geen tools</div>'
    beheer_html = "\n".join(dd_item(it) for it in beheer) or '<div class="dropdown-empty">Geen beheer items</div>'

    return f"""<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <link rel="icon" href="{favicon_ico}">
  <link rel="stylesheet" href="{css_href}">
</head>

<body class="{' '.join(body_classes)}">

<header class="topbar">
  <div class="topbar-left">
    <button id="btn-tools" class="iconbtn iconbtn-big" title="Tools" type="button">🔧</button>
  </div>

  <a class="brand" href="/">
    <img class="brand-logo" src="{logo_src}" alt="CyNiT logo">
    <span class="brand-title">{page_title}</span>
  </a>

  <div class="topbar-right">
    <button id="btn-beheer" class="iconbtn iconbtn-big" title="Beheer" type="button">⚙️</button>
  </div>
</header>

<div id="menu-tools" class="dropdown">
  <div class="dropdown-title">Tools</div>
  {tools_html}
</div>

<div id="menu-beheer" class="dropdown">
  <div class="dropdown-title">Beheer</div>
  {beheer_html}
</div>

<main class="main">
  <div class="pagewrap">
    {content_html}
  </div>
</main>

<footer class="footer">
  CyNiT Hub — footer altijd zichtbaar
</footer>

<script src="{js_src}"></script>
</body>
</html>
"""
