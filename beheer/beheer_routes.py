from __future__ import annotations

from flask import Flask
from beheer.main_layout import render_page


def register_beheer_routes(app: Flask) -> None:
    """
    Registreert alle beheer-pagina’s.
    Elke pagina geeft enkel de PAGINA-NAAM door.
    main_layout bouwt automatisch:
      - <title>
      - header pill
      - branding (CyNiT Beheer | ...)
    """

    @app.get("/beheer/tools")
    def beheer_tools():
        return render_page(
            title="Tools Editor",
            content_html="""
            <div class="panel">
              <h2>Tools editor</h2>
              <p>Hier beheer je tools (hide/show, icon, naam, kleur).</p>
              <p><em>Stap A – komt hier.</em></p>
            </div>
            """
        )

    @app.get("/beheer/config")
    def beheer_config():
        return render_page(
            title="Config",
            content_html="""
            <div class="panel">
              <h2>Config</h2>
              <p>Beheer <code>settings.json</code> en andere centrale configuratie.</p>
            </div>
            """
        )

    @app.get("/beheer/theme")
    def beheer_theme():
        return render_page(
            title="Theme",
            content_html="""
            <div class="panel">
              <h2>Theme</h2>
              <p>Beheer kleuren, fonts en layout-instellingen.</p>
            </div>
            """
        )

    @app.get("/beheer/logs")
    def beheer_logs():
        return render_page(
            title="Logs",
            content_html="""
            <div class="panel">
              <h2>Logs</h2>
              <p>Bekijk runtime logs van CyNiT Hub en tools.</p>
            </div>
            """
        )

    @app.get("/beheer/hub")
    def beheer_hub():
        return render_page(
            title="Hub Editor",
            content_html="""
            <div class="panel">
              <h2>Hub Editor</h2>
              <p>Globale hub-instellingen en gedrag.</p>
            </div>
            """
        )
