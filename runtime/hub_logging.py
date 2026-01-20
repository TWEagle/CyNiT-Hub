#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
runtime/hub_logging.py — centrale logging voor CyNiT-Hub

- logs/ folder auto-aanmaken
- 4 vaste logfiles: hub.log, errors.log, requests.log, clicks.log
- per tool: logs/tools/<toolid>.log (1 per tool)
- rotatie: dagelijks + 7 dagen bewaren
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Iterable

_TOOL_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_tool_id(tool_id: str) -> str:
    tool_id = (tool_id or "tool").strip()
    tool_id = _TOOL_SAFE.sub("_", tool_id)
    return tool_id[:80] or "tool"


def _make_daily_handler(path: Path, level: int, fmt: str, keep_days: int = 7) -> TimedRotatingFileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    h = TimedRotatingFileHandler(
        filename=str(path),
        when="midnight",      # rotate at local midnight
        interval=1,
        backupCount=keep_days,  # ✅ 7 dagen bewaren
        encoding="utf-8",
        delay=True,
        utc=False,
    )
    h.setLevel(level)
    h.setFormatter(logging.Formatter(fmt))
    return h


@dataclass(frozen=True)
class HubLoggers:
    hub: logging.Logger
    errors: logging.Logger
    requests: logging.Logger
    clicks: logging.Logger


def setup_logging(base_dir: Path, tool_ids: Iterable[str]) -> HubLoggers:
    logs_dir = base_dir / "logs"
    tools_dir = logs_dir / "tools"
    logs_dir.mkdir(parents=True, exist_ok=True)
    tools_dir.mkdir(parents=True, exist_ok=True)

    fmt_main = "%(asctime)s %(levelname)s:%(name)s:%(message)s"
    fmt_req = "%(asctime)s %(levelname)s:%(message)s"
    fmt_click = "%(asctime)s %(levelname)s:%(message)s"

    root = logging.getLogger()

    # Avoid double-config
    if getattr(root, "_cynit_configured", False):
        return HubLoggers(
            hub=logging.getLogger("hub"),
            errors=logging.getLogger("hub.errors"),
            requests=logging.getLogger("hub.requests"),
            clicks=logging.getLogger("hub.clicks"),
        )

    # Remove any existing handlers (basicConfig leftovers)
    for h in list(root.handlers):
        root.removeHandler(h)

    # ✅ “alles loggen”
    root.setLevel(logging.DEBUG)

    # Root handlers -> hub.log + errors.log
    hub_handler = _make_daily_handler(logs_dir / "hub.log", logging.DEBUG, fmt_main, keep_days=7)
    err_handler = _make_daily_handler(logs_dir / "errors.log", logging.ERROR, fmt_main, keep_days=7)
    root.addHandler(hub_handler)
    root.addHandler(err_handler)

    # Dedicated loggers (requests/clicks) -> apart bestand, geen propagate
    requests_log = logging.getLogger("hub.requests")
    requests_log.setLevel(logging.INFO)
    requests_log.propagate = False
    requests_log.addHandler(_make_daily_handler(logs_dir / "requests.log", logging.INFO, fmt_req, keep_days=7))

    clicks_log = logging.getLogger("hub.clicks")
    clicks_log.setLevel(logging.INFO)
    clicks_log.propagate = False
    clicks_log.addHandler(_make_daily_handler(logs_dir / "clicks.log", logging.INFO, fmt_click, keep_days=7))

    # Named loggers
    hub_log = logging.getLogger("hub")
    hub_log.setLevel(logging.DEBUG)
    hub_log.propagate = True

    errors_log = logging.getLogger("hub.errors")
    errors_log.setLevel(logging.ERROR)
    errors_log.propagate = True

    # Per-tool handlers (zelfde retentie)
    for tid_raw in tool_ids:
        if not tid_raw:
            continue
        tid_safe = _safe_tool_id(str(tid_raw))
        tool_file = tools_dir / f"{tid_safe}.log"
        tool_handler = _make_daily_handler(tool_file, logging.DEBUG, fmt_main, keep_days=7)

        # hang handler aan mogelijke logger-namen
        for lname in {
            str(tid_raw),
            tid_safe,
            f"tools.{tid_raw}",
            f"tools.{tid_safe}",
            f"tool_{tid_safe}",
        }:
            lg = logging.getLogger(lname)
            lg.setLevel(logging.DEBUG)
            lg.addHandler(tool_handler)
            lg.propagate = True  # ook in hub.log + errors.log

    # Werkzeug minder noisy maar nog steeds nuttig
    logging.getLogger("werkzeug").setLevel(logging.INFO)

    # Console (handig)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(fmt_main))
    root.addHandler(console)

    setattr(root, "_cynit_configured", True)
    hub_log.info("Logging initialized -> %s (keep_days=7) OK", str(logs_dir))
    return HubLoggers(hub=hub_log, errors=errors_log, requests=requests_log, clicks=clicks_log)
