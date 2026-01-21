# tools/createcert.py
# !/usr/bin/env python3
"""
CreateCert - Key + CSR maker voor CyNiT-Hub & Standalone.

Features:
- Engine: python (cryptography) of openssl (zoals voica1)
- Key type: RSA (default 4096) of ECC secp384r1
- Hash: SHA-384 (vast)
- Subject verplicht: C, O, CN, email
- SAN optioneel: meerdere regels (DNS/IP/email)
- Output map: <root_base_dir>\YYYY\MM\DD (maakt folders aan)
- Output files:
    <base>.key.pem   private key PEM
    <base>.csr       CSR PEM
    <base>.b64       CSR DER -> base64 single-line
    <base-hyphen>.crt (verwacht ontvangen cert)
    <base>.p12       export PKCS#12 (AES-256-CBC) + auto password
    <base>.pem       combined PEM (cert + key)

Standalone:
- python tools/createcert.py -> http://127.0.0.1:5011/createcert
"""

from __future__ import annotations

import base64
import ipaddress
import json
import os
import secrets
import string
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, request, send_from_directory

from beheer.main_layout import render_page as hub_render_page


# =========================
# Project root + config paths (zelfde stijl als voica1)
# =========================
def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    for _ in range(4):
        if (p / "config").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parent


PROJECT_ROOT = _find_project_root()
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_PATH = CONFIG_DIR / "creacert_settings.json"


# =========================
# Defaults
# =========================
DEFAULTS: Dict[str, Any] = {
    "root_base_dir": r"C:\Users\lemmenmf\OneDrive - Vlaamse overheid - Office 365\DCBaaS\VOICA1\Certificaten",
    "default_engine": "python",  # python|openssl
    "default_key_type": "RSA",  # RSA|ECC
    "default_key_size": 4096,
    "ecc_curve": "secp384r1",
    "hash_alg": "sha384",
    "openssl_bin": "openssl",
    "openssl_conf": None,
    "pass_length": 24,
    "default_country": "BE",
    "countries": [
        {"code": "BE", "name": "Belgium"},
        {"code": "NL", "name": "Netherlands"},
        {"code": "LU", "name": "Luxembourg"},
    ],
    "ui": {
        "brand": "CreateCert",
        "accent": "#00f700",
    },
}


# =========================
# Config load/apply
# =========================
CFG: Dict[str, Any] = dict(DEFAULTS)


def _safe_json_load(path: Path, fallback: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if not path.exists():
            return dict(fallback)
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return dict(fallback)
        data = json.loads(raw)
        if isinstance(data, dict):
            merged = dict(fallback)
            merged.update(data)
            return merged
    except Exception:
        pass
    return dict(fallback)


def _normalize_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(cfg or {})
    cfg.setdefault("ui", {})
    if not isinstance(cfg["ui"], dict):
        cfg["ui"] = {}

    # engine
    eng = str(cfg.get("default_engine") or "python").strip().lower()
    if eng not in ("python", "openssl"):
        eng = "python"
    cfg["default_engine"] = eng

    # key type
    kt = str(cfg.get("default_key_type") or "RSA").strip().upper()
    if kt not in ("RSA", "ECC"):
        kt = "RSA"
    cfg["default_key_type"] = kt

    # key size
    try:
        cfg["default_key_size"] = int(cfg.get("default_key_size") or 4096)
    except Exception:
        cfg["default_key_size"] = 4096
    cfg["default_key_size"] = max(2048, min(16384, cfg["default_key_size"]))

    # pass length
    try:
        cfg["pass_length"] = int(cfg.get("pass_length") or 24)
    except Exception:
        cfg["pass_length"] = 24
    cfg["pass_length"] = max(8, min(128, cfg["pass_length"]))

    # countries list
    countries = cfg.get("countries")
    if not isinstance(countries, list):
        countries = []
    norm: List[Dict[str, str]] = []
    for item in countries:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip().upper()
        name = str(item.get("name") or "").strip()
        if len(code) != 2 or not name:
            continue
        norm.append({"code": code, "name": name})
    if not norm:
        norm = list(DEFAULTS["countries"])
    cfg["countries"] = norm

    # default country
    dc = str(cfg.get("default_country") or "BE").strip().upper()
    if len(dc) != 2:
        dc = "BE"
    cfg["default_country"] = dc

    # ensure BE first if present
    cfg["countries"] = sorted(cfg["countries"], key=lambda x: (0 if x["code"] == "BE" else 1, x["name"]))

    return cfg


def load_cfg() -> Dict[str, Any]:
    global CFG
    CFG = _normalize_cfg(_safe_json_load(SETTINGS_PATH, DEFAULTS))
    return CFG


# =========================
# Utils
# =========================
def _html(s: Any) -> str:
    return (
        str(s if s is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _slug_filename(s: str) -> str:
    s = (s or "").strip()
    out = []
    for ch in s:
        if ch.isalnum() or ch in ("_", "-", "."):
            out.append(ch)
        elif ch in (" ", "/", "\\", ":", ";", ",", "|"):
            out.append("_")
        else:
            out.append("_")
    name = "".join(out).strip("_")
    return name or "cert"


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def compute_output_dir(root_base_dir: str) -> Path:
    root = Path(root_base_dir)
    now = datetime.now()
    target = root / f"{now.year}" / f"{now.month:02d}" / f"{now.day:02d}"
    return _ensure_dir(target)


def generate_password(length: int) -> str:
    # (zelfde “stijl” als voica1: mix + niet starten/eindigen met symbool)
    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    digits = string.digits
    symbols = r"\!@#$%&*()-_=+;[{]}:,.<>?/"
    all_chars = lower + upper + digits + symbols
    non_symbols = lower + upper + digits

    length = max(8, int(length))
    while True:
        pwd = [
            secrets.choice(lower),
            secrets.choice(upper),
            secrets.choice(digits),
            secrets.choice(symbols),
        ]
        pwd += [secrets.choice(all_chars) for _ in range(length - 4)]
        secrets.SystemRandom().shuffle(pwd)

        if pwd[0] in symbols or pwd[-1] in symbols:
            continue
        if not any(ch in symbols for ch in pwd[1:-1]):
            continue
        if pwd[0] not in non_symbols or pwd[-1] not in non_symbols:
            continue
        return "".join(pwd)


def _parse_sans(raw: str) -> List[str]:
    items: List[str] = []
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s:
            continue
        # allow comma-separated too
        parts = [p.strip() for p in s.split(",") if p.strip()]
        items.extend(parts)
    # dedupe while keeping order
    seen = set()
    out: List[str] = []
    for s in items:
        if s.lower() in seen:
            continue
        seen.add(s.lower())
        out.append(s)
    return out


def _infer_san_type(s: str) -> Tuple[str, str]:
    """
    Returns (kind, value) where kind is one of: DNS, IP, EMAIL
    """
    if "@" in s and " " not in s:
        return ("EMAIL", s)
    try:
        ip = ipaddress.ip_address(s)
        return ("IP", str(ip))
    except Exception:
        pass
    return ("DNS", s)


def _validate_subject(country: str, org: str, cn: str, email: str) -> Tuple[str, str, str, str]:
    country = (country or "").strip().upper()
    org = (org or "").strip()
    cn = (cn or "").strip()
    email = (email or "").strip()

    if len(country) != 2:
        raise ValueError("countryName moet exact 2 tekens zijn (bv. BE).")
    if not org:
        raise ValueError("organizationName is verplicht.")
    if not cn:
        raise ValueError("commonName is verplicht.")
    if not email or "@" not in email:
        raise ValueError("emailAddress is verplicht en moet een geldig e-mailadres bevatten.")
    return country, org, cn, email


def _run_cmd(cmd: List[str], cwd: Optional[Path] = None, openssl_conf: Optional[str] = None) -> str:
    env = os.environ.copy()
    if openssl_conf:
        env["OPENSSL_CONF"] = openssl_conf
    p = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        env=env,
    )
    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    if p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(cmd)}\n{out}".strip())
    return out.strip()


@dataclass
class MakeResult:
    ok: bool
    out_dir: Path
    base: str
    base_hyphen: str
    key_path: Path
    csr_path: Path
    b64_path: Path
    csr_pem: str
    csr_b64: str
    expected_crt_name: str
    msg: str = ""
    debug: str = ""


# =========================
# Engines: Python (cryptography)
# =========================
def py_make_key_and_csr(
    *,
    out_dir: Path,
    base: str,
    key_type: str,
    key_size: int,
    ecc_curve: str,
    country: str,
    org: str,
    cn: str,
    email: str,
    sans: List[str],
) -> MakeResult:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    from cryptography.x509.oid import NameOID

    key_type = key_type.upper()
    if key_type == "RSA":
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    else:
        # ECC secp384r1
        curve = ec.SECP384R1() if ecc_curve.lower() == "secp384r1" else ec.SECP384R1()
        private_key = ec.generate_private_key(curve)

    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, country),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
            x509.NameAttribute(NameOID.EMAIL_ADDRESS, email),
        ]
    )

    builder = x509.CertificateSigningRequestBuilder().subject_name(name)

    san_objs: List[x509.GeneralName] = []
    for item in sans:
        kind, val = _infer_san_type(item)
        if kind == "EMAIL":
            san_objs.append(x509.RFC822Name(val))
        elif kind == "IP":
            san_objs.append(x509.IPAddress(ipaddress.ip_address(val)))
        else:
            san_objs.append(x509.DNSName(val))

    if san_objs:
        builder = builder.add_extension(x509.SubjectAlternativeName(san_objs), critical=False)

    csr = builder.sign(private_key, hashes.SHA384())

    key_path = out_dir / f"{base}.key.pem"
    csr_path = out_dir / f"{base}.csr"
    b64_path = out_dir / f"{base}.b64"

    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    csr_pem_bytes = csr.public_bytes(serialization.Encoding.PEM)
    csr_der_bytes = csr.public_bytes(serialization.Encoding.DER)
    csr_b64 = base64.b64encode(csr_der_bytes).decode("ascii")

    key_path.write_bytes(key_pem)
    csr_path.write_bytes(csr_pem_bytes)
    b64_path.write_text(csr_b64, encoding="utf-8")

    base_hyphen = base.replace("_", "-")
    expected_crt_name = f"{base_hyphen}.crt"

    return MakeResult(
        ok=True,
        out_dir=out_dir,
        base=base,
        base_hyphen=base_hyphen,
        key_path=key_path,
        csr_path=csr_path,
        b64_path=b64_path,
        csr_pem=csr_pem_bytes.decode("utf-8", errors="replace"),
        csr_b64=csr_b64,
        expected_crt_name=expected_crt_name,
        msg="✅ Key + CSR gemaakt (python engine)",
    )


# =========================
# Engines: OpenSSL
# =========================
def _openssl_subject(country: str, org: str, cn: str, email: str) -> str:
    # openssl -subj format
    # /C=BE/O=Org/CN=example/emailAddress=a@b
    def esc(v: str) -> str:
        return v.replace("/", r"\/")

    return f"/C={esc(country)}/O={esc(org)}/CN={esc(cn)}/emailAddress={esc(email)}"


def openssl_make_key_and_csr(
    *,
    out_dir: Path,
    base: str,
    openssl_bin: str,
    openssl_conf: Optional[str],
    key_type: str,
    key_size: int,
    ecc_curve: str,
    country: str,
    org: str,
    cn: str,
    email: str,
    sans: List[str],
) -> MakeResult:
    key_type = key_type.upper()

    key_path = out_dir / f"{base}.key.pem"
    csr_path = out_dir / f"{base}.csr"
    b64_path = out_dir / f"{base}.b64"

    # 1) key
    if key_type == "RSA":
        # prefer genpkey (modern)
        _run_cmd(
            [openssl_bin, "genpkey", "-algorithm", "RSA", "-pkeyopt", f"rsa_keygen_bits:{key_size}", "-out", str(key_path)],
            cwd=out_dir,
            openssl_conf=openssl_conf,
        )
    else:
        # ECC secp384r1
        curve = ecc_curve.lower() or "secp384r1"
        _run_cmd(
            [openssl_bin, "ecparam", "-name", curve, "-genkey", "-noout", "-out", str(key_path)],
            cwd=out_dir,
            openssl_conf=openssl_conf,
        )

    subj = _openssl_subject(country, org, cn, email)

    # 2) CSR (+ SANs via temp config indien nodig)
    if sans:
        # build minimal openssl config with SANs
        san_lines: List[str] = []
        dns_i = 1
        ip_i = 1
        email_i = 1
        for item in sans:
            kind, val = _infer_san_type(item)
            if kind == "DNS":
                san_lines.append(f"DNS.{dns_i} = {val}")
                dns_i += 1
            elif kind == "IP":
                san_lines.append(f"IP.{ip_i} = {val}")
                ip_i += 1
            else:
                san_lines.append(f"email.{email_i} = {val}")
                email_i += 1

        cfg_txt = "\n".join(
            [
                "[ req ]",
                "prompt = no",
                "distinguished_name = dn",
                "req_extensions = v3_req",
                "",
                "[ dn ]",
                f"C = {country}",
                f"O = {org}",
                f"CN = {cn}",
                f"emailAddress = {email}",
                "",
                "[ v3_req ]",
                "subjectAltName = @alt_names",
                "",
                "[ alt_names ]",
                *san_lines,
                "",
            ]
        )

        tmp_cfg = out_dir / f"{base}._openssl_req.cnf"
        tmp_cfg.write_text(cfg_txt, encoding="utf-8")

        try:
            _run_cmd(
                [
                    openssl_bin,
                    "req",
                    "-new",
                    "-sha384",
                    "-key",
                    str(key_path),
                    "-out",
                    str(csr_path),
                    "-config",
                    str(tmp_cfg),
                ],
                cwd=out_dir,
                openssl_conf=openssl_conf,
            )
        finally:
            # laat file staan als debug? -> we verwijderen toch
            try:
                tmp_cfg.unlink(missing_ok=True)  # py3.8+ ok
            except Exception:
                pass
    else:
        _run_cmd(
            [openssl_bin, "req", "-new", "-sha384", "-key", str(key_path), "-out", str(csr_path), "-subj", subj],
            cwd=out_dir,
            openssl_conf=openssl_conf,
        )

    # 3) CSR -> DER -> base64 singleline
    # openssl req -in csr -outform DER | base64 (windows base64 tool not guaranteed)
    # we do it in python:
    csr_pem = csr_path.read_text(encoding="utf-8", errors="replace")
    der_bytes = _run_cmd(
        [openssl_bin, "req", "-in", str(csr_path), "-outform", "DER"],
        cwd=out_dir,
        openssl_conf=openssl_conf,
    ).encode("utf-8", errors="ignore")  # not correct (req outputs binary)
    # req -outform DER returns binary to stdout; subprocess text=True breaks binary.
    # So we re-run in binary-safe mode:
    env = os.environ.copy()
    if openssl_conf:
        env["OPENSSL_CONF"] = openssl_conf
    p = subprocess.run(
        [openssl_bin, "req", "-in", str(csr_path), "-outform", "DER"],
        cwd=str(out_dir),
        capture_output=True,
        env=env,
    )
    if p.returncode != 0:
        raise RuntimeError(f"OpenSSL DER export failed:\n{(p.stderr or b'').decode('utf-8', 'replace')}")
    csr_b64 = base64.b64encode(p.stdout).decode("ascii")
    b64_path.write_text(csr_b64, encoding="utf-8")

    base_hyphen = base.replace("_", "-")
    expected_crt_name = f"{base_hyphen}.crt"

    return MakeResult(
        ok=True,
        out_dir=out_dir,
        base=base,
        base_hyphen=base_hyphen,
        key_path=key_path,
        csr_path=csr_path,
        b64_path=b64_path,
        csr_pem=csr_pem,
        csr_b64=csr_b64,
        expected_crt_name=expected_crt_name,
        msg="✅ Key + CSR gemaakt (openssl engine)",
    )


# =========================
# Export helpers
# =========================
@dataclass
class ExportResult:
    ok: bool
    msg: str
    out_path: Optional[Path] = None
    password: Optional[str] = None
    debug: str = ""


def _safe_resolve_under(base_root: Path, p: Path) -> Path:
    base_root = base_root.resolve()
    rp = p.resolve()
    # prevent path traversal
    if base_root not in rp.parents and rp != base_root:
        raise ValueError("Onveilige output folder (niet onder root_base_dir).")
    return rp


def export_combined_pem(*, out_dir: Path, base: str, cert_path: Path, key_path: Path) -> ExportResult:
    if not cert_path.exists():
        return ExportResult(False, f"❌ Certificaat niet gevonden: {cert_path.name}")
    if not key_path.exists():
        return ExportResult(False, f"❌ Private key niet gevonden: {key_path.name}")

    out_pem = out_dir / f"{base}.pem"
    cert_txt = cert_path.read_text(encoding="utf-8", errors="replace").strip() + "\n"
    key_txt = key_path.read_text(encoding="utf-8", errors="replace").strip() + "\n"

    # meestal: cert eerst, dan key
    out_pem.write_text(cert_txt + "\n" + key_txt, encoding="utf-8")
    return ExportResult(True, "✅ Combined PEM gemaakt (cert + key)", out_path=out_pem)


def export_pkcs12_aes256(
    *,
    openssl_bin: str,
    openssl_conf: Optional[str],
    out_dir: Path,
    base: str,
    cert_path: Path,
    key_path: Path,
    password: str,
) -> ExportResult:
    if not cert_path.exists():
        return ExportResult(False, f"❌ Certificaat niet gevonden: {cert_path.name}")
    if not key_path.exists():
        return ExportResult(False, f"❌ Private key niet gevonden: {key_path.name}")

    out_p12 = out_dir / f"{base}.p12"

    cmd = [
        openssl_bin,
        "pkcs12",
        "-export",
        "-inkey",
        str(key_path),
        "-in",
        str(cert_path),
        "-out",
        str(out_p12),
        "-passout",
        f"pass:{password}",
        "-keypbe",
        "AES-256-CBC",
        "-certpbe",
        "AES-256-CBC",
    ]

    try:
        _run_cmd(cmd, cwd=out_dir, openssl_conf=openssl_conf)
        return ExportResult(True, "✅ PFX/P12 gemaakt (AES-256-CBC)", out_path=out_p12, password=password)
    except Exception as e:
        return ExportResult(False, f"❌ P12 export faalde: {e}", debug=traceback.format_exc())


# =========================
# Main wrapper
# =========================
def make_key_and_csr(
    *,
    engine: str,
    key_type: str,
    key_size: int,
    country: str,
    org: str,
    cn: str,
    email: str,
    sans_raw: str,
    base_name: str,
    out_root: str,
) -> MakeResult:
    cfg = load_cfg()

    out_dir = compute_output_dir(out_root)
    sans = _parse_sans(sans_raw)

    country, org, cn, email = _validate_subject(country, org, cn, email)

    base = _slug_filename(base_name) if base_name.strip() else _slug_filename(cn)
    base = base[:120]

    if engine == "openssl":
        return openssl_make_key_and_csr(
            out_dir=out_dir,
            base=base,
            openssl_bin=str(cfg.get("openssl_bin") or "openssl"),
            openssl_conf=cfg.get("openssl_conf"),
            key_type=key_type,
            key_size=key_size,
            ecc_curve=str(cfg.get("ecc_curve") or "secp384r1"),
            country=country,
            org=org,
            cn=cn,
            email=email,
            sans=sans,
        )
    else:
        return py_make_key_and_csr(
            out_dir=out_dir,
            base=base,
            key_type=key_type,
            key_size=key_size,
            ecc_curve=str(cfg.get("ecc_curve") or "secp384r1"),
            country=country,
            org=org,
            cn=cn,
            email=email,
            sans=sans,
        )


# =========================
# UI rendering
# =========================
def _country_options_html(cfg: Dict[str, Any], selected: str) -> str:
    selected = (selected or "").strip().upper()
    rows = []
    for item in cfg.get("countries", []):
        code = str(item.get("code") or "").upper()
        name = str(item.get("name") or "")
        sel = "selected" if code == selected else ""
        rows.append(f'<option value="{_html(code)}" {sel}>{_html(code)} — {_html(name)}</option>')
    return "\n".join(rows)


def _file_list_html(out_dir: Path) -> str:
    if not out_dir.exists():
        return "<div class='hint'>Nog geen output folder.</div>"
    files = sorted([p for p in out_dir.iterdir() if p.is_file()], key=lambda x: x.name.lower())
    if not files:
        return "<div class='hint'>Nog geen bestanden in output folder.</div>"
    items = []
    for p in files:
        items.append(
            f"""
            <div class="cc-file">
              <div class="cc-file-name">{_html(p.name)}</div>
              <div class="cc-file-actions">
                <a class="cc-btn cc-btn-mini" href="/createcert/dl?dir={_html(out_dir.as_posix())}&name={_html(p.name)}">Download</a>
              </div>
            </div>
            """
        )
    return "\n".join(items)


def _render(
    *,
    cfg: Dict[str, Any],
    msg: str = "",
    err: str = "",
    res: Optional[MakeResult] = None,
    exp_msg: str = "",
    exp_pwd: str = "",
    exp_out: str = "",
    form: Optional[Dict[str, str]] = None,
) -> str:
    form = form or {}
    # defaults
    engine = form.get("engine") or str(cfg.get("default_engine") or "python")
    key_type = form.get("key_type") or str(cfg.get("default_key_type") or "RSA")
    key_size = form.get("key_size") or str(cfg.get("default_key_size") or 4096)
    country = form.get("country") or str(cfg.get("default_country") or "BE")
    org = form.get("org") or ""
    cn = form.get("cn") or ""
    email = form.get("email") or ""
    sans_raw = form.get("sans") or ""
    base_name = form.get("base_name") or ""
    out_root = form.get("out_root") or str(cfg.get("root_base_dir") or DEFAULTS["root_base_dir"])

    # if we have a result, keep its out_dir in the form
    out_dir_val = str(res.out_dir) if res else form.get("out_dir") or ""
    base_val = res.base if res else base_name

    # expected crt name
    expected_crt = res.expected_crt_name if res else (base_val.replace("_", "-") + ".crt" if base_val else "")

    # include tool-specific CSS/JS
    head = """
<link rel="stylesheet" href="/static/css/createcert.css?v=1">
<script src="/static/js/createcert.js?v=1" defer></script>
"""

    notice = ""
    if err:
        notice = f"<div class='cc-notice cc-err'>❌ {_html(err)}</div>"
    elif msg:
        notice = f"<div class='cc-notice cc-ok'>✅ {_html(msg)}</div>"

    export_notice = ""
    if exp_msg:
        export_notice = f"<div class='cc-notice cc-ok' style='margin-top:10px;'>{_html(exp_msg)}</div>"
    if exp_out:
        export_notice += f"<div class='hint'>Output: <code>{_html(exp_out)}</code></div>"
    if exp_pwd:
        export_notice += f"""
<div class="cc-copyrow" style="margin-top:10px;">
  <div class="hint" style="min-width:140px;">P12 password:</div>
  <input class="cc-inp" id="p12pwd" value="{_html(exp_pwd)}" readonly>
  <button class="cc-btn cc-btn-mini" type="button" data-copy="#p12pwd">Copy</button>
</div>
"""

    csr_blocks = ""
    if res and res.ok:
        csr_blocks = f"""
<div class="cc-grid2" style="margin-top:12px;">
  <div class="panel">
    <div class="cc-section-title">CSR (PEM) — copy</div>
    <div class="cc-copyrow">
      <button class="cc-btn cc-btn-mini" type="button" data-copy="#csrPem">Copy CSR</button>
    </div>
    <textarea class="cc-ta" id="csrPem" readonly>{_html(res.csr_pem)}</textarea>
  </div>

  <div class="panel">
    <div class="cc-section-title">CSR (DER → Base64 single-line) — copy</div>
    <div class="cc-copyrow">
      <button class="cc-btn cc-btn-mini" type="button" data-copy="#csrB64">Copy B64</button>
    </div>
    <textarea class="cc-ta" id="csrB64" readonly>{_html(res.csr_b64)}</textarea>
  </div>
</div>

<div class="panel" style="margin-top:12px;">
  <div class="cc-section-title">Bestanden</div>
  <div class="hint">
    Output folder: <code>{_html(str(res.out_dir))}</code><br>
    Verwacht certificaatnaam (na ontvangst): <code>{_html(res.expected_crt_name)}</code>
  </div>

  <div class="cc-files" style="margin-top:10px;">
    {_file_list_html(res.out_dir)}
  </div>
</div>
"""

    content = f"""
{head}

<div class="panel">
  <h2 style="margin:0 0 6px 0;">CreateCert</h2>
  <div class="hint">
    Key + CSR maker • Engine python/openssl • SHA-384 • RSA 4096 / ECC secp384r1
  </div>
</div>

{notice}

<div class="cc-wrap">

  <div class="panel">
    <div class="cc-section-title">1) Key + CSR maken</div>

    <form method="post" action="/createcert" class="cc-form">
      <input type="hidden" name="action" value="make">

      <div class="cc-grid2">
        <div>
          <div class="cc-label">Engine</div>
          <div class="cc-radio">
            <label><input type="radio" name="engine" value="python" {"checked" if engine=="python" else ""}> python</label>
            <label><input type="radio" name="engine" value="openssl" {"checked" if engine=="openssl" else ""}> openssl</label>
          </div>
          <div class="hint">OpenSSL nodig voor P12 export (AES-256-CBC).</div>
        </div>

        <div>
          <div class="cc-label">Key type</div>
          <div class="cc-radio">
            <label><input type="radio" name="key_type" value="RSA" {"checked" if key_type.upper()=="RSA" else ""}> RSA</label>
            <label><input type="radio" name="key_type" value="ECC" {"checked" if key_type.upper()=="ECC" else ""}> ECC (secp384r1)</label>
          </div>

          <div class="cc-label" style="margin-top:10px;">Key size (RSA)</div>
          <input class="cc-inp" name="key_size" value="{_html(key_size)}" placeholder="4096">
        </div>
      </div>

      <div class="cc-grid2" style="margin-top:12px;">
        <div>
          <div class="cc-label">countryName (C) — verplicht</div>
          <select class="cc-inp" name="country">
            {_country_options_html(cfg, country)}
          </select>
          <div class="hint">Moet 2-letter code zijn (BE/NL/...).</div>
        </div>

        <div>
          <div class="cc-label">organizationName (O) — verplicht</div>
          <input class="cc-inp" name="org" value="{_html(org)}" placeholder="Organization">
        </div>

        <div>
          <div class="cc-label">commonName (CN) — verplicht</div>
          <input class="cc-inp" name="cn" value="{_html(cn)}" placeholder="Common Name">
        </div>

        <div>
          <div class="cc-label">emailAddress — verplicht</div>
          <input class="cc-inp" name="email" value="{_html(email)}" placeholder="name@domain.tld">
        </div>
      </div>

      <div class="cc-grid2" style="margin-top:12px;">
        <div>
          <div class="cc-label">Bestands prefix (optioneel)</div>
          <input class="cc-inp" name="base_name" value="{_html(base_name)}" placeholder="bv OVO002949_tt_test20260120">
          <div class="hint">Leeg = afgeleid van CN. Spaties/specials → underscore.</div>
        </div>

        <div>
          <div class="cc-label">Output root (settings)</div>
          <input class="cc-inp" name="out_root" value="{_html(out_root)}">
          <div class="hint">Tool maakt automatisch YYYY\\MM\\DD.</div>
        </div>
      </div>

      <div style="margin-top:12px;">
        <div class="cc-label">SANs (optioneel) — 1 per lijn (DNS/IP/email)</div>
        <textarea class="cc-ta" name="sans" placeholder="voorbeeld:
example.domain.be
10.0.0.10
altmail@domain.be">{_html(sans_raw)}</textarea>
      </div>

      <div class="cc-actions">
        <button class="cc-btn cc-btn-primary" type="submit">Maak key + CSR</button>
      </div>
    </form>
  </div>

  <div class="panel" style="margin-top:12px;">
    <div class="cc-section-title">2) Export (pas als je op knop drukt)</div>

    <div class="hint">
      Verwachte cert naam: <code>{_html(expected_crt)}</code> (je kan ook uploaden hieronder).
    </div>

    <form method="post" action="/createcert" enctype="multipart/form-data" class="cc-form" style="margin-top:10px;">
      <input type="hidden" name="action" value="export">
      <input type="hidden" name="out_dir" value="{_html(out_dir_val)}">
      <input type="hidden" name="base" value="{_html(base_val)}">

      <div class="cc-grid2">
        <div>
          <div class="cc-label">Certificaat uploaden (optioneel)</div>
          <input class="cc-inp" type="file" name="cert_file" accept=".crt,.cer,.pem">
          <div class="hint">Als je uploadt, wordt het bewaard als <code>{_html(expected_crt or "x.crt")}</code> in de output folder.</div>
        </div>

        <div>
          <div class="cc-label">Of gebruik cert in output folder</div>
          <input class="cc-inp" name="cert_name" value="{_html(expected_crt)}" placeholder="bv OVO002949-tt-test20260120.crt">
          <div class="hint">Standaard: underscores → hyphens + .crt</div>
        </div>
      </div>

      <div class="cc-actions" style="margin-top:12px;">
        <button class="cc-btn" type="submit" name="do" value="pem">Maak PEM (cert + key)</button>
        <button class="cc-btn cc-btn-primary" type="submit" name="do" value="p12">Maak PFX (.p12) (AES-256-CBC)</button>
      </div>
    </form>

    {export_notice}
  </div>

</div>

{csr_blocks}
"""

    return hub_render_page(title="CreateCert", content_html=content)


# =========================
# Routes
# =========================
def createcert_home() -> str:
    cfg = load_cfg()

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()

        # --- make ---
        if action == "make":
            try:
                engine = (request.form.get("engine") or cfg.get("default_engine") or "python").strip().lower()
                key_type = (request.form.get("key_type") or cfg.get("default_key_type") or "RSA").strip().upper()
                try:
                    key_size = int(request.form.get("key_size") or cfg.get("default_key_size") or 4096)
                except Exception:
                    key_size = int(cfg.get("default_key_size") or 4096)

                country = request.form.get("country") or cfg.get("default_country") or "BE"
                org = request.form.get("org") or ""
                cn = request.form.get("cn") or ""
                email = request.form.get("email") or ""
                sans_raw = request.form.get("sans") or ""
                base_name = request.form.get("base_name") or ""
                out_root = request.form.get("out_root") or str(cfg.get("root_base_dir") or DEFAULTS["root_base_dir"])

                res = make_key_and_csr(
                    engine=engine,
                    key_type=key_type,
                    key_size=key_size,
                    country=country,
                    org=org,
                    cn=cn,
                    email=email,
                    sans_raw=sans_raw,
                    base_name=base_name,
                    out_root=out_root,
                )

                form = {
                    "engine": engine,
                    "key_type": key_type,
                    "key_size": str(key_size),
                    "country": country,
                    "org": org,
                    "cn": cn,
                    "email": email,
                    "sans": sans_raw,
                    "base_name": base_name,
                    "out_root": out_root,
                    "out_dir": str(res.out_dir),
                }
                return _render(cfg=cfg, msg=res.msg, res=res, form=form)

            except Exception as e:
                form = {k: (request.form.get(k) or "") for k in ("engine", "key_type", "key_size", "country", "org", "cn", "email", "sans", "base_name", "out_root")}
                return _render(cfg=cfg, err=str(e), form=form)

        # --- export ---
        if action == "export":
            try:
                base_root = Path(str(cfg.get("root_base_dir") or DEFAULTS["root_base_dir"]))
                out_dir = Path(request.form.get("out_dir") or "")
                base = _slug_filename(request.form.get("base") or "")
                if not out_dir or not str(out_dir).strip():
                    raise ValueError("Geen output folder gevonden. Maak eerst key + CSR.")
                if not base:
                    raise ValueError("Geen base/prefix gevonden. Maak eerst key + CSR.")

                out_dir = _safe_resolve_under(base_root, out_dir)
                key_path = out_dir / f"{base}.key.pem"

                do = (request.form.get("do") or "").strip().lower()

                # certificate resolution: upload wins, else cert_name in folder
                cert_name = (request.form.get("cert_name") or f"{base.replace('_','-')}.crt").strip()
                cert_path = out_dir / cert_name

                # handle upload
                f = request.files.get("cert_file")
                if f and getattr(f, "filename", ""):
                    # always store as expected name (hyphen)
                    expected = f"{base.replace('_','-')}.crt"
                    cert_path = out_dir / expected
                    f.save(str(cert_path))

                exp_res: ExportResult
                if do == "pem":
                    exp_res = export_combined_pem(out_dir=out_dir, base=base, cert_path=cert_path, key_path=key_path)
                    exp_pwd = ""
                elif do == "p12":
                    pwd = generate_password(int(cfg.get("pass_length") or 24))
                    exp_res = export_pkcs12_aes256(
                        openssl_bin=str(cfg.get("openssl_bin") or "openssl"),
                        openssl_conf=cfg.get("openssl_conf"),
                        out_dir=out_dir,
                        base=base,
                        cert_path=cert_path,
                        key_path=key_path,
                        password=pwd,
                    )
                    exp_pwd = exp_res.password or ""
                else:
                    raise ValueError("Onbekende export actie.")

                form = {"out_root": str(cfg.get("root_base_dir") or ""), "out_dir": str(out_dir), "base_name": base}
                if exp_res.ok:
                    return _render(cfg=cfg, msg="", res=None, exp_msg=exp_res.msg, exp_pwd=exp_pwd, exp_out=str(exp_res.out_path or ""), form=form)
                return _render(cfg=cfg, err=exp_res.msg, exp_msg="", exp_pwd=exp_pwd, exp_out=str(exp_res.out_path or ""), form=form)

            except Exception as e:
                return _render(cfg=cfg, err=str(e))

        return _render(cfg=cfg, err="Onbekende actie.")

    # GET
    return _render(cfg=cfg)


def register_web_routes(app) -> None:
    # main page
    @app.route("/createcert", methods=["GET", "POST"])
    def _createcert_route():
        return createcert_home()

    # download endpoint (safe, only from output dir under root)
    @app.get("/createcert/dl")
    def _createcert_dl():
        cfg = load_cfg()
        base_root = Path(str(cfg.get("root_base_dir") or DEFAULTS["root_base_dir"]))
        dir_s = request.args.get("dir") or ""
        name = request.args.get("name") or ""
        out_dir = _safe_resolve_under(base_root, Path(dir_s))
        # serve file
        return send_from_directory(out_dir, name, as_attachment=True)


# =========================
# Standalone
# =========================
def _standalone() -> None:
    app = Flask("CreateCert", static_folder=str(PROJECT_ROOT / "static"), static_url_path="/static")
    register_web_routes(app)

    @app.get("/")
    def _root():
        return '<meta http-equiv="refresh" content="0; url=/createcert">'

    app.run(host="127.0.0.1", port=5011, debug=False)


if __name__ == "__main__":
    _standalone()
