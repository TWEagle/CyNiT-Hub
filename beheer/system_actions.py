from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List

BASE_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = BASE_DIR / "runtime"
HEARTBEAT_FILE = RUNTIME_DIR / "watchdog_heartbeat.json"

# Welke folders wil je als "cache" beschouwen?
CACHE_DIRS = [
    BASE_DIR / "tmp",
    BASE_DIR / "static" / "css",
    BASE_DIR / "static" / "js",
]


# -------------------------
# Watchdog detection
# -------------------------
def watchdog_status(max_age_seconds: int = 15) -> Dict[str, str | bool | int]:
    """
    Returns structured watchdog status info.

    {
      ok: bool,
      status: running|starting|crashed|stopped|stale|unknown|error,
      age: seconds,
      emoji: str,
      label: str,
      detail: str,
      uptime_sec: int (if present),
      tray_pid: int (if present)
    }
    """
    if not HEARTBEAT_FILE.exists():
        return {
            "ok": False,
            "status": "unknown",
            "age": -1,
            "emoji": "⚫",
            "label": "Geen watchdog",
            "detail": "heartbeat file ontbreekt",
        }

    try:
        data = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
        ts = float(data.get("ts", 0))
        status = str(data.get("status", "unknown")).lower()
        age = int(time.time() - ts)

        # extras (optioneel)
        uptime_sec = int(float(data.get("uptime_sec", 0) or 0))
        tray_pid = int(data.get("pid", 0) or 0)

        stale = age > max_age_seconds
        if stale:
            out: Dict[str, str | bool | int] = {
                "ok": False,
                "status": "stale",
                "age": age,
                "emoji": "🔴",
                "label": "Watchdog verlopen",
                "detail": f"laatste heartbeat {age}s geleden",
            }
            if uptime_sec:
                out["uptime_sec"] = uptime_sec
            if tray_pid:
                out["tray_pid"] = tray_pid
            return out

        def pack(ok: bool, st: str, emoji: str, label: str, detail: str) -> Dict[str, str | bool | int]:
            out2: Dict[str, str | bool | int] = {
                "ok": ok,
                "status": st,
                "age": age,
                "emoji": emoji,
                "label": label,
                "detail": detail,
            }
            if uptime_sec:
                out2["uptime_sec"] = uptime_sec
            if tray_pid:
                out2["tray_pid"] = tray_pid
            return out2

        if status == "running":
            return pack(True, "running", "🟢", "Watchdog actief", f"running • {age}s oud")
        if status == "starting":
            return pack(True, "starting", "🟡", "Watchdog start", f"starting • {age}s oud")
        if status == "crashed":
            return pack(False, "crashed", "🔴", "Watchdog crash", f"crashed • {age}s oud")
        if status == "stopped":
            return pack(False, "stopped", "⚪", "Watchdog gestopt", f"stopped • {age}s oud")

        return pack(False, status, "⚠️", "Onbekende status", f"{status} • {age}s oud")

    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "age": -1,
            "emoji": "❌",
            "label": "Watchdog fout",
            "detail": str(exc),
        }


# -------------------------
# Cache clearing
# -------------------------
def _clear_pycache(root: Path) -> int:
    removed = 0
    for p in root.rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)
        removed += 1
    for p in root.rglob("*.pyc"):
        try:
            p.unlink()
            removed += 1
        except Exception:
            pass
    return removed


def clear_cache() -> List[str]:
    """
    Best effort cleanup: tmp + static/css + static/js + __pycache__/pyc
    (Pas aan als je main.css/js niet wil verwijderen.)
    """
    removed: List[str] = []

    for d in CACHE_DIRS:
        if not d.exists():
            continue

        for item in d.iterdir():
            try:
                if item.is_file():
                    item.unlink(missing_ok=True)
                    removed.append(str(item))
                elif item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                    removed.append(str(item))
            except Exception:
                pass

    n = _clear_pycache(BASE_DIR)
    removed.append(f"__pycache__/*.pyc removed: {n}")

    return removed


# -------------------------
# Restart request
# -------------------------
def request_restart() -> None:
    """
    In watchdog mode: master stoppen -> tray_runner herstart.
    """
    os._exit(0)
