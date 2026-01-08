from __future__ import annotations
from flask import g


def register_web_routes(app):
    @app.get("/voica1")
    def voica1_home():
        from beheer.cynit_layout import render_page

        content = """
        <div class="wrap">
          <h2>VOICA1</h2>
          <p>✅ Dit is de lege schil (baseline).</p>
          <p><a class="btn" href="/">Terug naar Home</a></p>
        </div>
        """
        return render_page(title=g.get("page_title", "VOICA1 Certificaten"), content_html=content)
