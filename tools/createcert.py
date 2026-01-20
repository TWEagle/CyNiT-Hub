#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, request, render_template_string

# Hub layout (CyNiT-Hub)
from beheer.main_layout import render_page as hub_render_page


# =========================
# Project/Config paths (robuust, zoals voica1.py)
# =========================
def _find_project_root() -> Path:
    """
    Vind de projectroot door omhoog te lopen tot we /config vinden (max 3 niveaus).
    Dit maakt de module robuust wanneer ze in tools/ staat.
    """
    p = Path(__file__).resolve().parent
    for _ in range(3):
        if (p / "config").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parent


PROJECT_ROOT = _find_project_root()
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_JSON = CONFIG_DIR / "creacert_settings.json"


# =========================
# Defaults / settings
# =========================
DEFAULTS: Dict[str, Any] = {
    "default_engine": "python",  # "python" | "openssl"
    "debug_default": False,

    "openssl_bin": "openssl",
    "openssl_conf": None,  # optional pad

    "base_output_dir": r"C:\Users\lemmenmf\OneDrive - Vlaamse overheid - Office 365\DCBaaS\VOICA1\Certificaten",
    "rsa_default_bits": 4096,

    # Fixed requirements
    "ecc_curve": "secp384r1",
    "hash_algo": "sha384",

    # (future-proof) voor latere PFX export
    "pkcs12_cipher": "AES-256-CBC",
}


def _load_settings() -> Dict[str, Any]:
    if SETTINGS_JSON.exists():
        try:
            data = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged = dict(DEFAULTS)
                merged.update(data)
                # enforce fixed requirements
                merged["ecc_curve"] = "secp384r1"
                merged["hash_algo"] = "sha384"
                if merged.get("default_engine") not in ("python", "openssl"):
                    merged["default_engine"] = "python"
                return merged
        except Exception:
            pass
    return dict(DEFAULTS)


def _save_settings(cfg: Dict[str, Any]) -> None:
    cfg = dict(cfg or {})
    cfg["ecc_curve"] = "secp384r1"
    cfg["hash_algo"] = "sha384"
    if cfg.get("default_engine") not in ("python", "openssl"):
        cfg["default_engine"] = "python"

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_JSON.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


# =========================
# Helpers
# =========================
def _html(s: object) -> str:
    return (
        str(s if s is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _safe_filename(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "csr"


def _parse_sans(raw: str) -> List[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    parts = re.split(r"[,\n;\r]+", raw)
    out: List[str] = []
    for p in parts:
        p = (p or "").strip()
        if not p:
            continue
        p = re.sub(r"^\s*DNS\s*:\s*", "", p, flags=re.IGNORECASE).strip()
        if p:
            out.append(p)
    # uniq preserve order
    seen = set()
    uniq: List[str] = []
    for x in out:
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(x)
    return uniq


def _date_folder(base: str) -> Path:
    now = datetime.now()
    out = Path(base) / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _build_subj(country: str, org: str, cn: str, email: str) -> str:
    # OpenSSL -subj format
    return f"/C={country}/O={org}/CN={cn}/emailAddress={email}"

def _normalize_and_validate_country(C: str) -> Tuple[Optional[str], Optional[str]]:
    """
    countryName in X.509 moet exact 2 letters zijn (bv. BE).
    Returns: (normalized_value, error_message)
    """
    c = (C or "").strip().upper()

    if not c:
        return None, "countryName (C) is verplicht en moet 2 letters zijn (bv. BE)."

    if len(c) != 2:
        return None, f"countryName (C) moet exact 2 letters zijn (bv. BE). Jij gaf: {c!r}"

    if not re.fullmatch(r"[A-Z]{2}", c):
        return None, f"countryName (C) mag enkel letters A-Z bevatten (bv. BE). Jij gaf: {c!r}"

    return c, None

def _run_openssl(cmd: List[str], openssl_conf: Optional[str]) -> Tuple[int, str, str]:
    env = os.environ.copy()
    if openssl_conf:
        env["OPENSSL_CONF"] = openssl_conf
    p = subprocess.run(cmd, capture_output=True, text=True, shell=False, env=env)
    return p.returncode, p.stdout or "", p.stderr or ""


def _crypto_import() -> bool:
    try:
        import cryptography  # noqa
        return True
    except Exception:
        return False


@dataclass
class GenResult:
    ok: bool
    message: str
    out_dir: Optional[Path] = None
    key_path: Optional[Path] = None
    csr_pem_path: Optional[Path] = None
    csr_der_path: Optional[Path] = None
    csr_der_b64_path: Optional[Path] = None
    csr_pem_text: str = ""
    csr_der_b64_singleline: str = ""


# =========================
# Engine: Python (cryptography)
# =========================
def py_make_key_and_csr(
    *,
    kind: str,
    rsa_bits: int,
    country: str,
    org: str,
    cn: str,
    email: str,
    sans: List[str],
    cfg: Dict[str, Any],
) -> GenResult:
    if not _crypto_import():
        return GenResult(
            ok=False,
            message=(
                "Python engine vereist 'cryptography'.\n"
                "Installeer: pip install cryptography\n"
                "Of kies Engine = OpenSSL."
            ),
        )

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    from cryptography.x509.oid import NameOID

    base_dir = str(cfg.get("base_output_dir") or DEFAULTS["base_output_dir"])
    out_dir = _date_folder(base_dir)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = _safe_filename(cn) + "__" + stamp

    key_path = out_dir / f"{base}.key.pem"
    csr_pem_path = out_dir / f"{base}.csr.pem"
    csr_der_path = out_dir / f"{base}.csr.der"
    csr_der_b64_path = out_dir / f"{base}.csr.der.b64.txt"

    # Key
    if kind == "rsa":
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=int(rsa_bits))
    else:
        # ECC secp384r1
        private_key = ec.generate_private_key(ec.SECP384R1())

    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.write_bytes(key_pem)

    # CSR subject
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, country),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
            x509.NameAttribute(NameOID.EMAIL_ADDRESS, email),
        ]
    )

    builder = x509.CertificateSigningRequestBuilder().subject_name(subject)

    # SANs (DNS)
    if sans:
        san_ext = x509.SubjectAlternativeName([x509.DNSName(x) for x in sans])
        builder = builder.add_extension(san_ext, critical=False)

    # Sign with SHA-384 (forced)
    csr = builder.sign(private_key, hashes.SHA384())

    csr_pem = csr.public_bytes(serialization.Encoding.PEM)
    csr_der = csr.public_bytes(serialization.Encoding.DER)

    csr_pem_path.write_bytes(csr_pem)
    csr_der_path.write_bytes(csr_der)

    b64_single = base64.b64encode(csr_der).decode("ascii")
    csr_der_b64_path.write_text(b64_single, encoding="utf-8")

    return GenResult(
        ok=True,
        message="✅ CSR + private key gegenereerd (Python engine).",
        out_dir=out_dir,
        key_path=key_path,
        csr_pem_path=csr_pem_path,
        csr_der_path=csr_der_path,
        csr_der_b64_path=csr_der_b64_path,
        csr_pem_text=csr_pem.decode("utf-8", errors="replace"),
        csr_der_b64_singleline=b64_single,
    )


# =========================
# Engine: OpenSSL
# =========================
def openssl_make_key_and_csr(
    *,
    kind: str,
    rsa_bits: int,
    country: str,
    org: str,
    cn: str,
    email: str,
    sans: List[str],
    cfg: Dict[str, Any],
) -> GenResult:
    openssl_bin = str(cfg.get("openssl_bin") or "openssl")
    openssl_conf = cfg.get("openssl_conf") or None

    base_dir = str(cfg.get("base_output_dir") or DEFAULTS["base_output_dir"])
    out_dir = _date_folder(base_dir)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = _safe_filename(cn) + "__" + stamp

    key_path = out_dir / f"{base}.key.pem"
    csr_pem_path = out_dir / f"{base}.csr.pem"
    csr_der_path = out_dir / f"{base}.csr.der"
    csr_der_b64_path = out_dir / f"{base}.csr.der.b64.txt"

    subj = _build_subj(country, org, cn, email)

    # Key
    if kind == "rsa":
        cmd_key = [openssl_bin, "genrsa", "-out", str(key_path), str(int(rsa_bits))]
    else:
        # ECC: secp384r1
        cmd_key = [openssl_bin, "ecparam", "-name", "secp384r1", "-genkey", "-noout", "-out", str(key_path)]

    rc, so, se = _run_openssl(cmd_key, openssl_conf)
    if rc != 0 or not key_path.exists():
        return GenResult(
            ok=False,
            message=(
                "Key generatie faalde (OpenSSL).\n\n"
                f"CMD: {' '.join(cmd_key)}\n\nSTDERR:\n{se}\n\nSTDOUT:\n{so}"
            ),
        )

    # CSR (SHA-384 forced)
    addext: List[str] = []
    if sans:
        san_str = ",".join([f"DNS:{x}" for x in sans])
        addext = ["-addext", f"subjectAltName={san_str}"]

    cmd_csr = [
        openssl_bin,
        "req",
        "-new",
        "-key",
        str(key_path),
        "-sha384",
        "-out",
        str(csr_pem_path),
        "-subj",
        subj,
    ]
    cmd_csr.extend(addext)

    rc, so, se = _run_openssl(cmd_csr, openssl_conf)
    if rc != 0 or not csr_pem_path.exists():
        return GenResult(
            ok=False,
            message=(
                "CSR generatie faalde (OpenSSL).\n\n"
                f"CMD: {' '.join(cmd_csr)}\n\nSTDERR:\n{se}\n\nSTDOUT:\n{so}"
            ),
            out_dir=out_dir,
            key_path=key_path,
        )

    # CSR -> DER
    cmd_der = [openssl_bin, "req", "-in", str(csr_pem_path), "-outform", "DER", "-out", str(csr_der_path)]
    rc, so, se = _run_openssl(cmd_der, openssl_conf)
    if rc != 0 or not csr_der_path.exists():
        return GenResult(
            ok=False,
            message=(
                "CSR DER conversie faalde (OpenSSL).\n\n"
                f"CMD: {' '.join(cmd_der)}\n\nSTDERR:\n{se}\n\nSTDOUT:\n{so}"
            ),
            out_dir=out_dir,
            key_path=key_path,
            csr_pem_path=csr_pem_path,
        )

    csr_pem_text = csr_pem_path.read_text(encoding="utf-8", errors="replace")
    der_bytes = csr_der_path.read_bytes()
    b64_single = base64.b64encode(der_bytes).decode("ascii")
    csr_der_b64_path.write_text(b64_single, encoding="utf-8")

    return GenResult(
        ok=True,
        message="✅ CSR + private key gegenereerd (OpenSSL engine).",
        out_dir=out_dir,
        key_path=key_path,
        csr_pem_path=csr_pem_path,
        csr_der_path=csr_der_path,
        csr_der_b64_path=csr_der_b64_path,
        csr_pem_text=csr_pem_text,
        csr_der_b64_singleline=b64_single,
    )


def make_key_and_csr(
    *,
    engine: str,
    kind: str,
    rsa_bits: int,
    country: str,
    org: str,
    cn: str,
    email: str,
    sans: List[str],
    cfg: Dict[str, Any],
) -> GenResult:
    engine = (engine or "python").strip().lower()
    kind = (kind or "rsa").strip().lower()
    if engine not in ("python", "openssl"):
        engine = "python"
    if kind not in ("rsa", "ecc"):
        kind = "rsa"

    if engine == "openssl":
        return openssl_make_key_and_csr(
            kind=kind,
            rsa_bits=rsa_bits,
            country=country,
            org=org,
            cn=cn,
            email=email,
            sans=sans,
            cfg=cfg,
        )

    return py_make_key_and_csr(
        kind=kind,
        rsa_bits=rsa_bits,
        country=country,
        org=org,
        cn=cn,
        email=email,
        sans=sans,
        cfg=cfg,
    )


# =========================
# UI (content template)
# =========================
CONTENT_TEMPLATE = r"""
<style>
.cc-wrap { max-width: 1100px; margin: 0 auto; }
.card {
  background: rgba(10,15,18,.85); border-radius: 12px; padding: 16px 20px; margin-bottom: 16px;
  border: 1px solid var(--border, rgba(255,255,255,.10));
  box-shadow: var(--shadow, 0 2px 6px rgba(0,0,0,.6));
}
.field { display:grid; gap:6px; margin-bottom: 10px; }
.lbl { color: rgba(255,255,255,.65); font-size: 14px; }
.row { display:flex; gap:12px; flex-wrap:wrap; align-items:center; }
.grid2 { display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.inp, textarea, select {
  width: 100%; box-sizing:border-box; padding: 10px 12px; border-radius: 10px;
  background: #111; color: #fff; border: 1px solid rgba(255,255,255,.18);
}
textarea { resize: vertical; min-height: 84px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; font-size: 12.5px; line-height: 1.35; }
.hint { color: var(--muted, #9fb3b3); font-size: 0.92rem; }
.error-box {
  background: #330000; border: 1px solid #aa3333; color: #ffaaaa; padding: 8px 10px;
  border-radius: 8px; margin-bottom: 12px; font-size: 0.9rem; white-space: pre-wrap;
}
.pill {
  display:inline-flex; padding:6px 10px; border-radius:999px;
  border:1px solid rgba(255,255,255,.14); background: rgba(255,255,255,.03);
}
</style>

<div class="cc-wrap">
  <h1>CreateCert — CSR + Private Key</h1>
  <p class="hint">
    Engine: Python (cryptography) of OpenSSL • CSR = <b>SHA-384</b> • ECC curve = <b>secp384r1</b> • Output: <code>YYYY\MM\DD</code>
  </p>

  {% if error %}
    <div class="error-box">{{ error }}</div>
  {% endif %}

  {% if ok_msg %}
    <div class="card"><b>{{ ok_msg }}</b></div>
  {% endif %}

  <div class="card">
    <div class="row" style="justify-content:space-between;">
      <h2 style="margin:0;">Genereren</h2>
      <div class="row">
        <a class="btn" href="/createcert/settings">⚙️ Settings</a>
      </div>
    </div>

    <form method="post" action="/createcert">
      <div class="grid2">
        <div class="field">
          <label class="lbl">Engine</label>
          <select name="engine">
            <option value="python" {% if engine == 'python' %}selected{% endif %}>Python (cryptography)</option>
            <option value="openssl" {% if engine == 'openssl' %}selected{% endif %}>OpenSSL</option>
          </select>
          <div class="hint">Default = settings. OpenSSL vereist correct pad/PATH.</div>
        </div>

        <div class="field">
          <label class="lbl">Key type</label>
          <div class="row">
            <label class="pill"><input type="radio" name="key_type" value="rsa" {% if key_type == 'rsa' %}checked{% endif %}> RSA</label>
            <label class="pill"><input type="radio" name="key_type" value="ecc" {% if key_type == 'ecc' %}checked{% endif %}> ECC (secp384r1)</label>
          </div>
        </div>

        <div class="field">
          <label class="lbl">RSA key length</label>
          <input class="inp" type="number" min="2048" step="1024" name="rsa_bits" value="{{ rsa_bits }}">
          <div class="hint">Alleen gebruikt bij RSA.</div>
        </div>

        <div class="field">
          <label class="lbl">Output root</label>
          <input class="inp" value="{{ base_output_dir }}" disabled>
          <div class="hint">Tool maakt automatisch <code>YYYY\MM\DD</code> aan.</div>
        </div>
      </div>

      <div class="grid2" style="margin-top: 8px;">
        <div class="field">
          <label class="lbl">countryName (C) *</label>
          <input class="inp" name="C" value="{{ C }}" placeholder="BE" required>
        </div>
        <div class="field">
          <label class="lbl">organizationName (O) *</label>
          <input class="inp" name="O" value="{{ O }}" placeholder="Vlaamse Overheid" required>
        </div>
        <div class="field">
          <label class="lbl">commonName (CN) *</label>
          <input class="inp" name="CN" value="{{ CN }}" placeholder="voorbeeld.domain.be" required>
        </div>
        <div class="field">
          <label class="lbl">emailAddress *</label>
          <input class="inp" type="email" name="email" value="{{ email }}" placeholder="naam@vlaanderen.be" required>
        </div>
      </div>

      <div class="field" style="margin-top: 8px;">
        <label class="lbl">Extra SAN’s (DNS) — optioneel</label>
        <textarea class="inp" name="sans" rows="3" placeholder="dns1.domain.be, dns2.domain.be&#10;of 1 per lijn">{{ sans_raw }}</textarea>
        <div class="hint">Wordt omgezet naar <code>subjectAltName=DNS:...</code></div>
      </div>

      <div class="row" style="margin-top: 8px;">
        <button class="btn btn-primary" type="submit">🧾 Genereer key + CSR</button>
        <span class="pill">CSR hash: SHA-384</span>
        <span class="pill">ECC: secp384r1</span>
      </div>
    </form>
  </div>

  {% if out_dir %}
  <div class="card">
    <div class="pill">📁 Output</div>
    <div class="hint" style="margin-top:8px;">
      Map: <code>{{ out_dir }}</code><br>
      Key: <code>{{ key_path }}</code><br>
      CSR: <code>{{ csr_pem_path }}</code><br>
      CSR DER: <code>{{ csr_der_path }}</code><br>
      Base64: <code>{{ csr_der_b64_path }}</code>
    </div>
  </div>
  {% endif %}

  <div class="card">
    <h3 style="margin:0 0 10px 0;">CSR (PEM)</h3>
    <div class="row" style="margin-bottom:10px;">
      <button class="btn" type="button" onclick="copyFrom('csr_pem')">📋 Copy PEM</button>
    </div>
    <textarea id="csr_pem" class="inp mono" rows="10" placeholder="Na generatie komt hier de CSR PEM...">{{ csr_pem_text }}</textarea>
  </div>

  <div class="card">
    <h3 style="margin:0 0 10px 0;">CSR (DER) — Base64 single-line</h3>
    <div class="row" style="margin-bottom:10px;">
      <button class="btn" type="button" onclick="copyFrom('csr_b64')">📋 Copy Base64</button>
    </div>
    <textarea id="csr_b64" class="inp mono" rows="6" placeholder="Na generatie komt hier de Base64 single-line...">{{ csr_b64_text }}</textarea>
  </div>
</div>

<script>
function copyFrom(id){
  const el = document.getElementById(id);
  if(!el) return;
  el.focus();
  el.select();
  try { document.execCommand('copy'); }
  catch(e){ navigator.clipboard?.writeText(el.value || ""); }
}
</script>
"""


def _render_page(**ctx: Any) -> str:
    content_html = render_template_string(CONTENT_TEMPLATE, **ctx)
    return hub_render_page(title="CreateCert", content_html=content_html)


# =========================
# Routes
# =========================
def register_web_routes(app: Flask, settings: Any = None, tools: Any = None, createcert_cfg: Optional[Dict[str, Any]] = None) -> None:
    # cfg kan extern meegegeven worden (zoals voica1), maar we ondersteunen ook config file
    cfg = _load_settings()
    if createcert_cfg:
        cfg.update(createcert_cfg)
        cfg["ecc_curve"] = "secp384r1"
        cfg["hash_algo"] = "sha384"

    @app.route("/createcert", methods=["GET", "POST"])
    def createcert_home():
        cfg_local = _load_settings()
        engine_default = (cfg_local.get("default_engine") or "python").strip().lower()
        if engine_default not in ("python", "openssl"):
            engine_default = "python"

        rsa_default = int(cfg_local.get("rsa_default_bits") or 4096)

        # defaults for form persistence
        ctx: Dict[str, Any] = dict(
            error="",
            ok_msg="",
            engine=engine_default,
            key_type="rsa",
            rsa_bits=rsa_default,
            base_output_dir=str(cfg_local.get("base_output_dir") or ""),
            C="",
            O="",
            CN="",
            email="",
            sans_raw="",
            out_dir="",
            key_path="",
            csr_pem_path="",
            csr_der_path="",
            csr_der_b64_path="",
            csr_pem_text="",
            csr_b64_text="",
        )

        if request.method == "POST":
            engine = (request.form.get("engine") or engine_default).strip().lower()
            key_type = (request.form.get("key_type") or "rsa").strip().lower()

            C = (request.form.get("C") or "").strip()
            O = (request.form.get("O") or "").strip()
            CN = (request.form.get("CN") or "").strip()
            email = (request.form.get("email") or "").strip()
            sans_raw = request.form.get("sans") or ""
            sans = _parse_sans(sans_raw)

            try:
                rsa_bits = int(request.form.get("rsa_bits") or rsa_default)
            except Exception:
                rsa_bits = rsa_default
            rsa_bits = max(2048, min(16384, rsa_bits))

            ctx.update(
                engine=engine,
                key_type=key_type,
                rsa_bits=rsa_bits,
                C=C,
                O=O,
                CN=CN,
                email=email,
                sans_raw=sans_raw,
            )

            if not (C and O and CN and email):
                ctx["error"] = "Verplichte velden ontbreken (countryName, organizationName, commonName, emailAddress)."
                return _render_page(**ctx)

            try:
                res = make_key_and_csr(
                    engine=engine,
                    kind=key_type,
                    rsa_bits=rsa_bits,
                    country=C,
                    org=O,
                    cn=CN,
                    email=email,
                    sans=sans,
                    cfg=cfg_local,
                )

                if not res.ok:
                    ctx["error"] = res.message
                    return _render_page(**ctx)

                ctx["ok_msg"] = res.message
                ctx["out_dir"] = str(res.out_dir or "")
                ctx["key_path"] = str(res.key_path or "")
                ctx["csr_pem_path"] = str(res.csr_pem_path or "")
                ctx["csr_der_path"] = str(res.csr_der_path or "")
                ctx["csr_der_b64_path"] = str(res.csr_der_b64_path or "")
                ctx["csr_pem_text"] = res.csr_pem_text
                ctx["csr_b64_text"] = res.csr_der_b64_singleline
                return _render_page(**ctx)

            except FileNotFoundError as e:
                # OpenSSL niet gevonden (typisch)
                ctx["error"] = (
                    "OpenSSL werd niet gevonden.\n"
                    f"Details: {e}\n\n"
                    "Fix:\n"
                    " - Zet config/creacert_settings.json → openssl_bin naar een volledig pad (openssl.exe)\n"
                    " - Of kies Engine = Python (cryptography)\n"
                )
                return _render_page(**ctx)

            except Exception as e:
                ctx["error"] = f"Onverwachte fout:\n{e}\n\n{traceback.format_exc()}"
                return _render_page(**ctx)

        return _render_page(**ctx)

    @app.route("/createcert/settings", methods=["GET", "POST"])
    def createcert_settings():
        cfg_local = _load_settings()

        msg = ""
        if request.method == "POST":
            cfg_local["default_engine"] = (request.form.get("default_engine") or "python").strip().lower()
            if cfg_local["default_engine"] not in ("python", "openssl"):
                cfg_local["default_engine"] = "python"

            cfg_local["openssl_bin"] = (request.form.get("openssl_bin") or "openssl").strip()
            openssl_conf = (request.form.get("openssl_conf") or "").strip()
            cfg_local["openssl_conf"] = openssl_conf if openssl_conf else None

            base_output_dir = (request.form.get("base_output_dir") or "").strip()
            if not base_output_dir:
                msg = "❌ base_output_dir mag niet leeg zijn."
            else:
                cfg_local["base_output_dir"] = base_output_dir

            try:
                cfg_local["rsa_default_bits"] = int(request.form.get("rsa_default_bits") or 4096)
            except Exception:
                cfg_local["rsa_default_bits"] = 4096

            # enforce fixed requirements
            cfg_local["ecc_curve"] = "secp384r1"
            cfg_local["hash_algo"] = "sha384"

            if not msg:
                _save_settings(cfg_local)
                msg = "✅ Opgeslagen."

        content = f"""
<div class="card">
  <h2 style="margin:0 0 8px 0;">CreateCert — Settings</h2>
  <div class="hint">Opslag: <code>config/creacert_settings.json</code></div>
  {"<div class='pill' style='margin-top:10px;'>"+_html(msg)+"</div>" if msg else ""}

  <form method="post" style="margin-top:14px; display:grid; gap:12px; max-width: 900px;">
    <div class="field">
      <label class="lbl">Default engine</label>
      <select class="inp" name="default_engine">
        <option value="python" {"selected" if (cfg_local.get("default_engine")=="python") else ""}>Python (cryptography)</option>
        <option value="openssl" {"selected" if (cfg_local.get("default_engine")=="openssl") else ""}>OpenSSL</option>
      </select>
    </div>

    <div class="field">
      <label class="lbl">OpenSSL binary</label>
      <input class="inp" name="openssl_bin" value="{_html(cfg_local.get("openssl_bin"))}" placeholder="openssl">
      <div class="hint">Bv. <code>openssl</code> of volledig pad naar <code>openssl.exe</code>.</div>
    </div>

    <div class="field">
      <label class="lbl">OPENSSL_CONF (optioneel)</label>
      <input class="inp" name="openssl_conf" value="{_html(cfg_local.get("openssl_conf") or "")}" placeholder="C:\\path\\openssl.cnf">
      <div class="hint">Laat leeg tenzij je expliciet een config nodig hebt.</div>
    </div>

    <div class="field">
      <label class="lbl">Base output dir</label>
      <input class="inp" name="base_output_dir" value="{_html(cfg_local.get("base_output_dir"))}">
      <div class="hint">Tool maakt automatisch <code>YYYY\\MM\\DD</code> subfolders aan.</div>
    </div>

    <div class="field">
      <label class="lbl">RSA default bits</label>
      <input class="inp" type="number" min="2048" step="1024" name="rsa_default_bits" value="{int(cfg_local.get("rsa_default_bits") or 4096)}">
    </div>

    <div class="field">
      <label class="lbl">Fixed requirements</label>
      <div class="hint">
        CSR hash: <b>SHA-384</b><br>
        ECC curve: <b>secp384r1</b><br>
        PKCS12 cipher (later): <b>{_html(cfg_local.get("pkcs12_cipher") or "AES-256-CBC")}</b>
      </div>
    </div>

    <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
      <button class="btn btn-primary" type="submit">💾 Opslaan</button>
      <a class="btn" href="/createcert">⬅️ Terug</a>
    </div>
  </form>
</div>

<style>
.field{{ display:grid; gap:6px; }}
.lbl{{ color: rgba(255,255,255,.65); font-size: 14px; }}
</style>
"""
        return hub_render_page(title="CreateCert Settings", content_html=content)


# =========================
# Standalone run
# =========================
if __name__ == "__main__":
    app = Flask(__name__)
    register_web_routes(app)
    app.run(host="127.0.0.1", port=5011, debug=True)
