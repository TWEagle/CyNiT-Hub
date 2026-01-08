from flask import Flask, render_template_string, url_for, send_from_directory

app = Flask(
    __name__,
    static_folder="static",
    static_url_path=""
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
  <title>{{ title }}</title>

  <!-- CSS -->
  <link rel="stylesheet" href="{{ url_for('static', filename='cynit.css') }}">

  <!-- Favicon -->
  <link rel="icon" href="/images/logo.ico">
</head>

<body class="app-body">

<header class="header">
  <a href="/" class="brand">
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
        <h1>Home</h1>
        <p>Baseline werkt: header + footer + logo + title switching.</p>
        <a class="btn" href="/voica1">Open VOICA1</a>
        """
    )

@app.route("/voica1")
def voica1():
    return render_template_string(
        BASE_HTML,
        title="VOICA1 Certificaten",
        content="""
        <h1>VOICA1</h1>
        <p>VOICA1 tool placeholder.</p>
        <a class="btn" href="/">Terug naar home</a>
        """
    )

if __name__ == "__main__":
    app.run(debug=True)
