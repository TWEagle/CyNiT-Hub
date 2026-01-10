from __future__ import annotations

def register_web_routes(app):
    @app.get("/voica1")
    def voica1_home():
        from beheer.main_layout import render_page

        content = """
        <div class="panel">
          <h2>VOICA1</h2>
          <p>✅ Dit is de lege schil (baseline).</p>
          <p><a class="btn" href="/">Terug naar Home</a></p>
        </div>
        """
        # ✅ BELANGRIJK: title is nu de PAGINA-NAAM
        return render_page(title="VOICA1", content_html=content)
