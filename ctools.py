import json
from pathlib import Path
from flask import Flask, render_template_string, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"

app = Flask(
    __name__,
    static_folder="static",
    static_url_path="/static"
)

# ===== IMAGES ROUTE (logo blijft in /images) =====
@app.route("/images/<path:filename>")
def images(filename):
    return send_from_directory("images", filename)

def load_tools():
    """
    Laadt tools uit config/tools.json.
    Verwacht: list[dict] met minimaal: name, web_path.
    Optioneel: icon, hidden, order, accent, description
    """
    p = CONFIG_DIR / "tools.json"
    if not p.exists():
        return []

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    tools = []
    for t in data:
        if not isinstance(t, dict):
            continue

        if t.get("hidden") is True:
            continue

        web_path = (t.get("web_path") or "").strip()
        name = (t.get("name") or "").strip()
        if not web_path or not name:
            continue

        tools.append({
            "id": (t.get("id") or "").strip(),
            "name": name,
            "web_path": web_path,
            "icon": (t.get("icon") or "🔧"),
            "description": (t.get("description") or "").strip(),
            "accent": (t.get("accent") or "").strip(),
            "order": int(t.get("order") or 9999),
        })

    tools.sort(key=lambda x: (x["order"], x["name"].lower()))
    return tools


# ===== BASE TEMPLATE =====
BASE_HTML = """
<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>

  <link rel="icon" href="/images/logo.ico">

  <!-- Font Awesome -->
  <link
    rel="stylesheet"
    href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css"
    crossorigin="anonymous"
  />

  <link rel="stylesheet" href="/static/cynit.css">
</head>

<body class="page">

<header class="header">

  <!-- LEFT: TOOLS (🔧 dropdown uit tools.json) -->
  <div class="menu-wrapper">
    <button class="icon-btn" id="toolsBtn" title="Tools">
      <i class="fa-solid fa-screwdriver-wrench"></i>
    </button>

    <div class="dropdown" id="toolsMenu">
      {% for t in tools %}
        <a href="{{ t.web_path }}">{{ t.icon }} {{ t.name }}</a>
      {% endfor %}
      {% if tools|length == 0 %}
        <span class="dropdown-empty">Geen tools in tools.json</span>
      {% endif %}
    </div>
  </div>

  <!-- LEFT: BEHEER (⚙️) -->
  <div class="menu-wrapper">
    <button class="icon-btn" id="beheerBtn" title="Beheer">
      <i class="fa-solid fa-gear"></i>
    </button>

    <div class="dropdown" id="beheerMenu">
      <a href="/beheer/config">⚙️ Config</a>
      <a href="/beheer/theme">🎨 Theme</a>
      <a href="/beheer/logs">📜 Logs</a>
      <a href="/beheer/hub">🧩 Hub editor</a>
      <div class="dropdown-sep"></div>
      <a href="/help">❓ Help</a>
    </div>
  </div>

  <!-- CENTER: LOGO + TITLE (klikbaar) -->
  <a href="/" class="brand" title="Terug naar home">
    <img src="/images/logo.png?v=1" alt="CyNiT logo" class="brand-logo">
    <span class="brand-title">{{ title }}</span>
  </a>

</header>

<main class="main">
  {{ content|safe }}
</main>

<footer class="footer">
  CyNiT Hub — footer altijd zichtbaar
</footer>

<script src="/static/cynit.js"></script>
</body>
</html>
"""

def render_page(title: str, content_html: str):
    return render_template_string(
        BASE_HTML,
        title=title,
        tools=load_tools(),
        content=content_html
    )

# ===== ROUTES =====
@app.route("/")
def home():
    tools = load_tools()

    # Bouw cards uit JSON
    cards_html = []
    for t in tools:
        # Home tool niet als card tonen (optioneel)
        if t["web_path"] == "/":
            continue

        accent = t["accent"] if t["accent"] else "var(--accent)"
        desc = t["description"] or "—"
        cards_html.append(f"""
          <a class="tool-card" href="{t['web_path']}" style="--tool-accent: {accent};">
            <div class="tool-card-top">
              <div class="tool-icon">{t['icon']}</div>
              <div class="tool-name">{t['name']}</div>
            </div>
            <div class="tool-desc">{desc}</div>
            <div class="tool-hint">Linkerklik: open • Rechterklik: nieuwe tab</div>
          </a>
        """)

    grid = "\n".join(cards_html) if cards_html else "<div class='card'><p>Geen tools zichtbaar (tools.json leeg of hidden).</p></div>"

    return render_page(
        "CyNiT Tools",
        f"""
        <div class="card">
          <h1>Home</h1>
          <p>Tools/cards komen nu uit <code>config/tools.json</code>.</p>
        </div>

        <div class="tools-grid">
          {grid}
        </div>
        """
    )

@app.route("/voica1")
def voica1():
    return render_page(
        "VOICA1 Certificaten",
        """
        <div class="card">
          <h1>VOICA1</h1>
          <p>VOICA1 tool placeholder.</p>
          <a class="btn" href="/">Terug naar home</a>
        </div>
        """
    )

# ===== PLACEHOLDER routes for beheer =====
@app.route("/beheer/config")
def beheer_config():
    return render_page("Beheer - Config", "<div class='card'><h1>Config</h1><p>Placeholder.</p></div>")

@app.route("/beheer/theme")
def beheer_theme():
    return render_page("Beheer - Theme", "<div class='card'><h1>Theme</h1><p>Placeholder.</p></div>")

@app.route("/beheer/logs")
def beheer_logs():
    return render_page("Beheer - Logs", "<div class='card'><h1>Logs</h1><p>Placeholder.</p></div>")

@app.route("/beheer/hub")
def beheer_hub():
    return render_page("Beheer - Hub editor", "<div class='card'><h1>Hub editor</h1><p>Placeholder.</p></div>")

@app.route("/help")
def help_page():
    return render_page("Help", "<div class='card'><h1>Help</h1><p>Placeholder.</p></div>")

if __name__ == "__main__":
    app.run(debug=True)
