
# wsgi_prod.py — productie entrypoint zonder wijzigingen aan master.py
import logging
import time
from collections import OrderedDict
from typing import Tuple, Optional

from flask import request, g

# Haal de app-factory en register-functies uit master.py
from master import create_app as _create_app, register_beheer, register_tools

log = logging.getLogger("ctools")
access_log = logging.getLogger("access")
# access_log.setLevel(logging.WARNING)  # optioneel; we sturen zelf niveaus

# --- Eenvoudige LRU-cache om per client het laatste pad te onthouden ---
# Key = (remote_addr, user_agent), Value = (last_path, last_ts)
_MAX_CLIENTS = 512
_client_last: "OrderedDict[Tuple[str, str], Tuple[str, float]]" = OrderedDict()

def _client_key() -> Tuple[str, str]:
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "-"
    ua = request.headers.get("User-Agent", "-")
    return (ip, ua)

def _touch_client_last(path: str) -> bool:
    """
    Return True als dit een 'paginaswitch' is t.o.v. vorige request van dezelfde client.
    Houdt een beperkte LRU bij om geheugen te sparen.
    """
    now = time.time()
    k = _client_key()
    prev = _client_last.pop(k, None)  # pop om straks opnieuw te plaatsen (LRU)
    switched = prev is None or prev[0] != path
    # zet terug als meest recent
    _client_last[k] = (path, now)
    # LRU begrenzen
    while len(_client_last) > _MAX_CLIENTS:
        _client_last.popitem(last=False)
    return switched

def _page_name_from_request() -> str:
    """
    Probeer een leesbare paginanaam te geven. Valt terug op request.path.
    Pas deze mapping aan als je meer 'mooie namen' wil.
    """
    # Eerst proberen op endpoint (function name)
    ep = (request.endpoint or "").strip()
    if ep:
        # maak iets netter: underscores naar spaties
        friendly = ep.replace("_", " ").strip().title()
        # uitzonderingen
        if friendly.lower() in ("home",):
            return "Home"
        # als het op beheer pages lijkt
        if "beheer" in friendly.lower():
            return f"Beheer · {friendly}"
        return friendly

    # Dan specifieke paden die je hebt
    path = request.path or "/"
    if path == "/":
        return "Home"
    if path.startswith("/jwt"):
        return "JWT UI"
    if path.startswith("/voica1"):
        return "Voica1"
    if path.startswith("/beheer/tools"):
        return "Beheer · Tools"
    if path.startswith("/beheer/config"):
        return "Beheer · Config"
    if path.startswith("/beheer/theme"):
        return "Beheer · Theme"
    if path.startswith("/beheer/logs"):
        return "Beheer · Logs"
    if path.startswith("/beheer/hub"):
        return "Beheer · Hub"

    # fallback: pad zelf
    return path

def create_app():
    """
    Entry-point voor: waitress-serve --call wsgi_prod:create_app
    - bouwt de Flask app via master.create_app()
    - registreert beheer- en toolroutes (zoals main() normaal doet)
    - logging:
        * Errors (4xx/5xx) altijd loggen (WARNING/ERROR)
        * OK-regel alleen bij 'paginaswitch': "PAGE_NAME OK"
    """
    app = _create_app()

    # Registraties (zoals in main())
    try:
        register_beheer(app)
        log.info("Beheer routes registered (via wsgi_prod)")
    except Exception as exc:
        log.exception("FAILED registering beheer routes (via wsgi_prod): %s", exc)

    try:
        register_tools(app)
        log.info("Tools registered (via wsgi_prod)")
    except Exception as exc:
        log.exception("FAILED registering tools (via wsgi_prod): %s", exc)

    # Meet duur
    @app.before_request
    def _start_timer():
        g._t0 = time.perf_counter()

    @app.after_request
    def _log_request(resp):
        try:
            # Duur in ms (handig bij fouten)
            dt_ms = "-"
            if hasattr(g, "_t0"):
                dt_ms = f"{int((time.perf_counter() - g._t0) * 1000)}ms"

            status = int(resp.status_code)
            path = request.path or "/"

            # 1) Errors altijd loggen (jouw eerdere wens)
            if status >= 400:
                if status < 500:
                    access_log.warning("%s %s -> %s %s",
                                       request.method, path, status, dt_ms)
                else:
                    access_log.error("%s %s -> %s %s",
                                     request.method, path, status, dt_ms)
                return resp

            # 2) OK-regel alleen bij paginaswitch (nieuwe pagina)
            #    We beperken dit tot 'navigatie' (GET) en niet voor static-assets
            if request.method == "GET" and status < 400:
                if not path.startswith("/static/") and not path.startswith("/images/") and path != "/favicon.ico":
                    if _touch_client_last(path):
                        page_name = _page_name_from_request()
                        # Eén nette OK-regel
                        access_log.info("%s OK", page_name)

        except Exception:
            # logging mag de response nooit breken
            pass
        return resp

    return app
