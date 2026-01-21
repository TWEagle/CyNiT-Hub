
# tools/token2dcb.py
"""
Token DCBaaS – client credentials token tool (hybride: Hub + standalone)

UI/Styling
- Eigen assets: /static/css/token2dcb.css en /static/js/token2dcb.js
- Hoofdknop is prominente 'hero' button; Health gebruikt identieke rode variant
- Loading overlay à la VOICA1 (full-screen, bewegende balk)

Gedrag
- Eén radiogroep (Prod / T&I / Dev) stuurt zowel:
  * OP-base voor token (Prod → authenticatie.vlaanderen.be/op; T&I/Dev → authenticatie-ti.vlaanderen.be/op)
  * API-base voor health (Prod → extapi.dcb.vlaanderen.be; T&I → extapi.dcb-ti.vlaanderen.be; Dev → extapi.dcb-dev.vlaanderen.be)
- Token: client_credentials, audience = kid uit JWK (upload of vault), issuer = audience (kid)
- client_assertion_type = urn:ietf:params:oauth:client-assertion-type:jwt-bearer
- client_assertion = lokaal (iss=sub=aud_kid; iat/exp)
- scope = user input + 8 vaste DCBaaS scopes
- Health check: ZONDER Authorization (publieke GET {API_BASE}/health) + tabel met bollekes (glow)
- Standalone: http://127.0.0.1:5006/token2dcb
"""
from __future__ import annotations

import json
import time
import uuid
import base64
import os
import pathlib
from typing import Dict, Tuple, Any, Optional, List

from flask import Flask, request, url_for, abort, Response, jsonify

# =========================
# Korte token-cache voor download
# =========================
TOKENS: Dict[str, str] = {}

# =========================
# OP-bases (whitelist) + suffix
# =========================
OP_BASES = [
    "https://authenticatie.vlaanderen.be/op",
    "https://authenticatie-ti.vlaanderen.be/op",
]
TOKEN_SUFFIX = "/v1/token"

# =========================
# Environments → OP & API mapping
# Dev gebruikt TI-OP maar eigen API
# =========================
ENV_OP_BASE = {
    "prod": "https://authenticatie.vlaanderen.be/op",
    "ti":   "https://authenticatie-ti.vlaanderen.be/op",
    "dev":  "https://authenticatie-ti.vlaanderen.be/op",
}
ENV_API_BASE = {
    "prod": "https://extapi.dcb.vlaanderen.be",
    "ti":   "https://extapi.dcb-ti.vlaanderen.be",
    "dev":  "https://extapi.dcb-dev.vlaanderen.be",
}

# =========================
# Configpaden
# =========================
CONFIG_DIR = os.environ.get("CONFIG_DIR", "config")
SCOPES_FILE = os.path.join(CONFIG_DIR, "token2dcb_scopes.json")
CLIENTS_FILE = os.path.join(CONFIG_DIR, "token2dcb_clients.json")  # optioneel
VAULT_FILE = os.path.join(CONFIG_DIR, "token2dcb_vault.json")     # kid -> {label, jwk}

# =========================
# Vaste scopes (worden altijd toegevoegd)
# =========================
ALWAYS_SCOPES = {
    "dvl_dcbaas_app_application_admin",
    "dvl_dcbaas_app_certificate_admin",
    "dvl_dcbaas_app_config_admin",
    "dvl_dcbaas_app_helpdesk",
    "dvl_dcbaas_info",
    "dvl_dcbaas_org_certificate_admin_organization",
    "dvl_dcbaas_org_workflow_operator",
    "vo_info",
}
SCOPES_DEFAULT_KEYS_STR = " ".join(sorted(ALWAYS_SCOPES))

# =========================
# JWK helpers / PyJWT
# =========================
try:
    import jwt  # PyJWT
    from jwt.algorithms import RSAAlgorithm, ECAlgorithm
except Exception as e:
    raise RuntimeError("PyJWT vereist. Installeer: pip install PyJWT cryptography") from e


def _ensure_config_dir() -> None:
    pathlib.Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)


def _load_scope_mapping() -> Dict[str, str]:
    p = pathlib.Path(SCOPES_FILE)
    if p.exists():
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            pass
    # Defaults met gebruiksvriendelijke labels
    return {
        "dvl_dcbaas_app_application_admin": "DCBaaS Beheer Toepassingen",
        "dvl_dcbaas_app_certificate_admin": "DCBaaS Beheer Certificaten",
        "dvl_dcbaas_app_config_admin": "DCBaaS Beheer Configuratie",
        "dvl_dcbaas_app_helpdesk": "DCBaaS Beheer Helpdesk",
        "dvl_dcbaas_info": "DCBaaS Informatie",
        "dvl_dcbaas_org_certificate_admin_organization": "DCBaaS Certificaatbeheerder Organisatie",
        "dvl_dcbaas_org_workflow_operator": "DCBaaS Workflowbeheerder",
        "vo_info": "VO Informatie",
    }


def _save_scope_mapping(mapping: Dict[str, str]) -> None:
    _ensure_config_dir()
    pathlib.Path(SCOPES_FILE).write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_clients_mapping() -> Dict[str, str]:
    p = pathlib.Path(CLIENTS_FILE)
    if p.exists():
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}


def _load_vault_raw() -> Dict[str, dict]:
    p = pathlib.Path(VAULT_FILE)
    if not p.exists():
        return {}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _load_vault_meta() -> Dict[str, dict]:
    raw = _load_vault_raw()
    # Alleen label naar de UI (geen JWK)
    return {kid: {"label": (raw.get(kid, {}) or {}).get("label", "key")} for kid in raw.keys()}


def _choose_alg_from_jwk(jwk_obj: dict) -> str:
    kty = jwk_obj.get("kty")
    if kty == "RSA":
        return "RS256"
    if kty == "EC":
        return {
            "P-256": "ES256", "secp256r1": "ES256",
            "P-384": "ES384", "secp384r1": "ES384",
            "P-521": "ES512", "secp521r1": "ES512",
        }.get(jwk_obj.get("crv", ""), "ES256")
    if kty == "oct":
        return "HS256"
    raise ValueError(f"Onbekende kty: {kty}")


def _key_from_jwk(jwk_json: str) -> Tuple[Any, str, dict]:
    jwk_obj = json.loads(jwk_json)
    alg = _choose_alg_from_jwk(jwk_obj)
    kty = jwk_obj.get("kty")
    if kty == "RSA":
        key = RSAAlgorithm.from_jwk(jwk_json)
    elif kty == "EC":
        key = ECAlgorithm.from_jwk(jwk_json)
    elif kty == "oct":
        k = jwk_obj.get("k")
        if not k:
            raise ValueError("oct (HMAC) JWK mist 'k' veld.")
        padding = "=" * (-len(k) % 4)
        key = base64.urlsafe_b64decode(k + padding)
    else:
        raise ValueError(f"Unsupported kty: {kty}")
    return key, alg, jwk_obj


# =========================
# Health helpers
# =========================
def _status_to_bool(val: Any) -> Optional[bool]:
    """Converteer gangbare health-strings/waarden naar booleans; None als onbekend."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    ok_vals = {"up", "ok", "healthy", "available", "true", "1", "pass", "passing", "green", "ready"}
    ko_vals = {"down", "error", "unhealthy", "unavailable", "false", "0", "fail", "failing", "red", "notready", "ko"}
    if s in ok_vals:
        return True
    if s in ko_vals:
        return False
    return None


def _flatten_health(obj: Any, prefix: str = "") -> List[Tuple[str, Any]]:
    """Maak 'dotted' keys met waarden, zodat we een vlakke tabel kunnen renderen."""
    out: List[Tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.extend(_flatten_health(v, key))
    elif isinstance(obj, list):
        for idx, v in enumerate(obj):
            key = f"{prefix}[{idx}]"
            out.extend(_flatten_health(v, key))
    else:
        out.append((prefix or "status", obj))
    return out


def _prettify_health_key(key: str) -> str:
    """
    Verwijder technische prefixen en toon compacte labels.
    - 'response.backend'  -> 'Backend'
    - 'response.database' -> 'Database'
    - 'response.es'       -> 'ES'
    - 'response.fwp'      -> 'FWP'
    - 'foo.bar.status'    -> 'Bar'
    - 'something_like_this' -> 'Something Like This'
    """
    # verwijder '.status' suffix
    if key.endswith(".status"):
        key = key[: -len(".status")]
    # strip generieke prefixes
    for pref in ("response.", "data."):
        if key.startswith(pref):
            key = key[len(pref):]
            break
    # neem laatste segment
    seg = key.split(".")[-1] if "." in key else key
    seg_norm = seg.replace("_", " ").replace("-", " ").strip()
    lower = seg_norm.lower()
    if lower == "es":
        return "ES"
    if lower == "fwp":
        return "FWP"
    if len(seg_norm) <= 3 and seg_norm.isalpha():
        return seg_norm.upper()
    return seg_norm[:1].upper() + seg_norm[1:]


def _render_health_table(health_json: Any) -> str:
    """
    Bouw een tabel met glowy bollekes:
    - groen (.tdcb-dot--ok) voor True/OK
    - rood  (.tdcb-dot--nok) voor False/KO
    - grijs (.tdcb-dot--unk) voor onbekend
    """
    rows = []
    flat = _flatten_health(health_json)
    flat.sort(key=lambda kv: (0 if kv[0].endswith("status") else 1, kv[0]))
    for key, val in flat:
        b = _status_to_bool(val)
        label = _prettify_health_key(key)
        if b is True:
            badge = "<span class='tdcb-dot tdcb-dot--ok'></span>"
            val_html = "<span class='muted'>OK</span>"
        elif b is False:
            badge = "<span class='tdcb-dot tdcb-dot--nok'></span>"
            val_html = "<span class='muted'>NOK</span>"
        else:
            badge = "<span class='tdcb-dot tdcb-dot--unk'></span>"
            val_html = f"<code>{str(val)}</code>"
        rows.append(
            f"<tr><td>{label}</td>"
            f"<td style='width:80px;text-align:center'>{badge}</td>"
            f"<td>{val_html}</td></tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='3'><em>Geen health-gegevens</em></td></tr>")
    return "<table><tr><th>Onderdeel</th><th>OK</th><th>Waarde</th></tr>" + "".join(rows) + "</table>"


# =========================
# UI rendering
# =========================
def _page(title: str, content_html: str) -> str:
    """
    Render via beheer.main_layout als die bestaat; anders fallback HTML die onze eigen CSS/JS laadt.
    """
    try:
        from beheer.main_layout import render_page  # type: ignore
        inject = (
            '<link rel="stylesheet" href="/static/css/token2dcb.css?v=1">'
            f"{content_html}"
            '<script src="/static/js/token2dcb.js?v=1"></script>'
        )
        return render_page(title=title, content_html=inject)
    except Exception:
        # Standalone fallback
        return (
            "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
            f"<title>{title}</title>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            '<link rel="stylesheet" href="/static/css/token2dcb.css?v=1">'
            "</head><body style='margin:16px;background:#000;color:#e8f2f2'>"
            f"{content_html}"
            '<script src="/static/js/token2dcb.js?v=1"></script>'
            "</body></html>"
        )


def _form(
    *,
    error: Optional[str] = None,
    result_json: Optional[str] = None,
    access_token: Optional[str] = None,
    scope_table_html: Optional[str] = None,
    health_table_html: Optional[str] = None,
    token_url: Optional[str] = None,
    token_download_url: Optional[str] = None,
    claims_json: Optional[str] = None,
    env_mode_value: str = "prod",
) -> str:
    # Header met heldere uitleg
    head = """
<div class="tdcb-panel">
  <h2 style="margin:0 0 6px 0;">Token DCBaaS</h2>
  <div class="muted">
    Vraag een toegangstoken aan via <b>client_credentials</b>.
    <code>kid</code> van je <code>JWK</code> gebruiken we als <b>audience</b> én als <b>issuer</b>.
    De <code>client_assertion</code> (JWT) maken we lokaal.
  </div>
</div>
"""

    # Één radiogroep voor token & health
    env_panel = f"""
<div class="tdcb-panel" style="margin-top:10px;">
  <div class="tdcb-row">
    <span class="tdcb-pill">Omgeving</span>

    <label class="tdcb-radio">
      <input type="radio" name="env_mode"
             value="prod"
             data-op="{ENV_OP_BASE['prod']}"
             data-api="{ENV_API_BASE['prod']}"
             {'checked' if env_mode_value=='prod' else ''}>
      <span>Productie</span>
    </label>

    <label class="tdcb-radio">
      <input type="radio" name="env_mode"
             value="ti"
             data-op="{ENV_OP_BASE['ti']}"
             data-api="{ENV_API_BASE['ti']}"
             {'checked' if env_mode_value=='ti' else ''}>
      <span>Test &amp; Integratie (T&amp;I)</span>
    </label>

    <label class="tdcb-radio">
      <input type="radio" name="env_mode"
             value="dev"
             data-op="{ENV_OP_BASE['dev']}"
             data-api="{ENV_API_BASE['dev']}"
             {'checked' if env_mode_value=='dev' else ''}>
      <span>Dev</span>
    </label>
  </div>
</div>
"""

    # Token & inputs (alle inputs hebben form="tdcb-form")
    inputs_block = r"""
<div class="tdcb-panel">

  <input type="hidden" id="op_base_tkn" name="op_base" value="" form="tdcb-form">

  <div class="tdcb-grid2">
    <div>
      <label class="tdcb-label">Sleutel‑ID (kid)</label>
      <input class="tdcb-inp" id="aud_kid" name="aud_kid" type="text" required
             placeholder="Wordt automatisch ingevuld na JWK‑upload of keuze in sleutelkluis…" form="tdcb-form">
    </div>
    <div>
      <label class="tdcb-label">Issuer (zelfde als Sleutel‑ID)</label>
      <div class="tdcb-row">
        <input class="tdcb-inp" id="issuer" name="issuer" type="text" required
               placeholder="Wordt automatisch gelijk gezet aan de Sleutel‑ID (kid)" form="tdcb-form">
        <button id="issuerLockBtn" class="tdcb-btn tdcb-btn--lite" type="button"
                title="Vergrendel/Ontgrendel issuer">
          🔓 Vergrendel
        </button>
      </div>
    </div>
  </div>

  <div class="tdcb-grid2" style="margin-top:10px;">
    <div>
      <label class="tdcb-label">Extra scopes (optioneel)</label>
      <input class="tdcb-inp" id="scope" name="scope" type="text"
             placeholder="Optioneel: extra toegangsrechten (spatie‑gescheiden). 8 DCBaaS‑scopes voegen we altijd toe."
             form="tdcb-form">
    </div>
    <div>
      <label class="tdcb-label">Privésleutel (JWK‑bestand)</label>
      <input class="tdcb-file" id="private_jwk" name="private_jwk"
             type="file" accept=".jwk,application/json" form="tdcb-form">
    </div>
  </div>

  <div style="margin-top:10px;">
    <label class="tdcb-label">Sleutelkluis (opgeslagen JWK’s)</label>
    <select class="tdcb-select" id="vault" name="vault" form="tdcb-form">
      <option value="">-- Kies een opgeslagen sleutel --</option>
    </select>
  </div>

  <!-- Knoppenrij: twee aparte forms naast elkaar (geen required-blokkering voor health) -->
  <div class="tdcb-row" style="margin-top:14px; gap:12px; align-items:center; flex-wrap:wrap;">

    <!-- TOKEN: klein form met alleen submit; inputs zijn via form="tdcb-form" gekoppeld -->
    <form id="tdcb-form" method="post" action="/token2dcb" enctype="multipart/form-data" style="display:inline">
      <button id="submitBtn" type="submit" class="tdcb-btn tdcb-btn--hero" title="Vraagt een toegangstoken aan">
        ⚡ Genereer &amp; Vraag Token
      </button>
    </form>

    <!-- HEALTH: eigen mini-form (géén required) -->
    <form id="tdcb-health-form" method="post" action="/token2dcb/health" style="display:inline">
      <input type="hidden" id="op_base_hlt"  name="op_base"  value="">
      <input type="hidden" id="api_base_hlt" name="api_base" value="">
      <button id="healthBtn" type="submit" class="tdcb-btn tdcb-btn--hero-danger"
              formnovalidate title="Publieke GET /health, geen token vereist">
        ❤️ Health check
      </button>
    </form>

  </div>
</div>
"""

    # Overlay
    overlay = """
<div id="tdcb-progress-overlay">
  <div class="tdcb-progress-box">
    <div class="tdcb-progress-title" id="tdcb-progress-text">Bezig met verwerken…</div>
    <div class="tdcb-progress-bar-outer"><div class="tdcb-progress-bar-inner"></div></div>
    <div class="muted" style="margin-top:10px;">Even geduld…</div>
  </div>
</div>
"""

    # Tabs containers
    tabs = """
<div class="tdcb-tabs">
  <button class="tdcb-tab-btn active" data-tab="tab-result">Resultaat</button>
  <button class="tdcb-tab-btn" data-tab="tab-claims">Claims</button>
  <button class="tdcb-tab-btn" data-tab="tab-scopes">Scopes</button>
</div>

<div id="tab-result" class="tdcb-tab active">__RESULT_TAB__</div>
<div id="tab-claims" class="tdcb-tab">__CLAIMS_TAB__</div>
<div id="tab-scopes" class="tdcb-tab">__SCOPES_TAB__</div>
"""

    # Result-tab content
    parts: List[str] = []
    if error:
        parts.append(f"<div class='tdcb-banner-error'><b>⚠️</b> {error}</div>")

    # Token blok
    if access_token:
        token_block = (
            "<div class='tdcb-download'>"
            "<span class='tdcb-pill'>Access Token</span> "
            f"<span id='accessTokenText' class='tdcb-pill' style='border-radius:12px'>{access_token}</span>"
            "<button id='copyTokenBtn' class='tdcb-btn tdcb-btn--lite' type='button' "
            "onclick=\"tdcbCopyById('accessTokenText','copyTokenBtn','Gekopieerd ✔')\">📋 Kopieer token</button>"
            "<button class='tdcb-btn tdcb-btn--lite' type='button' data-toggle-target='accessTokenText' "
            "data-show='Toon token' data-hide='Verberg token'>Verberg token</button>"
        )
        if token_download_url:
            token_block += (
                f" <a class='tdcb-btn tdcb-btn--lite' href='{token_download_url}' "
                "download='access_token.txt'>⬇️ Download</a>"
            )
        token_block += "</div>"
    else:
        token_block = (
            "<div class='tdcb-download'>"
            "<span class='tdcb-pill'>Access Token</span> <span class='tdcb-pill'>-</span>"
            "<button class='tdcb-btn tdcb-btn--lite' type='button' disabled>📋 Kopieer token</button>"
            "<button class='tdcb-btn tdcb-btn--lite' type='button' disabled>Toon token</button>"
            "</div>"
        )
    parts.append(token_block)

    # Scopes direct onder token
    if scope_table_html:
        parts.append(
            "<div class='tdcb-row' style='margin-top:6px;'>"
            "<button class='tdcb-btn tdcb-btn--lite' type='button' data-toggle-target='scopesTableTop' "
            "data-show='Toon scope‑overzicht' data-hide='Verberg scope‑overzicht'>Verberg scope‑overzicht</button>"
            "</div>"
            f"<div id='scopesTableTop'>{scope_table_html}</div>"
        )

    # Health statuspaneel
    if health_table_html:
        parts.append(
            "<div class='tdcb-row' style='margin-top:6px;'>"
            "<button class='tdcb-btn tdcb-btn--lite' type='button' data-toggle-target='healthPanelTop' "
            "data-show='Toon health‑overzicht' data-hide='Verberg health‑overzicht'>Verberg health‑overzicht</button>"
            "</div>"
            f"<div id='healthPanelTop'>{health_table_html}</div>"
        )

    # Token URL
    if token_url:
        parts.append(f"<div class='muted' style='margin-top:6px;'>Token URL: <code>{token_url}</code></div>")

    # Result JSON
    if result_json:
        parts.append(
            "<div class='tdcb-row' style='margin-top:8px;'>"
            "<button class='tdcb-btn tdcb-btn--lite' type='button' data-toggle-target='jsonPanel' "
            "data-show='Toon JSON' data-hide='Verberg JSON'>Verberg JSON</button>"
            "</div>"
            f"<div id='jsonPanel'><pre>{result_json}</pre></div>"
        )

    result_tab = "\n".join(parts)

    # Claims tab
    if claims_json:
        claims_tab = (
            "<div class='tdcb-download'>"
            "<button id='copyClaimsBtn' class='tdcb-btn tdcb-btn--lite' type='button' "
            "onclick=\"tdcbCopyById('claimsText','copyClaimsBtn','Claims gekopieerd ✔')\">📋 Copy claims</button>"
            "</div>"
            f"<div id='claimsPanel'><pre id='claimsText'>{claims_json}</pre></div>"
        )
    else:
        claims_tab = "<p class='muted'>Geen claims beschikbaar. Vraag eerst een token aan.</p>"

    # Scopes tab
    scopes_section: List[str] = []
    if scope_table_html:
        scopes_section.append(
            "<div class='tdcb-row'>"
            "<button class='tdcb-btn tdcb-btn--lite' type='button' data-toggle-target='scopesTable' "
            "data-show='Toon scope‑overzicht' data-hide='Verberg scope‑overzicht'>Verberg scope‑overzicht</button>"
            "</div>"
            f"<div id='scopesTable'>{scope_table_html}</div>"
        )
    scopes_section.append(
        "<div class='tdcb-row'>"
        "<button class='tdcb-btn tdcb-btn--lite' type='button' data-toggle-target='stdScopes' "
        "data-show='Toon standaard-scopekeys' data-hide='Verberg standaard-scopekeys'>Toon standaard-scopekeys</button>"
        "</div>"
        f"<div id='stdScopes' class='hidden'><pre>{SCOPES_DEFAULT_KEYS_STR}</pre></div>"
    )
    scopes_section.append(
        "<div class='tdcb-row'>"
        "<button class='tdcb-btn tdcb-btn--lite' type='button' data-toggle-target='scopesEditorWrap' "
        "data-show='Toon scope‑mapping' data-hide='Verberg scope‑mapping'>Toon scope‑mapping</button>"
        "</div>"
        "<div id='scopesEditorWrap' class='hidden'>"
        "<p class='muted'>Bewerkt bestand: <code>config/token2dcb_scopes.json</code></p>"
        "<textarea id='scopesEditor' class='tdcb-inp' rows='12' style='font-family:ui-monospace,Consolas,Menlo,monospace'></textarea>"
        "</div>"
    )
    scopes_tab = "\n".join(scopes_section)

    # Inline JS: radiogroep → hidden inputs + overlay hooks
    inline_js = """
<script>
(function(){
  function activeEnvRadio(){
    return document.querySelector('input[name="env_mode"]:checked');
  }
  function applyEnv(rad){
    if(!rad) return;
    var op  = rad.getAttribute('data-op');
    var api = rad.getAttribute('data-api');
    // zet hidden inputs voor BEIDE forms
    var opT = document.getElementById('op_base_tkn');
    var opH = document.getElementById('op_base_hlt');
    var apH = document.getElementById('api_base_hlt');
    if(opT) opT.value = op;
    if(opH) opH.value = op;
    if(apH) apH.value = api;
    // titel voor health-knop
    var hb = document.getElementById('healthBtn');
    if(hb) hb.title = 'GET ' + api + '/health';
  }
  // init + listeners
  applyEnv(activeEnvRadio());
  document.querySelectorAll('input[name="env_mode"]').forEach(function(r){
    r.addEventListener('change', function(){ applyEnv(r); });
  });

  // Issuer lock/unlock
  (function(){
    var issuerEl = document.getElementById('issuer');
    var issuerLockBtn = document.getElementById('issuerLockBtn');
    function setIssuerLocked(locked){
      if(!issuerEl || !issuerLockBtn) return;
      issuerEl.readOnly = !!locked;
      issuerEl.classList.toggle('ro', !!locked);
      issuerLockBtn.textContent = locked ? '🔒 Ontgrendel' : '🔓 Vergrendel';
      issuerLockBtn.title = locked ? 'Ontgrendel issuer' : 'Vergrendel issuer';
    }
    issuerLockBtn?.addEventListener('click', ()=> setIssuerLocked(!issuerEl.readOnly));
    setIssuerLocked(false);
  })();

  // Vault dropdown vullen
  (async function(){
    try{
      const res = await fetch('/token2dcb/vault.json',{cache:'no-store'});
      if(!res.ok) return;
      const vault = await res.json();
      const sel = document.getElementById('vault');
      if(!sel) return;
      Object.keys(vault).sort().forEach(kid=>{
        const opt = document.createElement('option');
        const label = (vault[kid] && vault[kid].label) ? vault[kid].label : 'key';
        opt.value = kid; opt.textContent = `${kid} (${label})`;
        sel.appendChild(opt);
      });
    }catch(e){}
  })();

  // Vault keuze → audience/issuer
  document.getElementById('vault')?.addEventListener('change', (ev)=>{
    const kid = ev.target.value; if(!kid) return;
    const audKid = document.getElementById('aud_kid');
    const issuer = document.getElementById('issuer');
    if(audKid) audKid.value = kid;
    if(issuer){ issuer.value = kid; issuer.readOnly = true; }
    const f = document.getElementById('private_jwk'); if(f) f.value = "";
  });

  // JWK upload → aud_kid & issuer vullen
  (function(){
    const jwkInput = document.getElementById('private_jwk');
    const audKid = document.getElementById('aud_kid');
    const issuer = document.getElementById('issuer');
    jwkInput?.addEventListener('change', ()=>{
      const f = jwkInput.files && jwkInput.files[0]; if(!f) return;
      const r = new FileReader();
      r.onload = e=>{
        try{
          const jwk = JSON.parse(String(e.target.result||'{}'));
          if(jwk.kid) audKid.value = jwk.kid;
          if(audKid.value){ issuer.value = audKid.value; issuer.readOnly = true; }
        }catch{}
      };
      r.readAsText(f,'utf-8');
    });
  })();

  // Loading overlay + busy-state
  (function(){
    const tForm = document.getElementById('tdcb-form');
    const hForm = document.getElementById('tdcb-health-form');
    const tBtn  = document.getElementById('submitBtn');
    const hBtn  = document.getElementById('healthBtn');
    if(tForm && tBtn){
      tForm.addEventListener('submit', ()=>{
        try{
          tBtn.classList.add('is-busy');
          tBtn.setAttribute('disabled','disabled');
          if(window.tdcbShowProgress) tdcbShowProgress('Token aanvragen… ');
        }catch(e){}
      });
    }
    if(hForm && hBtn){
      hForm.addEventListener('submit', ()=>{
        try{
          hBtn.classList.add('is-busy');
          hBtn.setAttribute('disabled','disabled');
          if(window.tdcbShowProgress) tdcbShowProgress('Health check… ');
        }catch(e){}
      });
    }
  })();
})();
</script>
"""

    # Tabs inhoud samenstellen
    body = head + env_panel + inputs_block + overlay + tabs + inline_js
    body = body.replace("__RESULT_TAB__", result_tab).replace("__CLAIMS_TAB__", claims_tab).replace("__SCOPES_TAB__", scopes_tab)
    return _page("Token DCBaaS", body)


# =========================
# Scopes rendering helper
# =========================

def _render_scope_table(scopes_space_sep: str, mapping: Dict[str, str]) -> str:
    """
    Rendert de scopes als tabel met glowing bollekes:
    - groen (.tdcb-dot--ok) wanneer scope aanwezig is
    - rood  (.tdcb-dot--nok) wanneer scope ontbreekt
    - grijs (.tdcb-dot--unk) voor niet-herkenbare/lege input
    """
    # Normaliseer: set met aangeleverde scope-keys
    scopes = set(s for s in (scopes_space_sep or "").split() if s.strip())

    rows = []
    # Bekende (gemapte) scopes
    for key, label in mapping.items():
        present = key in scopes
        dot = "<span class='tdcb-dot tdcb-dot--ok'></span>" if present else "<span class='tdcb-dot tdcb-dot--nok'></span>"
        rows.append(
            f"<tr>"
            f"<td>{label}</td>"
            f"<td style='width:80px;text-align:center'>{dot}</td>"
            f"</tr>"
        )

    # Overige (niet in mapping maar wel aangeleverd)
    extra = [s for s in sorted(scopes) if s not in mapping]
    extra_rows = ""
    if extra:
        extra_rows = (
            "<tr><th colspan='2'>Overige scopes (niet in mapping)</th></tr>"
            + "".join(
                "<tr>"
                f"<td><code>{s}</code></td>"
                "<td style='width:80px;text-align:center'><span class='tdcb-dot tdcb-dot--ok'></span></td>"
                "</tr>"
                for s in extra
            )
        )

    # Opbouw tabel; kolomheader ‘Aanwezig’ past bij de statusbol
    return (
        "<table>"
        "<tr><th>Betekenis</th><th>Aanwezig</th></tr>"
        + "".join(rows)
        + extra_rows
        + "</table>"
    )


# =========================
# Web routes
# =========================
def register_web_routes(app: Flask):
    @app.get("/token2dcb")
    def token2dcb_index():
        return _form()

    @app.post("/token2dcb")
    def token2dcb_post():
        try:
            issuer = (request.form.get("issuer") or "").strip()
            op_base = (request.form.get("op_base") or "").strip()
            aud_kid = (request.form.get("aud_kid") or "").strip()
            scope = (request.form.get("scope") or "").strip()
            vault_kid = (request.form.get("vault") or "").strip()

            jwk_json = ""
            if vault_kid:
                vault = _load_vault_raw()
                if vault_kid not in vault:
                    return _form(error="Sleutel niet in sleutelkluis gevonden."), 400
                jwk_json = json.dumps(vault[vault_kid].get("jwk", {}), ensure_ascii=False)
            else:
                f = request.files.get("private_jwk")
                if not f or not f.filename:
                    return _form(error="Upload een privésleutel (JWK) of kies er één uit de sleutelkluis."), 400
                jwk_json = f.read().decode("utf-8")

            key, alg, jwk_obj = _key_from_jwk(jwk_json)

            # issuer = audience (kid)
            if not aud_kid:
                aud_kid = jwk_obj.get("kid") or ""
            if not aud_kid:
                return _form(error="Sleutel‑ID (kid) is verplicht. Upload/kies een JWK."), 400
            issuer = aud_kid

            if op_base not in OP_BASES:
                return _form(error="Onbekende omgeving. Kies Productie, T&I of Dev."), 400

            # client_assertion
            now = int(time.time())
            jwt_claims = {"iss": issuer, "sub": issuer, "aud": op_base, "iat": now, "exp": now + 600}
            client_assertion = jwt.encode(jwt_claims, key, algorithm=alg)

            token_url = op_base.rstrip("/") + TOKEN_SUFFIX

            # scopes: user + ALWAYS_SCOPES → één regel
            scopes_user = (scope or "").split()
            merged_scopes = " ".join(sorted(set(scopes_user) | ALWAYS_SCOPES))

            import requests
            resp = requests.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "audience": aud_kid,
                    "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                    "client_assertion": client_assertion,
                    "scope": merged_scopes,
                },
                headers={"Accept": "application/json"},
                timeout=30,
            )
            txt = resp.text
            try:
                data = resp.json()
            except Exception:
                data = {"_raw": txt}

            if resp.status_code >= 400:
                pretty = json.dumps(data, ensure_ascii=False, indent=2)
                return (
                    _form(
                        error=f"Token‑aanvraag faalde (HTTP {resp.status_code})",
                        result_json=pretty,
                        token_url=token_url,
                        claims_json=json.dumps(jwt_claims, ensure_ascii=False, indent=2),
                    ),
                    resp.status_code,
                )

            pretty = json.dumps(data, ensure_ascii=False, indent=2)
            access_token = data.get("access_token") or ""
            scopes_resp = data.get("scope") or ""

            token_id = str(uuid.uuid4())
            TOKENS[token_id] = access_token
            dl = url_for("token2dcb_download", token_id=token_id, _external=False)

            mapping = _load_scope_mapping()
            table_html = _render_scope_table(scopes_resp, mapping)

            return _form(
                error=None,
                result_json=pretty,
                access_token=access_token,
                scope_table_html=table_html,  # ook direct onder token
                token_url=token_url,
                token_download_url=dl,
                claims_json=json.dumps(jwt_claims, ensure_ascii=False, indent=2),
            )
        except Exception as e:
            return _form(error=f"Fout: {e}"), 400

    @app.post("/token2dcb/health")
    def token2dcb_health():
        """Publieke health: GET {API_BASE}/health (GEEN Authorization header)."""
        try:
            _ = (request.form.get("op_base") or "").strip()  # behouden voor consistentie
            api_base = (request.form.get("api_base") or "").strip()
            if not api_base:
                api_base = ENV_API_BASE["prod"]  # veilige fallback

            url = api_base.rstrip("/") + "/health"

            import requests
            resp = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
            txt = resp.text
            try:
                data = resp.json()
                pretty = json.dumps(data, ensure_ascii=False, indent=2)
            except Exception:
                data = {"status": txt}
                pretty = txt

            health_table = _render_health_table(data)
            banner = None if resp.ok else f"Health‑controle mislukt (HTTP {resp.status_code})"

            # render healthresultaat in Resultaat-tab; token-paneel ongemoeid laten
            return _form(
                error=banner,
                result_json=pretty,
                health_table_html=health_table,
            ), (200 if resp.ok else resp.status_code)

        except Exception as e:
            return _form(error=f"Health check fout: {e}"), 400

    @app.get("/token2dcb/scopes.json")
    def token2dcb_scopes_get():
        return jsonify(_load_scope_mapping())

    @app.post("/token2dcb/scopes.json")
    def token2dcb_scopes_post():
        try:
            body = request.get_json(force=True, silent=False)
            if not isinstance(body, dict):
                return jsonify({"error": "JSON object verwacht"}), 400
            for k, v in body.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    return jsonify({"error": "Alle keys/values moeten strings zijn."}), 400
            _save_scope_mapping(body)
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.get("/token2dcb/clients.json")
    def token2dcb_clients_get():
        return jsonify(_load_clients_mapping())

    @app.get("/token2dcb/vault.json")
    def token2dcb_vault_get():
        return jsonify(_load_vault_meta())

    @app.get("/token2dcb/download/<token_id>")
    def token2dcb_download(token_id: str):
        token = TOKENS.get(token_id, "")
        if not token:
            abort(404)
        return Response(
            token,
            mimetype="text/plain",
            headers={"Content-Disposition": 'attachment; filename="access_token.txt"'},
        )


# =========================
# Standalone
# =========================
if __name__ == "__main__":
    _ensure_config_dir()
    _app = Flask(
        "token2dcb_standalone",
        static_folder=str(pathlib.Path(__file__).resolve().parents[1] / "static"),
        static_url_path="/static",
    )
    register_web_routes(_app)
    print("Token DCBaaS standalone draait op: http://127.0.0.1:5006/token2dcb")
    _app.run("127.0.0.1", 5006, debug=True)
