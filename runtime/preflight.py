from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class PreflightConfig:
    project_dir: Path
    venv_dir: Path
    requirements_dir: Path
    requirements_entry: Path  # bv requirements/all.in
    logs_dir: Path
    stamp_file: Path  # runtime/.deps_stamp


def _run(cmd: List[str], cwd: Path | None = None) -> Tuple[int, str]:
    """Run command and return (returncode, combined_output)."""
    p = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, p.stdout


def _log(cfg: PreflightConfig, msg: str) -> None:
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = cfg.logs_dir / "preflight.log"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(msg.rstrip() + "\n")


def _hash_requirements_tree(req_dir: Path) -> str:
    """
    Hash contents of requirements/*.in to detect changes.
    """
    h = hashlib.sha256()
    files = sorted(req_dir.glob("*.in"))
    for fp in files:
        h.update(fp.name.encode("utf-8"))
        h.update(b"\n")
        h.update(fp.read_bytes())
        h.update(b"\n---\n")
    return h.hexdigest()


def _venv_python(cfg: PreflightConfig) -> Path:
    if os.name == "nt":
        return cfg.venv_dir / "Scripts" / "python.exe"
    return cfg.venv_dir / "bin" / "python"


def _ensure_venv(cfg: PreflightConfig) -> Path:
    py = _venv_python(cfg)
    if py.exists():
        _log(cfg, "[OK] venv bestaat")
        return py

    _log(cfg, "[INFO] venv ontbreekt -> aanmaken")
    code, out = _run([sys.executable, "-m", "venv", str(cfg.venv_dir)], cwd=cfg.project_dir)
    _log(cfg, out)
    if code != 0 or not py.exists():
        raise RuntimeError("Kon venv niet aanmaken. Zie logs/preflight.log")
    return py


def _pip_install_requirements(cfg: PreflightConfig, venv_py: Path) -> None:
    _log(cfg, f"[INFO] pip install -r {cfg.requirements_entry}")
    code, out = _run([str(venv_py), "-m", "pip", "install", "-r", str(cfg.requirements_entry)], cwd=cfg.project_dir)
    _log(cfg, out)
    if code != 0:
        raise RuntimeError("pip install faalde. Zie logs/preflight.log")


def _missing_imports(venv_py: Path, required: Dict[str, str], cfg: PreflightConfig) -> List[str]:
    """
    required: {pip_name: import_name}
    Returns list of pip_names missing.
    """
    missing: List[str] = []
    for pip_name, mod in required.items():
        code, _ = _run([str(venv_py), "-c", f"import {mod}"])
        if code != 0:
            missing.append(pip_name)
    if missing:
        _log(cfg, f"[INFO] missing packages (import check): {missing}")
    else:
        _log(cfg, "[OK] import-check: alles aanwezig")
    return missing


def ensure_env_and_deps(
    cfg: PreflightConfig,
    required_imports: Dict[str, str],
    *,
    force_install: bool = False,
) -> Path:
    """
    Ensures venv exists and deps are installed.
    Strategy:
    - Create venv if missing
    - If requirements changed OR force_install: pip install -r requirements/all.in
    - Else: import-check; if missing -> pip install -r requirements/all.in (robust)
    Returns venv python path.
    """
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    cfg.requirements_dir.mkdir(parents=True, exist_ok=True)
    cfg.stamp_file.parent.mkdir(parents=True, exist_ok=True)

    venv_py = _ensure_venv(cfg)

    # Always ensure pip itself is usable (no hard fail if upgrade blocked)
    _log(cfg, "[INFO] pip version check")
    _run([str(venv_py), "-m", "pip", "--version"])

    req_hash = _hash_requirements_tree(cfg.requirements_dir)
    old_hash = cfg.stamp_file.read_text(encoding="utf-8").strip() if cfg.stamp_file.exists() else ""

    needs_full_install = force_install or (req_hash != old_hash)

    if needs_full_install:
        _log(cfg, "[INFO] requirements gewijzigd (of force) -> full install")
        _pip_install_requirements(cfg, venv_py)
        cfg.stamp_file.write_text(req_hash, encoding="utf-8")
        return venv_py

    # quick import-check
    missing = _missing_imports(venv_py, required_imports, cfg)
    if missing:
        _log(cfg, "[INFO] ontbrekende deps -> full install (all.in)")
        _pip_install_requirements(cfg, venv_py)
        cfg.stamp_file.write_text(req_hash, encoding="utf-8")

    return venv_py
