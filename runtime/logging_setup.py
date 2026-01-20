from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Dict, Iterable, Optional


class OnlyErrors(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.ERROR


class NoErrors(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.ERROR


class ToolRouter(logging.Handler):
    """
    Router die logs van tools wegschrijft naar logs/tools/<tool>.log
    Herkent tool records via:
      - record.name == <tool_id>  (bv "voica1")
      - record.name startswith "tools.<tool_id>" (bv "tools.voica1")
    """

    def __init__(self, logs_dir: Path, tool_ids: Iterable[str], level: int = logging.INFO):
        super().__init__(level=level)
        self.logs_dir = logs_dir
        self.tools_dir = logs_dir / "tools"
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.tool_ids = {str(x).strip() for x in tool_ids if str(x).strip()}
        self._handlers: Dict[str, TimedRotatingFileHandler] = {}

        self._fmt = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")

    def _tool_from_record(self, record: logging.LogRecord) -> Optional[str]:
        name = (record.name or "").strip()
        if not name:
            return None

        # exact match (voica1, cert_viewer, token2dcb, ...)
        if name in self.tool_ids:
            return name

        # module style: tools.<id>...
        if name.startswith("tools."):
            parts = name.split(".")
            if len(parts) >= 2 and parts[1] in self.tool_ids:
                return parts[1]

        return None

    def _get_handler(self, tool: str) -> TimedRotatingFileHandler:
        h = self._handlers.get(tool)
        if h:
            return h

        fp = self.tools_dir / f"{tool}.log"
        h = TimedRotatingFileHandler(
            fp,
            when="midnight",
            interval=1,
            backupCount=7,        # 1 week
            encoding="utf-8",
            delay=True,
        )
        h.setLevel(logging.DEBUG)
        h.setFormatter(self._fmt)
        self._handlers[tool] = h
        return h

    def emit(self, record: logging.LogRecord) -> None:
        try:
            tool = self._tool_from_record(record)
            if not tool:
                return
            h = self._get_handler(tool)
            h.emit(record)
        except Exception:
            # nooit logging laten crashen
            return


def _mk_daily_handler(path: Path, level: int) -> TimedRotatingFileHandler:
    h = TimedRotatingFileHandler(
        path,
        when="midnight",
        interval=1,
        backupCount=7,     # 1 week
        encoding="utf-8",
        delay=True,
    )
    h.setLevel(level)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s"))
    return h


def setup_logging(*, logs_dir: Path, tool_ids: Iterable[str]) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Root logger: vangt alles (ook 3rd party) en stuurt door naar handlers
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # voorkom dubbele handlers bij re-runs
    if getattr(root, "_cynit_configured", False):
        return
    setattr(root, "_cynit_configured", True)

    # --- basis handlers ---
    hub_h = _mk_daily_handler(logs_dir / "hub.log", logging.INFO)
    hub_h.addFilter(NoErrors())

    err_h = _mk_daily_handler(logs_dir / "errors.log", logging.ERROR)
    err_h.addFilter(OnlyErrors())

    access_h = _mk_daily_handler(logs_dir / "access.log", logging.INFO)
    clicks_h = _mk_daily_handler(logs_dir / "clicks.log", logging.INFO)

    # --- tool router handler ---
    tool_router = ToolRouter(logs_dir, tool_ids=tool_ids, level=logging.DEBUG)

    # Attach to root
    root.addHandler(hub_h)
    root.addHandler(err_h)
    root.addHandler(tool_router)

    # “named” loggers voor access/clicks (apart bestand)
    access_logger = logging.getLogger("hub.access")
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False
    access_logger.addHandler(access_h)

    clicks_logger = logging.getLogger("hub.clicks")
    clicks_logger.setLevel(logging.INFO)
    clicks_logger.propagate = False
    clicks_logger.addHandler(clicks_h)

    # Optioneel: console tijdens dev (kan je uitzetten)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s"))
    root.addHandler(console)

    logging.getLogger("hub").info("Logging initialized -> %s OK", str(logs_dir))
