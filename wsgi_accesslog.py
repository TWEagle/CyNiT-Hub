
# wsgi_accesslog.py
import time
import logging
from typing import Callable, Iterable, Tuple
from master import create_app

# Basis logging-config (als je 'm al zet elders, blijft dit onschadelijk)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s"
)
access_log = logging.getLogger("access")

def _wrap_with_access_log(app) -> Callable:
    def middleware(environ, start_response):
        t0 = time.perf_counter()
        method = environ.get("REQUEST_METHOD", "-")
        path   = environ.get("PATH_INFO", "-")
        ua     = environ.get("HTTP_USER_AGENT", "-")
        status_headers: Tuple[str, Iterable[Tuple[str, str]]] = ("", [])

        def _sr(status, headers, *args, **kwargs):
            nonlocal status_headers
            status_headers = (status, headers)
            return start_response(status, headers, *args, **kwargs)

        try:
            result = app(environ, _sr)
            return result
        finally:
            try:
                dt_ms = int((time.perf_counter() - t0) * 1000)
                status_code = status_headers[0].split(" ", 1)[0] if status_headers[0] else "-"
                access_log.info("%s %s -> %s %dms UA=%s", method, path, status_code, dt_ms, ua)
            except Exception:
                # logging mag nooit de response breken
                pass

    return middleware

def create_app():
    """Factory die jouw Flask app ophaalt en wrapt met access logging."""
    app = create_app.__wrapped_app if hasattr(create_app, "__wrapped_app") else None
    base_app = globals().get("_base_app")
    if base_app is None:
        # haal de echte Flask app uit master.create_app()
        base_app = _get_base_app()
        globals()["_base_app"] = base_app
    return _wrap_with_access_log(base_app)

def _get_base_app():
    # import hier om cirkels te vermijden
    from master import create_app as _factory
    return _factory()
