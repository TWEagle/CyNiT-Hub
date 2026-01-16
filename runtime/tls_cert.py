from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


@dataclass
class TLSPaths:
    dir: Path
    crt: Path  # PEM cert
    key: Path  # PEM key
    cer: Path  # DER cert for Windows trust import


def _log(log_file: Path, msg: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def get_tls_paths(project_dir: Path) -> TLSPaths:
    d = project_dir / "runtime" / "tls"
    return TLSPaths(
        dir=d,
        crt=d / "localhost.crt",
        key=d / "localhost.key",
        cer=d / "localhost.cer",
    )


def ensure_localhost_cert(project_dir: Path, *, log_file: Path) -> Tuple[Path, Path]:
    """
    Ensures a self-signed localhost TLS cert exists in runtime/tls/.
    Returns (crt_path, key_path).
    """
    paths = get_tls_paths(project_dir)
    paths.dir.mkdir(parents=True, exist_ok=True)

    if paths.crt.exists() and paths.key.exists():
        _log(log_file, "TLS cert bestaat al.")
        if not paths.cer.exists():
            try:
                cert = x509.load_pem_x509_certificate(paths.crt.read_bytes())
                paths.cer.write_bytes(cert.public_bytes(serialization.Encoding.DER))
                _log(log_file, "localhost.cer (DER) bijgemaakt.")
            except Exception as e:
                _log(log_file, f"[WARN] kon localhost.cer niet maken: {e}")
        return paths.crt, paths.key

    _log(log_file, "TLS cert ontbreekt -> genereren (self-signed localhost).")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "BE"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CyNiT-Hub"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ]
    )

    # SAN: localhost + 127.0.0.1
    import ipaddress
    san = x509.SubjectAlternativeName(
        [
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow() - timedelta(days=1))
        .not_valid_after(datetime.utcnow() + timedelta(days=825))
        .add_extension(san, critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(private_key=key, algorithm=hashes.SHA256())
    )

    paths.key.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    paths.crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    paths.cer.write_bytes(cert.public_bytes(serialization.Encoding.DER))

    _log(log_file, "TLS cert/key aangemaakt in runtime/tls/.")
    return paths.crt, paths.key


def trust_cert_current_user_windows(project_dir: Path, *, log_file: Path) -> bool:
    """
    Try to trust the cert for the current user (no admin) using:
      certutil -user -addstore Root localhost.cer
    If your org blocks this by policy, Edge will still show a warning.
    """
    if os.name != "nt":
        _log(log_file, "Niet-Windows: trust import overgeslagen.")
        return False

    paths = get_tls_paths(project_dir)
    if not paths.cer.exists():
        _log(log_file, "localhost.cer ontbreekt -> kan niet importeren in trust store.")
        return False

    cmd = ["certutil", "-user", "-addstore", "Root", str(paths.cer)]
    _log(log_file, f"Trust import: {' '.join(cmd)}")

    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.stdout.strip():
            _log(log_file, p.stdout.strip())
        if p.stderr.strip():
            _log(log_file, "[STDERR] " + p.stderr.strip())
        _log(log_file, f"Trust import returncode={p.returncode}")
        return p.returncode == 0
    except Exception as e:
        _log(log_file, f"[ERROR] certutil faalde: {e}")
        return False
