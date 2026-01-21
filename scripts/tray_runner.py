from __future__ import annotations

import json
import os
import subprocess
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem
from win11toast import toast

# import preflight
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from preflight import PreflightConfig, ensure_env_and_deps  # noqa: E402


# =========================
# Project paths (relative, clean)
# =========================
PROJECT_DIR = Path(__file__).resolve().parents[1]  # CyNiT-Hub/
VENV_DIR = PROJECT_DIR / "venv"
REQ_DIR = PROJECT_DIR / "requirements"
REQ_ENTRY = REQ_DIR / "all.in"

RUNTIME_DIR = PROJECT_DIR / "runtime"
STAMP_FILE = RUNTIME_DIR / ".deps_stamp"

LOGS_DIR = PROJECT_DIR / "logs"
TRAY_LOG = LOGS_DIR / "master_tray.log"

SCRIPT = PROJECT_DIR / "master.py"
HUB_URL = "https://localhost:5000"  # pas aan indien jouw master op andere poort draait

ICON_OK_PATH = PROJECT_DIR / "static" / "images" / "logo.png"
ICON_ERR_PATH = PROJECT_DIR / "static" / "images" / "logo_crash.png"

# Heartbeat file for beheer watchdog detection
HEARTBEAT_FILE = RUNTIME_DIR / "watchdog_heartbeat.json"
HEARTBEAT_INTERVAL_SEC = 5

# Tray uptime
TRAY_STARTED_TS = time.time()

_proc = None
_proc_lock = Lock()


# =========================
# Logging / notify
# =========================
def log(msg: str):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(TRAY_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def notify(title: str, message: str):
    try:
        toast(title, message)
    except Exception as e:
        log(f"[WARN] toast failed: {e}")


# =========================
# Heartbeat (watchdog status)
# =========================
def _fmt_uptime(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def write_heartbeat(status: str, extra: dict | None = None):
    """
    Writes runtime/watchdog_heartbeat.json so beheer can detect if tray_runner is alive.
    status: starting | running | crashed | stopped
    """
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        uptime_sec = int(time.time() - TRAY_STARTED_TS)

        payload = {
            "ts": time.time(),
            "status": status,
            "pid": os.getpid(),
            "uptime_sec": uptime_sec,
        }
        if extra and isinstance(extra, dict):
            payload.update(extra)

        HEARTBEAT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"[WARN] heartbeat write failed: {e}")


def tray_uptime_text() -> str:
    """
    Dynamic text in right-click menu.
    pystray supports callables for MenuItem text.
    """
    up = int(time.time() - TRAY_STARTED_TS)
    return f"Uptime tray: {_fmt_uptime(up)}"


# =========================
# Icons
# =========================
def fallback_icon() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 56, 56), fill=(0, 250, 0, 255))
    return img


def safe_load_image(path: Path, fallback: Image.Image) -> Image.Image:
    try:
        if path.exists():
            return Image.open(path)
    except Exception as e:
        log(f"[WARN] kon image niet laden {path}: {e}")
    return fallback


def make_red_icon(src_path: Path, dest_path: Path):
    img = Image.open(src_path).convert("RGBA")
    *_, a = img.split()
    red_img = Image.new("RGBA", img.size, (255, 60, 60, 255))
    red_img.putalpha(a)
    red_img.save(dest_path)


# =========================
# Master process control
# =========================
def start_master(venv_pythonw: Path) -> subprocess.Popen:
    if not venv_pythonw.exists():
        raise FileNotFoundError(f"pythonw.exe niet gevonden: {venv_pythonw}")
    if not SCRIPT.exists():
        raise FileNotFoundError(f"master.py niet gevonden: {SCRIPT}")

    return subprocess.Popen([str(venv_pythonw), str(SCRIPT)], cwd=str(PROJECT_DIR))


def stop_master():
    global _proc
    with _proc_lock:
        p = _proc

    if not p:
        log("stop_master: geen actief proces")
        return

    try:
        if p.poll() is None:
            log("stop_master: terminate()")
            p.terminate()
            for _ in range(30):
                if p.poll() is not None:
                    break
                time.sleep(0.1)
            if p.poll() is None:
                log("stop_master: kill()")
                p.kill()
    except Exception as e:
        log(f"[WARN] stop_master failed: {e}")


# =========================
# Tray callbacks
# =========================
def on_open(icon, item):
    log("CLICK: Open Hub")
    notify("CyNiT-Hub", "Hub openen")
    webbrowser.open(HUB_URL)


def on_ping(icon, item):
    log("CLICK: Ping")
    notify("CyNiT-Hub", "Ping OK (tray werkt)")
    write_heartbeat("running", {"note": "manual ping"})


def on_restart(icon, item):
    log("CLICK: Herstart")
    notify("CyNiT-Hub", "Herstart gevraagd")
    write_heartbeat("starting", {"reason": "tray menu restart"})
    stop_master()  # watchdog herstart automatisch


def on_quit(icon, item):
    log("CLICK: Afsluiten")
    notify("CyNiT-Hub", "Afsluiten")
    write_heartbeat("stopped", {"reason": "tray quit"})
    stop_master()
    icon.stop()
    os._exit(0)


# =========================
# Watchdog
# =========================
def run_watchdog(icon: Icon):
    global _proc

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log("Tray runner gestart")
    notify("CyNiT-Hub", "Tray runner gestart")

    write_heartbeat("starting", {"phase": "preflight"})

    # 1) Preflight: venv + deps
    cfg = PreflightConfig(
        project_dir=PROJECT_DIR,
        venv_dir=VENV_DIR,
        requirements_dir=REQ_DIR,
        requirements_entry=REQ_ENTRY,
        logs_dir=LOGS_DIR,
        stamp_file=STAMP_FILE,
    )

    REQUIRED_IMPORTS = {
        # hub
        "flask": "flask",
        "jinja2": "jinja2",
        "cryptography": "cryptography",
        "pyjwt": "jwt",
        "openpyxl": "openpyxl",
        "markdown": "markdown",
        "pyyaml": "yaml",
        "pyzipper": "pyzipper",
        # tray
        "pillow": "PIL",
        "pystray": "pystray",
        "win11toast": "win11toast",
        # docs
        "reportlab": "reportlab",
        "pdfkit": "pdfkit",
    }

    try:
        venv_py = ensure_env_and_deps(cfg, REQUIRED_IMPORTS)
        log(f"Preflight OK: {venv_py}")
        write_heartbeat("starting", {"phase": "preflight_ok"})
    except Exception as e:
        log(f"[FATAL] Preflight failed: {e}")
        notify("CyNiT-Hub", f"Preflight faalde: {e}")
        write_heartbeat("crashed", {"phase": "preflight_failed", "error": str(e)})
        return

    venv_pythonw = (VENV_DIR / "Scripts" / "pythonw.exe") if os.name == "nt" else venv_py

    # 2) crash icoon genereren indien nodig
    if ICON_OK_PATH.exists() and not ICON_ERR_PATH.exists():
        try:
            make_red_icon(ICON_OK_PATH, ICON_ERR_PATH)
            log("Crash-icoon gegenereerd")
        except Exception as e:
            log(f"[WARN] crash-icoon maken faalde: {e}")

    hb_stop = {"stop": False}

    def heartbeat_loop():
        while not hb_stop["stop"]:
            write_heartbeat("running", {"master_running": True})
            # sleep in small chunks so stop reacts quickly
            for _ in range(int(HEARTBEAT_INTERVAL_SEC * 10)):
                if hb_stop["stop"]:
                    break
                time.sleep(0.1)

    # 3) run loop
    while True:
        try:
            write_heartbeat("starting", {"phase": "starting_master"})
            log("Start master.py")

            with _proc_lock:
                _proc = start_master(venv_pythonw)

            hb_stop["stop"] = False
            Thread(target=heartbeat_loop, daemon=True).start()

            icon.icon = safe_load_image(ICON_OK_PATH, fallback_icon())
            icon.title = "CyNiT-Hub draait"
            icon.visible = True

            rc = _proc.wait()

            hb_stop["stop"] = True
            write_heartbeat("starting", {"phase": "master_stopped", "returncode": rc})
            log(f"master.py gestopt (returncode={rc})")

            icon.icon = safe_load_image(ICON_ERR_PATH, fallback_icon())
            icon.title = "CyNiT-Hub gestopt – herstart volgt"
            notify("CyNiT-Hub", "master.py is gestopt en wordt herstart")

            time.sleep(3)

        except Exception as e:
            hb_stop["stop"] = True
            log(f"[ERROR] watchdog exception: {e}")
            notify("CyNiT-Hub", f"Tray error: {e}")
            write_heartbeat("crashed", {"phase": "watchdog_exception", "error": str(e)})
            time.sleep(3)


# =========================
# Main
# =========================
def main():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log("main() gestart")

    image_ok = safe_load_image(ICON_OK_PATH, fallback_icon())

    # Uptime wordt getoond in right-click menu via callable text.
    menu = Menu(
        MenuItem(tray_uptime_text, None, enabled=False),  # <-- uptime regel
        Menu.SEPARATOR,
        MenuItem("Open Hub", on_open, default=True),
        MenuItem("Ping", on_ping),
        MenuItem("Herstart CyNiT-Hub", on_restart),
        MenuItem("Afsluiten", on_quit),
    )

    icon = Icon("CyNiT-Hub", image_ok, "CyNiT-Hub", menu)
    Thread(target=run_watchdog, args=(icon,), daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()
