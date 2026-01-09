from flask import Flask, render_template_string, send_from_directory

app = Flask(
    __name__,
    static_folder="static",
    static_url_path="/static"
)

# ===== IMAGES ROUTE =====
@app.route("/images/<path:filename>")
def images(filename):
    return send_from_directory("images", filename)

# ===== BASE TEMPLATE =====
BASE_HTML = """
<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>

  <!-- Favicon -->
  <link rel="icon" href="/images/logo.ico">

  <!-- Font Awesome -->
  <link
    rel="stylesheet"
    href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css"
    crossorigin="anonymous"
  />

  <!-- CyNiT CSS -->
  <link rel="stylesheet" href="/static/cynit.css">
</head>

<body class="page">

<header class="header">

  <!-- LEFT: WAFFLE -->
  <div class="menu-wrapper">
    <button class="icon-btn" id="toolsBtn" title="Tools">
      <i class="fa-solid fa-waffle"></i>
    </button>

    <div class="dropdown" id="toolsMenu">
      <a href="/">🏠 Home</a>
      <a href="/voica1">🔐 VOICA1</a>
      <a href="#">🧪 Andere tool</a>
    </div>
  </div>

  <!-- CENTER: LOGO + TITLE -->
  <a href="/" class="brand">
    <img src="/images/logo.png?v=1" alt="CyNiT logo" class="brand-logo">
    <span class="brand-title">{{ title }}</span>
  </a>

  <!-- RIGHT: HAMBURGER -->
  <button class="icon-btn" title="Beheer">
    <i class="fa-solid fa-bars"></i>
  </button>

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

# ===== ROUTES =====
@app.route("/")
def home():
    return render_template_string(
        BASE_HTML,
        title="CyNiT Tools",
        content="""
        <div class="card">
          <h1>Home</h1>
          <p>Wafel-menu werkt nu.</p>
          <a class="btn" href="/voica1">Open VOICA1</a>
        </div>
        """
    )

@app.route("/voica1")
def voica1():
    return render_template_string(
        BASE_HTML,
        title="VOICA1 Certificaten",
        content="""
        <div class="card">
          <h1>VOICA1</h1>
          <p>VOICA1 tool placeholder.</p>
          <a class="btn" href="/">Terug naar home</a>
        </div>
        """
    )

if __name__ == "__main__":
    app.run(debug=True)
