from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import List, Tuple

BASE_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = BASE_DIR / "runtime"
HEARTBEAT_FILE = RUNTIME_DIR / "watchdog_heartbeat.json"


# -------------------------
# Watchdog detection
# -------------------------
def watchdog_status(max_age_seconds: int = 15) -> Tuple[bool, str]:
    """
    Returns (is_active, message)
    Active if heartbeat file exists and timestamp is recent.
    """
    try:
        if not HEARTBEAT_FILE.exists():
            return (False, "geen heartbeat file")

        data = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
        ts = float(data.get("ts", 0))
        age = time.time() - ts
        if age <= max_age_seconds:
            return (True, f"actief ({int(age)}s oud)")
        return (False, f"te oud ({int(age)}s oud)")
    except Exception as exc:
        return (False, f"fout: {exc}")


# -------------------------
# Cache clear
# -------------------------
CACHE_DIRS = [
    BASE_DIR / "tmp",
    BASE_DIR / "static" / "css",
    BASE_DIR / "static" / "js",
]


def clear_pycache(root: Path) -> int:
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
    removed: List[str] = []

    for d in CACHE_DIRS:
        if not d.exists():
            continue

        # Laat main.css / main.js gerust staan als je wilt; nu: alles in die folders
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

    n = clear_pycache(BASE_DIR)
    removed.append(f"__pycache__/*.pyc removed: {n}")

    return removed


# -------------------------
# Restart request
# -------------------------
def request_restart():
    """
    In tray/watchdog mode: gewoon master laten stoppen.
    Tray runner herstart.
    """
    os._exit(0)
