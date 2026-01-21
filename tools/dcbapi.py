
# tools/dcbapi.py
"""
DCBaaS API Tool – Hub-stijl (Optie B) + standalone

Afgestemd op de perfect werkende token2dcb-flow:
- Eén radiogroep (Prod/T&I/Dev) zet zowel OP (token) als API (health/calls).
- Dev gebruikt TI-OP en Dev-API.
- Token via client_credentials; token + scopes in sessie en opgeslagen op disk (dcbapi/session_<id>/).
- Health-check is PUBLIEK (GEEN Authorization) en toont glowy-status tabel (Backend/Database/ES/FWP/…).
- Scopes-overzicht verschijnt direct onder de token (glowy dot-tabel) + tooltip blijft.
- Endpoints-editor en dynamische request-UI blijven behouden.
"""
from __future__ import annotations
import os, json, time, uuid, base64, pathlib
from typing import Dict, Any, Optional, Tuple, List
from flask import Flask, request, abort, Response, jsonify

# ---------- Sessies ----------
SESSIONS: Dict[str, Dict[str, Any]] = {}

# ---------- OP / API settings (in lijn met token2dcb) ----------
OP_BASES = {
    "prod": "https://authenticatie.vlaanderen.be/op",
    "ti":   "https://authenticatie-ti.vlaanderen.be/op",
    "dev":  "https://authenticatie-ti.vlaanderen.be/op",   # Dev gebruikt TI-OP
}
API_BASES = {
    "prod": "https://extapi.dcb.vlaanderen.be",
    "ti":   "https://extapi.dcb-ti.vlaanderen.be",
    "dev":  "https://extapi.dcb-dev.vlaanderen.be",
}
TOKEN_SUFFIX = "/v1/token"

# ---------- Configpaden ----------
CONFIG_DIR     = os.environ.get("CONFIG_DIR", "config")
DATA_DIR       = os.environ.get("DCBAPI_DATA_DIR", "dcbapi")
SCOPES_FILE    = os.path.join(CONFIG_DIR, "token2dcb_scopes.json")
VAULT_FILE     = os.path.join(CONFIG_DIR, "token2dcb_vault.json")
ENDPOINTS_FILE = os.path.join(CONFIG_DIR, "dcbapi_endpoints.json")

# Altijd toe te voegen DCBaaS scopes
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

# ---------- Helpers: bestanden/config ----------
def _ensure_dir(p: str) -> None:
    pathlib.Path(p).mkdir(parents=True, exist_ok=True)

def _ensure_config_dir() -> None:
    _ensure_dir(CONFIG_DIR)

def _ensure_data_dir() -> None:
    _ensure_dir(DATA_DIR)

def _session_dir(session_id: str) -> str:
    d = os.path.join(DATA_DIR, f"session_{session_id}")
    _ensure_dir(d)
    return d

def _save_file(path: str, content: str) -> None:
    pathlib.Path(path).write_text(content, encoding="utf-8")

def _load_json_object(path: str, default: dict) -> dict:
    p = pathlib.Path(path)
    if not p.exists():
        return default
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else default
    except Exception:
        return default

def _load_scope_mapping() -> Dict[str, str]:
    default = {
        "dvl_dcbaas_app_application_admin":            "DCBaaS Beheer Toepassingen",
        "dvl_dcbaas_app_certificate_admin":            "DCBaaS Beheer Certificaten",
        "dvl_dcbaas_app_config_admin":                 "DCBaaS Beheer Configuratie",
        "dvl_dcbaas_app_helpdesk":                     "DCBaaS Beheer Helpdesk",
        "dvl_dcbaas_info":                             "DCBaaS Informatie",
        "dvl_dcbaas_org_certificate_admin_organization":"DCBaaS Certificaatbeheerder Organisatie",
        "dvl_dcbaas_org_workflow_operator":            "DCBaaS Workflowbeheerder",
        "vo_info":                                     "VO Info",
    }
    return _load_json_object(SCOPES_FILE, default)

def _save_scope_mapping(mapping: Dict[str, str]) -> None:
    _ensure_config_dir()
    _save_file(SCOPES_FILE, json.dumps(mapping, ensure_ascii=False, indent=2))

def _load_vault_raw() -> Dict[str, dict]:
    return _load_json_object(VAULT_FILE, {})

def _load_vault_meta() -> Dict[str, dict]:
    raw = _load_vault_raw()
    return {kid: {"label": (raw.get(kid, {}) or {}).get("label", "key")} for kid in raw.keys()}

def _load_endpoints() -> Dict[str, dict]:
    default = {"health": {"method": "GET", "path": "/health", "description": "Health check"}}
    return _load_json_object(ENDPOINTS_FILE, default)

def _save_endpoints(mapping: Dict[str, dict]) -> None:
    _ensure_config_dir()
    _save_file(ENDPOINTS_FILE, json.dumps(mapping, ensure_ascii=False, indent=2))

# ---------- JWK / JWT helpers ----------
try:
    import jwt  # PyJWT
    from jwt.algorithms import RSAAlgorithm, ECAlgorithm
except Exception as e:
    raise RuntimeError("PyJWT vereist. Installeer: pip install PyJWT cryptography") from e

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

# ---------- Health helpers (uit token2dcb) ----------
def _status_to_bool(val: Any) -> Optional[bool]:
    """Converteer gangbare health-waarden naar booleans; None als onbekend."""
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
    """Maak 'dotted' keys met values voor tabelweergave."""
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
    if key.endswith(".status"):
        key = key[: -len(".status")]
    for pref in ("response.", "data."):
        if key.startswith(pref):
            key = key[len(pref):]
            break
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
    rows: List[str] = []
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
            f"<tr><td>{label}</td><td style='width:80px;text-align:center'>{badge}</td><td>{val_html}</td></tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='3'><em>Geen health-gegevens</em></td></tr>")
    return "<table><tr><th>Onderdeel</th><th>OK</th><th>Waarde</th></tr>" + "".join(rows) + "</table>"

# ---------- Scopes rendering ----------
def _render_scope_table(scopes_space_sep: str, mapping: Dict[str, str]) -> str:
    scopes = set(s for s in (scopes_space_sep or "").split() if s.strip())
    rows = []
    for key, label in mapping.items():
        present = key in scopes
        dot = "<span class='tdcb-dot tdcb-dot--ok'></span>" if present else "<span class='tdcb-dot tdcb-dot--nok'></span>"
        rows.append(f"<tr><td>{label}</td><td style='width:80px;text-align:center'>{dot}</td></tr>")
    extra = [s for s in sorted(scopes) if s not in mapping]
    extra_rows = ""
    if extra:
        extra_rows = (
            "<tr><th colspan='2'>Overige scopes (niet in mapping)</th></tr>"
            + "".join(
                "<tr><td><code>{}</code></td><td style='width:80px;text-align:center'><span class='tdcb-dot tdcb-dot--ok'></span></td></tr>".format(s)
                for s in extra
            )
        )
    return "<table><tr><th>Betekenis</th><th>Aanwezig</th></tr>" + "".join(rows) + extra_rows + "</table>"

# ---------- UI rendering ----------
def _page(title: str, body_html: str) -> str:
    """Render via beheer.main_layout als beschikbaar; anders minimal fallback."""
    try:
        from beheer.main_layout import render_page  # type: ignore
        return render_page(title=title, content_html=body_html)
    except Exception:
        return (
            "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
            f"<title>{title}</title><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "</head><body>" + body_html + "</body></html>"
        )

def _form(
    error: Optional[str] = None,
    info: Optional[str] = None,
    result_json: Optional[str] = None,
    access_token: Optional[str] = None,
    token_url: Optional[str] = None,
    session_id: Optional[str] = None,
    scopes_embed: Optional[str] = None,
    scope_table_html: Optional[str] = None,
    health_table_html: Optional[str] = None,
) -> str:
    token_url_block = f"<div class='muted'>Token URL: <code>{token_url}</code></div>" if token_url else ""
    token_text   = access_token or "-"
    copy_disabled = "disabled" if not access_token else ""
    run_disabled  = "disabled" if not access_token else ""
    download_html = f"<a class='btn' href='/dcbapi/download/{session_id}/access_token' download='access_token.txt'>Download token</a>" if (session_id and access_token) else ""
    result_block = (
        "<details open><summary>Resultaat JSON</summary><pre style='overflow:auto'>__RESULT_JSON__</pre></details>"
        if result_json else
        "<details><summary>Resultaat JSON</summary><div class='muted'>Nog geen resultaat</div></details>"
    )

    # Statische styles (met glowy dots) – geen f-string om { } veilig te houden
    styles = """
<style>
  body{background:#000;color:#e8f2f2}
  .muted{color:rgba(255,255,255,.75)}
  .btn{padding:8px 12px;border-radius:10px;border:1px solid rgba(255,255,255,.18);background:#0b1016;color:#e7f3f3;font-weight:800;cursor:pointer}
  .btn[disabled]{opacity:.6;cursor:not-allowed}
  .in{padding:8px 10px;border-radius:10px;border:1px solid rgba(255,255,255,.18);background:#0b1016;color:#e7f3f3;min-width:120px}
  .pill{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:999px;border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.04);font-weight:800}
  .hidden{display:none !important}
  table{border-collapse:collapse;width:100%;margin-top:8px}
  th,td{border:1px solid rgba(255,255,255,.18);padding:8px 10px}
  th{text-align:left;background:rgba(255,255,255,.06)}
  .error{margin:8px 0;padding:10px 12px;border-radius:12px;border:1px solid rgba(255,80,80,.35);background:rgba(255,80,80,.06)}
  /* glowy dots */
  .tdcb-dot{display:inline-block;width:16px;height:16px;border-radius:50%;margin:auto;box-shadow:0 0 6px rgba(0,0,0,.4),2px 2px 4px rgba(0,0,0,.6)}
  .tdcb-dot--ok{background:#24d65a;box-shadow:0 0 6px rgba(36,214,90,.7),0 0 12px rgba(36,214,90,.6),2px 2px 4px rgba(0,0,0,.6)}
  .tdcb-dot--nok{background:#ff3030;box-shadow:0 0 6px rgba(255,50,50,.7),0 0 12px rgba(255,50,50,.6),2px 2px 4px rgba(0,0,0,.6)}
  .tdcb-dot--unk{background:#bbb;box-shadow:0 0 6px rgba(200,200,200,.5),2px 2px 4px rgba(0,0,0,.5)}
</style>
"""

    # Groot HTML/JS-blok met placeholders (GEEN f-string!)
    body = """
{STYLES}
<div class="dcbapi" style="padding:10px;border-radius:12px">
  {ERROR_BLOCK}{INFO_BLOCK}

  <!-- Top toolbar / Token -->
  <section>
    <form id="tokenForm" method="post" action="/dcbapi/token/generate" enctype="multipart/form-data">
      <input type="hidden" name="session_id" id="session_id" value="__SESSION_ID__">
      <div class="toolbar" style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;position:relative">

        <!-- ÉÉN OMGEVINGSSELECTIE -->
        <div style="display:flex;gap:10px;align-items:center;">
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
            <input type="radio" name="env_radio" value="prod" checked> Productie
          </label>
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
            <input type="radio" name="env_radio" value="ti"> T&amp;I
          </label>
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
            <input type="radio" name="env_radio" value="dev"> Dev
          </label>
          <!-- Hidden OP/API base voor token + health -->
          <input type="hidden" id="op_base" name="op_base" value="">
          <input type="hidden" id="api_base" name="api_base" value="">
          <span id="envBadge" class="pill" style="margin-left:6px;">Env: Prod</span>
        </div>

        <!-- Token URL -->
        <div id="tokenUrlBox" style="min-width:260px;">__TOKEN_URL_BLOCK__</div>

        <!-- Scopes input -->
        <div style="display:flex;gap:6px;align-items:center;min-width:260px;">
          <label for="scope" class="muted">extra scopes</label>
          <input class="in" id="scope" name="scope" type="text" placeholder="spatie-gescheiden; vaste DCBaaS scopes worden toegevoegd">
        </div>

        <!-- JWK upload en Vault -->
        <div style="display:flex;gap:8px;align-items:center;min-width:300px;">
          <input class="in" id="private_jwk" name="private_jwk" type="file" accept=".jwk,application/json" />
          <select class="in" id="vault" name="vault">
            <option value="">-- Kies uit opgeslagen JWK’s --</option>
          </select>
        </div>

        <!-- Genereer token -->
        <button id="genTokenBtn" class="btn" type="submit">Genereer token</button>

        <!-- Health (publiek) via apart form) -->
        <form id="dcbapi-health-form" method="post" action="/dcbapi/health" style="display:inline">
          <input type="hidden" id="op_base_hlt" name="op_base" value="">
          <input type="hidden" id="api_base_hlt" name="api_base" value="">
          <button id="healthBtn" class="btn" type="submit" formnovalidate title="Publieke GET /health">Health</button>
        </form>

        <!-- Tokenstatus + scopes -->
        <div id="tokenStatus" style="display:flex;gap:8px;align-items:center;position:relative">
          <span class="pill" id="accessTokenText">__ACCESS_TOKEN__</span>
          <span id="tokenLight" class="pill" style="display:inline-flex;align-items:center;gap:6px;">
            <span id="tokenDot" style="width:10px;height:10px;border-radius:50%;background:#666;box-shadow:0 0 6px #333;"></span>
            <span id="tokenLabel">Geen token</span>
          </span>
          <button id="copyTokenBtn" class="btn" type="button" __COPY_DISABLED__>Kopieer</button>
          <button class="btn" type="button" id="toggleTokenBtn" __COPY_DISABLED__>Toon token</button>
          __DOWNLOAD_HTML__

          <!-- Scopes: knop + tooltip -->
          <button id='scopeTooltipBtn' class='btn' type='button' title='Toon scopes'>Scopes</button>
          <div id='scopeTooltipPanel' class='hidden' role='dialog' aria-label='Scopes in token'
               style='position:absolute; right:0; top:100%; min-width:320px; max-width:520px; z-index:100;
                      display:none; background:rgba(0,0,0,0.9); border:1px solid rgba(255,255,255,.14);
                      border-radius:10px; padding:10px;'>
            <div id='scopeTooltipContent' style='max-height:340px; overflow:auto;'></div>
          </div>
        </div>
      </div>

      <!-- Audience/Issuer -->
      <div style="display:flex;gap:10px;align-items:center;margin-top:6px;flex-wrap:wrap;">
        <div style="display:flex;gap:6px;align-items:center;">
          <label for="aud_kid" class="muted">Audience (kid)</label>
          <input class="in" id="aud_kid" name="aud_kid" type="text" required placeholder="vult na JWK of Vault">
        </div>
        <div style="display:flex;gap:6px;align-items:center;">
          <label for="issuer" class="muted">Issuer</label>
          <input class="in" id="issuer" name="issuer" type="text" required placeholder="= kid" />
          <button id="issuerLockBtn" class="btn" type="button" title="Vergrendel/Ontgrendel issuer">🔓</button>
        </div>
        <div id="progressGen" class="hidden" style="height:4px;flex:1;background:rgba(255,255,255,.08);border-radius:3px;">
          <div id="progressGenBar" style="height:100%;width:0;background:linear-gradient(90deg,#37ffe2,#10b8ff);"></div>
        </div>
      </div>
    </form>
  </section>

  <!-- Scopes-tabel direct onder token -->
  {SCOPES_TOP}

  <!-- Health-resultaat (publiek) -->
  {HEALTH_TOP}

  <!-- Result JSON -->
  <section style="margin-top:12px;">
    __RESULT_BLOCK__
  </section>

  <!-- API-calls -->
  <section style="margin-top:16px;">
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
      <!-- API base (readonly) -->
      <div style="display:flex;gap:6px;align-items:center;min-width:320px;">
        <label for="api_base_visible" class="muted">API base</label>
        <input class="in" id="api_base_visible" type="text" readonly title="Wordt automatisch door 'Omgeving' gezet">
      </div>

      <!-- Operatie-select -->
      <div style="display:flex;gap:6px;align-items:center;position:relative;">
        <label for="op_select" class="muted">Operatie</label>
        <div class="select-wrap" style="position:relative;display:inline-block;">
          <select class="in" id="op_select" style="padding-right:34px;"></select>
          <span aria-hidden="true"
                style="position:absolute; right:10px; top:50%; transform:translateY(-50%);
                       pointer-events:none; color:#a7b6b6; font-weight:800;">▾</span>
        </div>
      </div>

      <div id="progressCall" class="hidden" style="height:4px;flex:1;background:rgba(255,255,255,.08);border-radius:3px;">
        <div id="progressCallBar" style="height:100%;width:0;background:linear-gradient(90deg,#37ffe2,#10b8ff);"></div>
      </div>
    </div>

    <div id="dynWrap" style="margin-top:10px;">
      <div style="display:grid;grid-template-columns:220px 1fr;gap:10px;align-items:center;">
        <div class="lbl">Methode</div>
        <div>
          <select class="in" id="op_method">
            <option>GET</option><option>POST</option><option>PUT</option><option>PATCH</option><option>DELETE</option>
          </select>
        </div>
        <div class="lbl">Pad</div>
        <div><input class="in" id="op_path" type="text" value="/health"></div>
      </div>
      <div id="dynForm" style="display:grid;grid-template-columns:220px 1fr;gap:10px;align-items:center;margin-top:10px;">
        <!-- dynamische velden -->
      </div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap;">
        <button class="btn" id="toggleRawBtn" type="button">Toon Raw JSON</button>
        <button id="runBtn" class="btn" type="button" __RUN_DISABLED__>▶️ Uitvoeren</button>
        <button id="clearRespBtn" class="btn" type="button">Wissen</button>
        <a class="btn" href="/dcbapi/endpoints.json" target="_blank" rel="noopener">Open endpoints.json</a>
      </div>
      <textarea class="in hidden" id="op_body" rows="10" placeholder='{"voorbeeld":"waarde"}'></textarea>
      <div id="respPanel" style="margin-top:10px;"><pre id="respText">(geen response)</pre></div>
    </div>
  </section>

  <!-- Endpoints-beheer -->
  <section style="margin-top:16px;">
    <details>
      <summary>Endpoints beheren</summary>
      <div style="display:flex;gap:8px;align-items:center;margin:6px 0;">
        <button class="btn" id="loadEndpointsBtn" type="button">Herladen</button>
        <button class="btn" id="saveEndpointsBtn" type="button">Opslaan</button>
        <a class="btn" href="/dcbapi/endpoints.json" target="_blank" rel="noopener">Open JSON</a>
      </div>
      <textarea id="endpointsEditor" class="in" rows="16"></textarea>
    </details>
  </section>

  <!-- Logs -->
  <section style="margin-top:16px;">
    <details open>
      <summary>Logs</summary>
      <pre id="logBox" style="max-height:260px;overflow:auto;"></pre>
    </details>
  </section>
</div>

<script>
  // Helpers
  function setProgress(id, show, pct){
    const wrap = document.getElementById(id);
    const bar = wrap?.querySelector('div');
    if(!wrap || !bar) return;
    wrap.classList.toggle('hidden', !show);
    if(typeof pct === 'number') bar.style.width = Math.max(0, Math.min(100, pct)) + '%';
  }
  function log(s){
    const lb = document.getElementById('logBox');
    const ts = new Date().toISOString().replace('T',' ').replace('Z','');
    lb.textContent += `[${ts}] ${s}\n`;
    lb.scrollTop = lb.scrollHeight;
  }
  function setBtnGlow(btnId, status){ // 'ok' | 'ko' | 'idle'
    const el = document.getElementById(btnId);
    if(!el) return;
    if(status === 'ok'){ el.style.color = '#27d89d'; el.style.textShadow = '0 0 8px rgba(39,216,157,.95)'; }
    else if(status === 'ko'){ el.style.color = '#ff5566'; el.style.textShadow = '0 0 8px rgba(255,85,102,.9)'; }
    else { el.style.color = ''; el.style.textShadow = ''; }
  }

  // ÉÉN omgeving: OP & API in sync + badge
  function applyEnv(env){
    const OP_PROD  = "__OP_PROD__";
    const OP_TI    = "__OP_TI__";
    const OP_DEV   = "__OP_DEV__";
    const API_PROD = "__API_PROD__";
    const API_TI   = "__API_TI__";
    const API_DEV  = "__API_DEV__";
    const op  = (env === 'prod') ? OP_PROD : (env === 'ti' ? OP_TI : OP_DEV);
    const api = (env === 'prod') ? API_PROD : (env === 'ti' ? API_TI : API_DEV);
    const opEl  = document.getElementById('op_base');
    const apiEl = document.getElementById('api_base');
    const apiVis= document.getElementById('api_base_visible');
    const badge = document.getElementById('envBadge');
    const opHlt = document.getElementById('op_base_hlt');
    const apiHlt= document.getElementById('api_base_hlt');
    if(opEl)  opEl.value  = op;
    if(apiEl) apiEl.value = api;
    if(apiVis) apiVis.value = api;
    if(opHlt) opHlt.value = op;
    if(apiHlt) apiHlt.value = api;
    if(badge) badge.textContent = 'Env: ' + (env === 'prod' ? 'Prod' : (env === 'ti' ? 'T&I' : 'Dev'));
    setBtnGlow('healthBtn', 'idle');
    setBtnGlow('genTokenBtn', 'idle');
  }
  applyEnv('prod');
  document.querySelectorAll('input[name="env_radio"]').forEach(r=>{
    r.addEventListener('change', ev => applyEnv(ev.target.value));
  });

  // Issuer lock
  const issuerEl = document.getElementById('issuer');
  const issuerLockBtn = document.getElementById('issuerLockBtn');
  function setIssuerLocked(locked){
    issuerEl.readOnly = !!locked;
    issuerLockBtn.textContent = locked ? '🔒' : '🔓';
    issuerLockBtn.title = locked ? 'Ontgrendel issuer' : 'Vergrendel issuer';
  }
  issuerLockBtn?.addEventListener('click', ()=> setIssuerLocked(!issuerEl.readOnly));
  setIssuerLocked(false);

  // Upload JWK -> aud/issuer
  const jwkInput = document.getElementById('private_jwk');
  const audKid = document.getElementById('aud_kid');
  jwkInput?.addEventListener('change', ()=>{
    const f = jwkInput.files && jwkInput.files[0]; if(!f) return;
    const r = new FileReader();
    r.onload = e=>{
      try{
        const jwk = JSON.parse(String(e.target.result||'{}'));
        if(jwk.kid) audKid.value = jwk.kid;
        if(audKid.value){ issuerEl.value = audKid.value; setIssuerLocked(true); }
      }catch{}
    };
    r.readAsText(f,'utf-8');
  });

  // Vault dropdown
  async function loadVault(){
    try{
      const res = await fetch('/dcbapi/vault.json',{cache:'no-store'});
      if(!res.ok) return;
      const vault = await res.json();
      const sel = document.getElementById('vault');
      Object.keys(vault).sort().forEach(kid=>{
        const opt = document.createElement('option');
        const label = (vault[kid] && vault[kid].label) ? vault[kid].label : 'key';
        opt.value = kid; opt.textContent = `${kid} (${label})`;
        sel.appendChild(opt);
      });
    }catch(e){}
  }
  loadVault();
  document.getElementById('vault')?.addEventListener('change', (ev)=>{
    const kid = ev.target.value;
    if(!kid) return;
    audKid.value = kid; issuerEl.value = kid; setIssuerLocked(true);
    if(jwkInput) jwkInput.value = "";
  });

  // Token verkeerslicht + masking
  const accessTokenEl = document.getElementById('accessTokenText');
  const toggleTokenBtn = document.getElementById('toggleTokenBtn');
  function setTokenLight(hasToken){
    const dot = document.getElementById('tokenDot');
    const label = document.getElementById('tokenLabel');
    if(!dot || !label) return;
    if(hasToken){ dot.style.background='#27d89d'; dot.style.boxShadow='0 0 8px #27d89d'; label.textContent='Token OK'; }
    else        { dot.style.background='#666';     dot.style.boxShadow='0 0 6px #333';    label.textContent='Geen token'; }
  }
  function maskToken(){
    if(!accessTokenEl) return;
    const full = accessTokenEl.textContent || '';
    if(!full || full === '-'){ setTokenLight(false); return; }
    accessTokenEl.setAttribute('data-full', full);
    accessTokenEl.setAttribute('data-hidden','1');
    const masked = full.length>12 ? (full.slice(0,6) + "…" + full.slice(-6)) : "•••";
    accessTokenEl.textContent = masked;
    if(toggleTokenBtn) toggleTokenBtn.textContent = 'Toon token';
    setTokenLight(true);
  }
  (function initTokenLightAndMask(){
    if(toggleTokenBtn){
      maskToken();
      toggleTokenBtn.addEventListener('click', ()=>{
        const isHidden = accessTokenEl.getAttribute('data-hidden') === '1';
        if(isHidden){
          accessTokenEl.textContent = accessTokenEl.getAttribute('data-full') || '';
          accessTokenEl.setAttribute('data-hidden','0');
          toggleTokenBtn.textContent = 'Verberg token';
        } else {
          maskToken();
        }
      });
    } else {
      setTokenLight(!!(accessTokenEl && accessTokenEl.textContent && accessTokenEl.textContent.trim() !== '-'));
    }
  })();
  document.getElementById('copyTokenBtn')?.addEventListener('click', async ()=>{
    const txt = accessTokenEl.getAttribute('data-full') || accessTokenEl.textContent || '';
    try{ await navigator.clipboard.writeText(txt); } catch(e){ alert('Kopiëren mislukt: '+e.message); }
  });

  // Scopes tooltip
  (()=>{
    const btn = document.getElementById('scopeTooltipBtn');
    const wrap = document.getElementById('tokenStatus');
    const panel = document.getElementById('scopeTooltipPanel');
    if(!btn || !panel || !wrap) return;
    function openPanel(){ panel.classList.remove('hidden'); panel.style.display='block'; btn.setAttribute('aria-expanded','true'); }
    function closePanel(){ panel.classList.add('hidden'); panel.style.display='none'; btn.setAttribute('aria-expanded','false'); }
    function togglePanel(){ const isHidden = panel.classList.contains('hidden') || panel.style.display==='none'; if(isHidden) openPanel(); else closePanel(); }
    closePanel();
    btn.addEventListener('click', togglePanel);
    btn.addEventListener('keydown', e=>{ if(e.key==='Enter' || e.key===' '){ e.preventDefault(); togglePanel(); }});
    document.addEventListener('keydown', e=>{ if(e.key==='Escape') closePanel(); });
    document.addEventListener('click', e=>{ if(!wrap.contains(e.target)) closePanel(); });
    wrap.addEventListener('mouseenter', openPanel);
    wrap.addEventListener('mouseleave', closePanel);
  })();
  (()=>{
    const dataEl = document.getElementById('scopesData');
    const content = document.getElementById('scopeTooltipContent');
    if(!dataEl || !content) return;
    let payload = {};
    try{ payload = JSON.parse(dataEl.textContent || '{}'); } catch {}
    const scopesStr = (payload.scopes || '').trim();
    const mapping = payload.mapping || {};
    if(!scopesStr){ content.textContent = 'Geen scopes in token.'; return; }
    const scopes = Array.from(new Set(scopesStr.split(/\\s+/).filter(Boolean))).sort();
    const mappedRows=[], extras=[];
    scopes.forEach(s => { if(mapping[s]) mappedRows.push({key:s, label: mapping[s]}); else extras.push(s); });
    const row = (label, ok)=>`<tr><td>${label}</td><td style="width:80px;text-align:center">${ok?'✔️':'❌'}</td></tr>`;
    let html = `<table><tr><th>Betekenis</th><th>Aanwezig</th></tr>`;
    mappedRows.forEach(r => { html += row(r.label, true); });
    if(extras.length){
      html += `<tr><th colspan="2">Overige scopes (niet in mapping)</th></tr>`;
      extras.forEach(s => { html += `<tr><td class="k" colspan="2">${s}</td></tr>`; });
    }
    html += `</table>`;
    content.innerHTML = html;
  })();

  // Operatie-select tinting
  (function styleOperationSelect(){
    const sel = document.getElementById('op_select'); if(!sel) return;
    sel.style.background = '#0b1016'; sel.style.color = '#e7f3f3'; sel.style.borderColor = 'rgba(255,255,255,0.18)';
    function tint(){ [...sel.options].forEach(opt=>{ opt.style.background='#0b1016'; opt.style.color='#e7f3f3'; }); }
    tint(); const mo=new MutationObserver(tint); mo.observe(sel,{childList:true}); sel.addEventListener('mousedown', tint); sel.addEventListener('click', tint);
  })();

  // Endpoints editor
  async function loadEndpoints(){
    try{
      const res = await fetch('/dcbapi/endpoints.json',{cache:'no-store'});
      const obj = await res.json();
      document.getElementById('endpointsEditor').value = JSON.stringify(obj, null, 2);
      const sel = document.getElementById('op_select');
      sel.innerHTML = '';
      Object.keys(obj).sort().forEach(k=>{
        const o = document.createElement('option'); o.value=k; o.textContent=k; sel.appendChild(o);
      });
      const first = Object.keys(obj)[0];
      if(first){ sel.value = first; applyOperation(obj, first); }
      sel.onchange = ()=>applyOperation(obj, sel.value);
      window.__ENDPOINTS__ = obj;
    }catch(e){
      document.getElementById('endpointsEditor').value = '{"health":{"method":"GET","path":"/health"}}';
    }
  }
  loadEndpoints();
  document.getElementById('loadEndpointsBtn')?.addEventListener('click', loadEndpoints);
  document.getElementById('saveEndpointsBtn')?.addEventListener('click', async ()=>{
    try{
      const txt = document.getElementById('endpointsEditor').value;
      const obj = JSON.parse(txt);
      const res = await fetch('/dcbapi/endpoints.json', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(obj)});
      if(!res.ok){ alert('Opslaan mislukt'); return; }
      await loadEndpoints(); log('Endpoints opgeslagen.');
    }catch(e){ alert('Ongeldige JSON of fout bij opslaan.'); }
  });

  // Placeholder-classifier voor dynamische velden
  function classify(ph){
    if(typeof ph !== 'string') return {type:'text', ph:''};
    const suf = ph.split('.').pop();
    const map = { n:'text', oc:'text', sn:'text', temp:'text', r:'textarea', desc:'textarea', dur:'number', cp:'list', cert:'file' };
    return {type: map[suf] || 'text', ph};
  }
  function applyOperation(all, key){
    const op = all[key] || {};
    const tmpl = op.body_template || {};
    document.getElementById('op_method').value = (op.method || 'GET');
    document.getElementById('op_path').value   = (op.path   || '/health');
    const dyn = document.getElementById('dynForm');
    dyn.innerHTML = '';
    for(const k of Object.keys(tmpl)){
      const v = tmpl[k];
      const label = k.replace(/_/g, ' ').replace(/\\b\\w/g,m=>m.toUpperCase());
      if(Array.isArray(v)){
        const ph = (v.length===1 && typeof v[0]==='string') ? v[0] : '';
        const info = classify(ph);
        if(info.type === 'list'){
          const id = `fld_${k}`;
          const wrap = `<div id="${id}" class="input-row"><button type="button" class="btn" data-add="${id}">+ Voeg toe</button></div>`;
          dyn.insertAdjacentHTML('beforeend', `<div class="lbl">${label}</div><div>${wrap}</div>`);
          addListRow(id, info.ph);
          dyn.querySelector(`[data-add="${id}"]`)?.addEventListener('click', ()=> addListRow(id, info.ph));
        } else {
          const id = `fld_${k}`;
          dyn.insertAdjacentHTML('beforeend', `<div class="lbl">${label}</div><div><textarea class="in" rows="3" id="${id}" placeholder="Komma-gescheiden waarden"></textarea></div>`);
        }
      } else {
        const info = classify(v); const id = `fld_${k}`;
        if(info.type==='textarea'){
          dyn.insertAdjacentHTML('beforeend', `<div class="lbl">${label}</div><div><textarea class="in" rows="3" id="${id}" data-ph="${info.ph}"></textarea></div>`);
        } else if(info.type==='number'){
          dyn.insertAdjacentHTML('beforeend', `<div class="lbl">${label}</div><div><input class="in" id="${id}" type="number" step="1" data-ph="${info.ph}"/></div>`);
        } else if(info.type==='file'){
          dyn.insertAdjacentHTML('beforeend', `<div class="lbl">${label} (bestand → Base64)</div><div class="input-row">
              <input class="in" type="file" id="${id}_file" />
              <button type="button" class="btn" id="${id}_to64">Lees & Base64</button>
            </div>
            <textarea class="in" rows="3" id="${id}" data-ph="${info.ph}" placeholder="Base64 inhoud..."></textarea>`);
          const fileEl = document.getElementById(`${id}_file`);
          const btn64 = document.getElementById(`${id}_to64`);
          btn64?.addEventListener('click', async ()=>{
            const f = fileEl.files && fileEl.files[0]; if(!f) return alert('Kies eerst een bestand.');
            const arr = await f.arrayBuffer(); const b64 = btoa(String.fromCharCode(...new Uint8Array(arr)));
            document.getElementById(id).value = b64;
          });
        } else {
          dyn.insertAdjacentHTML('beforeend', `<div class="lbl">${label}</div><div><input class="in" id="${id}" type="text" data-ph="${info.ph}"/></div>`);
        }
      }
    }
    // Raw JSON dicht
    const raw = document.getElementById('op_body');
    raw.classList.add('hidden');
    document.getElementById('toggleRawBtn').textContent = 'Toon Raw JSON';
  }
  function addListRow(containerId, ph){
    const cont = document.getElementById(containerId);
    const rowId = containerId + '_' + Math.random().toString(36).slice(2,7);
    const html = `<div class="input-row" id="${rowId}">
      <input class="in" type="text" data-ph="${ph}" placeholder="waarde"/>
      <button type="button" class="btn" data-del="${rowId}">×</button>
    </div>`;
    cont.insertAdjacentHTML('beforeend', html);
    cont.querySelector(`[data-del="${rowId}"]`)?.addEventListener('click', ()=> { document.getElementById(rowId)?.remove(); });
  }

  // Raw toggle
  document.getElementById('toggleRawBtn')?.addEventListener('click', ()=>{
    const raw = document.getElementById('op_body');
    const isHidden = raw.classList.contains('hidden');
    if(isHidden){
      const body = buildBodyFromDyn(); document.getElementById('op_body').value = JSON.stringify(body, null, 2);
      raw.classList.remove('hidden'); document.getElementById('toggleRawBtn').textContent = 'Verberg Raw JSON';
    } else {
      raw.classList.add('hidden'); document.getElementById('toggleRawBtn').textContent = 'Toon Raw JSON';
    }
  });
  function buildBodyFromDyn(){
    const sel = document.getElementById('op_select');
    const ops = window.__ENDPOINTS__ || {};
    const cur = ops[sel.value] || {};
    const tmpl = cur.body_template || {};
    const body = {};
    for(const k of Object.keys(tmpl)){
      const v = tmpl[k];
      if(Array.isArray(v)){
        const ph = (v.length===1 && typeof v[0]==='string') ? v[0] : '';
        const rows = Array.from(document.querySelectorAll(`#fld_${k} [data-ph="${ph}"]`));
        const values = rows.map(el => el.value).filter(x=>x!==undefined && x!=="");
        body[k] = values;
      } else {
        const el = document.getElementById(`fld_${k}`);
        if(!el){ body[k] = ""; continue; }
        const type = el.getAttribute('type') || (el.tagName.toLowerCase()==='textarea' ? 'textarea' : 'text');
        let val = el.value;
        if(type === 'number' && val !== ""){
          const n = Number(val); val = (Number.isFinite(n) ? n : val);
        }
        body[k] = val;
      }
    }
    return body;
  }

  // Uitvoeren (met auth)
  async function executeCall(method, path, body){
    const sid  = document.getElementById('session_id').value.trim();
    if(!sid){ alert('Geen sessie/token. Genereer eerst een token.'); return 0; }
    const base = document.getElementById('api_base').value.trim();
    setProgress('progressCall', true, 10);
    log(`Call: ${method} ${base}${path}`);
    try{
      const res = await fetch('/dcbapi/call', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({session_id: sid, base, method, path, body})
      });
      setProgress('progressCall', true, 70);
      const txt = await res.text();
      let pretty = txt; try{ pretty = JSON.stringify(JSON.parse(txt), null, 2);}catch(_){}
      document.getElementById('respText').textContent = pretty;
      setProgress('progressCall', false, 100);
      log(`Response: HTTP ${res.status}`);
      return res.status;
    }catch(e){
      setProgress('progressCall', false, 0);
      alert('Call mislukt: '+ e.message); log('Call error: '+ e.message); return 0;
    }
  }
  document.getElementById('runBtn')?.addEventListener('click', async ()=>{
    const method = (document.getElementById('op_method')?.value || 'GET').toUpperCase();
    const path   =  document.getElementById('op_path')?.value  || '/health';
    const raw = document.getElementById('op_body');
    let body = null;
    if(!raw.classList.contains('hidden')){
      const txt = raw.value; try{ body = txt ? JSON.parse(txt) : (['POST','PUT','PATCH'].includes(method) ? {} : null); }
      catch(e){ alert('Raw JSON is ongeldig.'); return; }
    } else {
      body = buildBodyFromDyn(); if(!['POST','PUT','PATCH'].includes(method)) body = null;
    }
    await executeCall(method, path, body);
  });
  document.getElementById('clearRespBtn')?.addEventListener('click', ()=>{ document.getElementById('respText').textContent = '(geen response)'; });

  // Health-form (publiek)
  (()=>{
    const form = document.getElementById('dcbapi-health-form');
    form?.addEventListener('submit', ()=>{
      setBtnGlow('healthBtn','idle');
    });
  })();

  // Token form progress + glow
  (()=>{
    const form = document.getElementById('tokenForm');
    const btn  = document.getElementById('genTokenBtn');
    form?.addEventListener('submit', ()=>{
      btn.disabled = true;
      setBtnGlow('genTokenBtn', 'idle');
      setProgress('progressGen', true, 25);
      setTimeout(()=>setProgress('progressGen', true, 60), 300);
    });
  })();
</script>
__SCOPES_EMBED__
"""

    # Blokken invullen
    error_block = f"<div class='error'>⚠️ {error}</div>" if error else ""
    info_block  = f"<div class='muted'>ℹ️ {info}</div>" if info else ""
    scopes_top  = (f"<div class='muted' style='margin-top:6px;'>Scope-overzicht</div><div id='scopesTableTop'>{scope_table_html}</div>"
                   if scope_table_html else "")
    health_top  = (f"<div class='muted' style='margin-top:6px;'>Health-overzicht</div><div id='healthPanelTop'>{health_table_html}</div>"
                   if health_table_html else "")

    body = body.replace("{STYLES}", styles)
    body = body.replace("{ERROR_BLOCK}", error_block)
    body = body.replace("{INFO_BLOCK}", info_block)
    body = body.replace("{SCOPES_TOP}", scopes_top)
    body = body.replace("{HEALTH_TOP}", health_top)

    # Eenvoudige placeholders
    body = body.replace("__SESSION_ID__", session_id or "")
    body = body.replace("__ACCESS_TOKEN__", token_text)
    body = body.replace("__COPY_DISABLED__", copy_disabled)
    body = body.replace("__RUN_DISABLED__", run_disabled)
    body = body.replace("__DOWNLOAD_HTML__", download_html)
    body = body.replace("__TOKEN_URL_BLOCK__", token_url_block)
    body = body.replace("__RESULT_BLOCK__", result_block)
    if result_json:
        body = body.replace("__RESULT_JSON__", result_json)
    else:
        body = body.replace("__RESULT_JSON__", "")
    body = body.replace("__SCOPES_EMBED__", scopes_embed or "")

    # JS placeholders voor omgevingswaarden
    body = body.replace("__OP_PROD__", OP_BASES["prod"])
    body = body.replace("__OP_TI__",   OP_BASES["ti"])
    body = body.replace("__OP_DEV__",  OP_BASES["dev"])
    body = body.replace("__API_PROD__", API_BASES["prod"])
    body = body.replace("__API_TI__",   API_BASES["ti"])
    body = body.replace("__API_DEV__",  API_BASES["dev"])

    return _page("DCBaaS API Tool", body)

# ---------- Web routes ----------
def register_web_routes(app: Flask):
    import requests

    @app.get("/dcbapi", strict_slashes=False)
    def dcbapi_index():
        return _form()

    @app.post("/dcbapi/token/generate", strict_slashes=False)
    def dcbapi_token_generate():
        try:
            session_id = (request.form.get("session_id") or "").strip() or str(uuid.uuid4())
            op_base    = (request.form.get("op_base")    or "").strip()
            aud_kid    = (request.form.get("aud_kid")    or "").strip()
            issuer     = (request.form.get("issuer")     or "").strip()
            scope      = (request.form.get("scope")      or "").strip()
            vault_kid  = (request.form.get("vault")      or "").strip()

            if op_base not in OP_BASES.values():
                return _form(error="OP omgeving is ongeldig."), 400

            # JWK: vault of upload
            if vault_kid:
                vault = _load_vault_raw()
                if vault_kid not in vault:
                    return _form(error="Vault-entry niet gevonden."), 400
                jwk_json = json.dumps(vault[vault_kid].get("jwk", {}), ensure_ascii=False)
            else:
                f = request.files.get("private_jwk")
                if not f or not f.filename:
                    return _form(error="Upload een private.jwk (JWK JSON) of kies een Vault-entry."), 400
                jwk_json = f.read().decode("utf-8")

            key, alg, jwk_obj = _key_from_jwk(jwk_json)

            # issuer = audience (kid)
            if not aud_kid:
                aud_kid = jwk_obj.get("kid") or ""
            if not aud_kid:
                return _form(error="Audience (kid) is verplicht. Upload/kies een JWK."), 400
            issuer = aud_kid

            # client_assertion
            now = int(time.time())
            jwt_claims = {"iss": issuer, "sub": issuer, "aud": op_base, "iat": now, "exp": now + 600}
            client_assertion = jwt.encode(jwt_claims, key, algorithm=alg)

            token_url = op_base.rstrip("/") + TOKEN_SUFFIX

            # scopes: user + ALWAYS_SCOPES
            scopes_user = (scope or "").split()
            merged_scopes = " ".join(sorted(set(scopes_user) | set(ALWAYS_SCOPES)))

            payload = {
                "grant_type": "client_credentials",
                "audience": aud_kid,
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": client_assertion,
                "scope": merged_scopes,
            }

            resp = requests.post(token_url, data=payload, headers={"Accept": "application/json"}, timeout=30)
            txt = resp.text
            try:
                data = resp.json()
            except Exception:
                data = {"_raw": txt}

            if resp.status_code >= 400:
                pretty = json.dumps(data, ensure_ascii=False, indent=2)
                page = _form(
                    error=f"Token aanvraag faalde (HTTP {resp.status_code})",
                    result_json=pretty,
                    token_url=token_url,
                    session_id=session_id
                )
                page += "<script>try{setBtnGlow('genTokenBtn','ko');}catch{}</script>"
                return page, resp.status_code

            pretty = json.dumps(data, ensure_ascii=False, indent=2)
            access_token = data.get("access_token") or ""
            scopes_resp  = data.get("scope") or ""

            # sessie + files
            SESSIONS[session_id] = {"token": access_token, "scopes": scopes_resp, "op_base": op_base, "created_ts": int(time.time())}
            _ensure_data_dir()
            sd = _session_dir(session_id)
            _save_file(os.path.join(sd, "access_token.txt"), access_token)
            _save_file(os.path.join(sd, "scopes.json"), json.dumps({"scope": scopes_resp}, ensure_ascii=False, indent=2))

            # Scope-embed (tooltip) + scope-tabel (onder token)
            mapping = _load_scope_mapping()
            scopes_json_script = (
                "<script id='scopesData' type='application/json'>"
                + json.dumps({"scopes": scopes_resp, "mapping": mapping}, ensure_ascii=False)
                + "</script>"
            )
            scope_table_html = _render_scope_table(scopes_resp, mapping)

            page = _form(
                error=None,
                info=f"Sessie-ID: {session_id}. Token opgeslagen in {sd}/access_token.txt",
                result_json=pretty,
                access_token=access_token,
                token_url=token_url,
                session_id=session_id,
                scopes_embed=scopes_json_script,
                scope_table_html=scope_table_html,
            )
            page += "<script>try{setBtnGlow('genTokenBtn','ok');}catch{}</script>"
            return page
        except Exception as e:
            page = _form(error=f"Fout: {e}")
            page += "<script>try{setBtnGlow('genTokenBtn','ko');}catch{}</script>"
            return page, 400

    @app.post("/dcbapi/health", strict_slashes=False)
    def dcbapi_health():
        """Publieke health: GET {API_BASE}/health (GEEN Authorization header)."""
        try:
            _ = (request.form.get("op_base") or "").strip()
            api_base = (request.form.get("api_base") or "").strip()
            if not api_base:
                api_base = API_BASES["prod"]  # veilige fallback
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
            banner = None if resp.ok else f"Health-controle mislukt (HTTP {resp.status_code})"

            return _form(
                error=banner,
                result_json=pretty,
                health_table_html=health_table,
            ), (200 if resp.ok else resp.status_code)
        except Exception as e:
            return _form(error=f"Health check fout: {e}"), 400

    @app.post("/dcbapi/call", strict_slashes=False)
    def dcbapi_call():
        """
        Body: { session_id, base, method, path, body? }
        Voert een request uit met Authorization: Bearer <token> uit de sessie.
        """
        try:
            body = request.get_json(force=True, silent=False) or {}
            session_id = (body.get("session_id") or "").strip()
            base = (body.get("base") or "").strip()
            method = (body.get("method") or "GET").upper()
            path = (body.get("path") or "").strip()
            payload = body.get("body")

            sess = SESSIONS.get(session_id) or {}
            token = sess.get("token", "")
            if not token:
                return jsonify({"error": "Geen token in sessie. Genereer eerst een token."}), 400
            if not base or not path:
                return jsonify({"error": "base en path zijn verplicht."}), 400

            url = base.rstrip("/") + (path if path.startswith("/") else "/" + path)
            headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}

            import requests
            resp = requests.request(
                method, url,
                json=payload if method in ("POST","PUT","PATCH") else None,
                headers=headers, timeout=60
            )
            try:
                data = resp.json()
                return Response(json.dumps(data, ensure_ascii=False, indent=2),
                                mimetype="application/json", status=resp.status_code)
            except Exception:
                return Response(resp.text, mimetype="text/plain", status=resp.status_code)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # Config endpoints
    @app.get("/dcbapi/endpoints.json", strict_slashes=False)
    def dcbapi_endpoints_get():
        return jsonify(_load_endpoints())

    @app.post("/dcbapi/endpoints.json", strict_slashes=False)
    def dcbapi_endpoints_post():
        try:
            payload = request.get_json(force=True, silent=False)
            if not isinstance(payload, dict):
                return jsonify({"error":"JSON object verwacht"}), 400
            for k, v in payload.items():
                if not isinstance(k, str) or not isinstance(v, dict):
                    return jsonify({"error":"Ongeldige mapping. Verwacht {naam: {method, path}}"}), 400
            _save_endpoints(payload)
            return jsonify({"status":"ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.get("/dcbapi/scopes.json", strict_slashes=False)
    def dcbapi_scopes_get():
        return jsonify(_load_scope_mapping())

    @app.post("/dcbapi/scopes.json", strict_slashes=False)
    def dcbapi_scopes_post():
        try:
            body = request.get_json(force=True, silent=False)
            if not isinstance(body, dict):
                return jsonify({"error":"JSON object verwacht"}), 400
            for k,v in body.items():
                if not isinstance(k,str) or not isinstance(v,str):
                    return jsonify({"error":"Alle keys/values moeten strings zijn."}), 400
            _save_scope_mapping(body)
            return jsonify({"status":"ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.get("/dcbapi/vault.json", strict_slashes=False)
    def dcbapi_vault_get():
        return jsonify(_load_vault_meta())

    @app.get("/dcbapi/download/<session_id>/access_token", strict_slashes=False)
    def dcbapi_download_token(session_id: str):
        token = (SESSIONS.get(session_id) or {}).get("token", "")
        if not token: abort(404)
        return Response(token, mimetype="text/plain",
                        headers={"Content-Disposition": 'attachment; filename="access_token.txt"'})

# ---------- Standalone ----------
if __name__ == "__main__":
    _ensure_config_dir()
    _ensure_data_dir()
    app = Flask("dcbapi_standalone")
    app.url_map.strict_slashes = False
    register_web_routes(app)
    print("DCBaaS API Tool draait op: http://127.0.0.1:5010/dcbapi")
    app.run("127.0.0.1", 5010, debug=True)
