from __future__ import annotations

import json
from pathlib import Path
from flask import url_for, request

# =========================
# Paths
# =========================
BASE_DIR = Path(__file__).resolve().parents[1]   # CyNiT-Hub/
CONFIG_DIR = BASE_DIR / "config"
TOOLS_JSON = CONFIG_DIR / "tools.json"


# =========================
# Data loaders
# =========================
def load_tools() -> list[dict]:
    if not TOOLS_JSON.exists():
        return []
    data = json.loads(TOOLS_JSON.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "tools" in data:
        data = data["tools"]
    if not isinstance(data, list):
        return []
    return data


def _tool_items(tools: list[dict]) -> list[dict]:
    items = []
    for t in tools:
        if not t.get("enabled", True):
            continue

        web_path = (t.get("web_path") or "").strip()
        if web_path and not web_path.startswith("/"):
            web_path = "/" + web_path

        items.append({
            "name": t.get("name", t.get("id", "Tool")),
            "icon": t.get("icon", "🧩"),
            "desc": t.get("description", ""),
            "href": web_path or "/",
        })
    return items


def _beheer_items() -> list[dict]:
    return [
        {"name": "Tools Editor", "icon": "⚙️", "desc": "Hide/show + accent + naam/icon", "href": "/beheer/tools"},
        {"name": "Config",       "icon": "🧾", "desc": "settings.json beheren",           "href": "/beheer/config"},
        {"name": "Theme",        "icon": "🎨", "desc": "theme.json beheren",              "href": "/beheer/theme"},
        {"name": "Logs",         "icon": "📜", "desc": "logs viewer",                     "href": "/beheer/logs"},
        {"name": "Hub Editor",   "icon": "🧭", "desc": "hub editor",                      "href": "/beheer/hub"},
    ]


# =========================
# Layout renderer
# =========================
def render_page(*, title: str, content_html: str) -> str:
    """
    title = PAGINA titel (bv: 'Theme', 'VOICA1', 'Home')
    """

    # ---------- bepaal context ----------
    path = request.path or ""

    if path.startswith("/beheer"):
        brand = "CyNiT Beheer"
    else:
        brand = "CyNiT Tools"

    page_title = f"{brand} | {title}" if title else brand

    # ---------- assets ----------
    css_href = url_for("static", filename="main.css")
    js_src = url_for("static", filename="main.js")

    logo_src = "/images/logo.png?v=1"
    favicon_ico = "/images/logo.ico"

    tools = _tool_items(load_tools())
    beheer = _beheer_items()

    # ---------- dropdown rendering ----------
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

    # ---------- HTML ----------
    return f"""<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <link rel="icon" href="{favicon_ico}">
  <link rel="stylesheet" href="{css_href}">
</head>

<body class="page">

<header class="topbar">
  <div class="topbar-left">
    <button id="btn-tools" class="iconbtn iconbtn-big" title="Tools">🔧</button>
  </div>

  <a class="brand" href="/">
    <img class="brand-logo" src="{logo_src}" alt="CyNiT logo">
    <span class="brand-title">{brand}</span>
  </a>

  <div class="topbar-right">
    <div class="pill">{title}</div>
    <button id="btn-beheer" class="iconbtn iconbtn-big" title="Beheer">⚙️</button>
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
