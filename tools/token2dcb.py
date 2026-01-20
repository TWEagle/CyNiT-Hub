
# tools/token2dcb.py
"""
Token DCBaaS – client credentials token tool (hybride: Hub + standalone)

UI
- Extra grote 3D-submitknop (inline styles → wint altijd van main.css)
- Vault-select (config/token2dcb_vault.json) om zonder upload te werken
- Tabs: Resultaat, Claims, Scopes (overzicht + mapping-editor + standaardkeys)

Gedrag
- OP: authenticatie(.be)/op of authenticatie-ti(.be)/op → token URL = <keuze>/v1/token
- audience = kid uit JWK (upload of vault)
- issuer = audience (kid) (client-side ingevuld én server-side enforced)
- client_assertion_type = urn:ietf:params:oauth:client-assertion-type:jwt-bearer
- client_assertion = lokaal (iss=sub=aud_kid; iat/exp server-side)
- scope = user input + 8 vaste DCBaaS scopes (altijd toegevoegd, één regel)
- Standalone: http://127.0.0.1:5006/token2dcb
"""

from __future__ import annotations
import json, time, uuid, base64, os, pathlib
from typing import Dict, Tuple, Any, Optional
from flask import Flask, request, url_for, abort, Response, jsonify

# In-memory opslag (kortlevend)
TOKENS: Dict[str, str] = {}

# OP-bases
OP_BASES = [
    "https://authenticatie.vlaanderen.be/op",
    "https://authenticatie-ti.vlaanderen.be/op",
]
TOKEN_SUFFIX = "/v1/token"

# Config
CONFIG_DIR = os.environ.get("CONFIG_DIR", "config")
SCOPES_FILE = os.environ.get("TOKEN2DCB_SCOPES_FILE", os.path.join(CONFIG_DIR, "token2dcb_scopes.json"))
CLIENTS_FILE = os.environ.get("TOKEN2DCB_CLIENTS_FILE", os.path.join(CONFIG_DIR, "token2dcb_clients.json"))  # optioneel
VAULT_FILE = os.path.join(CONFIG_DIR, "token2dcb_vault.json")  # kid -> {label, jwk}

# Altijd toe te voegen scopes (één regel, spatie-gescheiden)
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

def _ensure_config_dir():
    pathlib.Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)

def _load_scope_mapping() -> Dict[str, str]:
    p = pathlib.Path(SCOPES_FILE)
    if p.exists():
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            pass
    return {
        "dvl_dcbaas_app_application_admin": "DCBaaS Beheer Toepassingen",
        "dvl_dcbaas_app_certificate_admin": "DCBaaS Beheer Certificaten",
        "dvl_dcbaas_app_config_admin": "DCBaaS Beheer Configuratie",
        "dvl_dcbaas_app_helpdesk": "DCBaaS Beheer Helpdesk",
        "dvl_dcbaas_info": "DCBaaS Informatie",
        "dvl_dcbaas_org_certificate_admin_organization": "DCBaaS Certificaatbeheerder Organisatie",
        "dvl_dcbaas_org_workflow_operator": "DCBaaS Workflowbeheerder",
        "vo_info": "VO Info",
    }

def _save_scope_mapping(mapping: Dict[str, str]) -> None:
    _ensure_config_dir()
    pathlib.Path(SCOPES_FILE).write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")

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
    return {kid: {"label": (raw.get(kid, {}) or {}).get("label", "key")} for kid in raw.keys()}

# JWK helpers
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

# UI rendering
def _page(title: str, body_html: str) -> str:
    try:
        from beheer.main_layout import render_page  # type: ignore
        return render_page(title=title, content_html=body_html)
    except Exception:
        return (
            "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
            f"<title>{title}</title>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>"
            "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:2rem;background:#000;color:#e8f2f2}"
            ".panel{background:linear-gradient(180deg,rgba(12,18,24,.95),rgba(8,12,16,.92));"
            "border:1px solid rgba(255,255,255,.10);border-radius:18px;box-shadow:0 20px 45px rgba(0,0,0,.55);padding:24px}"
            ".in{width:100%;padding:12px 14px;border-radius:12px;border:1px solid rgba(255,255,255,.12);background:#0f141a;color:#eaf6f6;outline:none}"
            ".in:focus{border-color:#35e6df;box-shadow:0 0 0 3px rgba(53,230,223,.15)}"
            ".in.ro{background:#101214;color:#9fb0b0;opacity:0.95}"
            ".btn{display:inline-flex;align-items:center;gap:12px;padding:12px 18px;border-radius:14px;"
            "border:1px solid rgba(0,255,200,.65);background:#35e6df;color:#00161a;cursor:pointer;font-weight:900;letter-spacing:.2px}"
            ".btn:hover{filter:brightness(1.02)}"
            ".flex{display:flex;gap:32px;align-items:flex-start}.col{flex:1 1 0;min-width:320px}"
            ".download{margin-top:16px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}"
            ".hidden{display:none !important}"
            "pre{background:#0b1020;color:#cfe3ff;padding:14px;border-radius:10px;overflow:auto}"
            "table{border-collapse:collapse;width:100%;margin-top:12px}"
            "th,td{border:1px solid rgba(255,255,255,.15);padding:10px 12px}"
            "th{text-align:left;background:rgba(255,255,255,.06)}"
            "@media(max-width:900px){.flex{flex-direction:column;gap:18px}.col{min-width:0}}"
            ".muted{color:#a7b6b6;font-size:.95rem}.error{color:#ff9b9b;margin-bottom:8px}"
            ".pill{font-family:ui-monospace,Consolas,Menlo,monospace;background:#101828;border:1px solid rgba(255,255,255,.14);padding:6px 8px;border-radius:10px}"
            ".tabs{display:flex;gap:8px;margin-top:20px;margin-bottom:8px;flex-wrap:wrap}"
            ".tab-btn{background:#10161b;border:1px solid rgba(255,255,255,.12);color:#dce7e7;padding:8px 12px;border-radius:10px;cursor:pointer}"
            ".tab-btn.active{background:#35e6df;color:#00161a;border-color:#35e6df}"
            ".tab{display:none}.tab.active{display:block}"
            ".section-toggle{display:flex;gap:8px;align-items:center;margin:8px 0 4px}"
            ".field-row{display:flex;gap:8px;align-items:center}"
            "</style></head><body>"
            + body_html + "</body></html>"
        )

def _form(
    error: Optional[str] = None,
    result_json: Optional[str] = None,
    access_token: Optional[str] = None,
    scope_table_html: Optional[str] = None,
    token_url: Optional[str] = None,
    token_download_url: Optional[str] = None,
    claims_json: Optional[str] = None,
) -> str:
    body = r"""
<div class="panel">
  <div class="flex">
    <div class="col">
      <h2>Token DCBaaS</h2>
      <p class="muted">
        Vraag een OAuth2 access token aan via <b>client_credentials</b>.
        <code>audience</code> wordt automatisch <b>kid</b> uit je <code>private.jwk</code>.
        <code>client_assertion</code> (JWT) maken we lokaal.
      </p>
    </div>
    <div class="col">
      <form method="post" action="/token2dcb" enctype="multipart/form-data">
        <label for="aud_kid">Audience (kid)</label>
        <input class="in" id="aud_kid" name="aud_kid" type="text" required placeholder="vult automatisch na JWK upload/keuze..." />

        <label for="issuer">Issuer (ook 'sub')</label>
        <div class="field-row">
          <input class="in" id="issuer" name="issuer" type="text" required placeholder="wordt gelijk gezet aan audience (kid)" />
          <button id="issuerLockBtn" class="btn" type="button" title="Vergrendel/Ontgrendel issuer">🔓 Vergrendel</button>
        </div>

             <label>OP omgeving</label>
            <div style="display:flex; gap:22px; margin-bottom:8px; align-items:center;">

            <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
                <input type="radio" name="op_radio" value="https://authenticatie.vlaanderen.be/op" checked>
                Productie
            </label>

            <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
                <input type="radio" name="op_radio" value="https://authenticatie-ti.vlaanderen.be/op">
                T&amp;I
            </label>

            </div>

            <!-- Hidden veld dat backend gebruikt -->
            <input type="hidden" id="op_base" name="op_base" value="https://authenticatie.vlaanderen.be/op">

        <label for="scope">Scope(s)</label>
        <input class="in" id="scope" name="scope" type="text" placeholder="extra scopes (spatie-gescheiden) — 8 DCBaaS scopes worden altijd toegevoegd" />

        <label for="private_jwk">private.jwk (JWK JSON)</label>
        <input class="in" id="private_jwk" name="private_jwk" type="file" accept=".jwk,application/json" />

        <label for="vault">Vault (opgeslagen JWK’s)</label>
        <select class="in" id="vault" name="vault">
          <option value="">-- Kies uit opgeslagen sleutels --</option>
        </select>

        <!-- INLINE STYLES: onverslaanbaar door main.css -->
        <button
          id="submitBtn" type="submit"
          style="
            width:100%; margin-top:22px; padding:22px 28px;
            font-size:1.55rem; font-weight:900; letter-spacing:.5px;
            border-radius:16px; cursor:pointer; text-align:center; display:inline-block;
            background:linear-gradient(170deg,#37ffe2,#35e6df,#10b8ff);
            border:2px solid rgba(16,184,255,.95);
            box-shadow:
              0 12px 0 rgba(0,120,140,1),
              0 26px 40px rgba(16,184,255,.35),
              inset 0 -8px 18px rgba(0,0,0,.35),
              inset 0 8px 20px rgba(255,255,255,.15);
            color:#000;
          "
          onmousedown="this.style.transform='translateY(4px)'; this.style.boxShadow='0 6px 0 rgba(0,120,140,1),0 18px 30px rgba(16,184,255,.25), inset 0 -8px 18px rgba(0,0,0,.35), inset 0 8px 20px rgba(255,255,255,.15)';"
          onmouseup="this.style.transform='translateY(0)'; this.style.boxShadow='0 12px 0 rgba(0,120,140,1),0 26px 40px rgba(16,184,255,.35), inset 0 -8px 18px rgba(0,0,0,.35), inset 0 8px 20px rgba(255,255,255,.15)';"
        >
          ⚡ Genereer &amp; Vraag Token
        </button>
      </form>
    </div>
  </div>

  <div class="tabs">
    <button class="tab-btn active" data-tab="tab-result">Resultaat</button>
    <button class="tab-btn" data-tab="tab-claims">Claims</button>
    <button class="tab-btn" data-tab="tab-scopes">Scopes</button>
  </div>

  <div id="tab-result" class="tab active">__RESULT_TAB__</div>
  <div id="tab-claims"  class="tab">__CLAIMS_TAB__</div>
  <div id="tab-scopes"  class="tab">__SCOPES_TAB__</div>
</div>

<script>
  // Tabs
  document.querySelectorAll('.tab-btn').forEach(btn=>{
    btn.addEventListener('click',()=>{
      document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
      document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
      btn.classList.add('active'); document.getElementById(btn.getAttribute('data-tab')).classList.add('active');
    });
  });

  // Issuer lock/unlock
  const issuerEl = document.getElementById('issuer');
  const issuerLockBtn = document.getElementById('issuerLockBtn');
  function setIssuerLocked(locked){
    issuerEl.readOnly = !!locked;
    issuerEl.classList.toggle('ro', !!locked);
    issuerLockBtn.textContent = locked ? '🔒 Ontgrendel' : '🔓 Vergrendel';
    issuerLockBtn.title = locked ? 'Ontgrendel issuer' : 'Vergrendel issuer';
  }
  issuerLockBtn?.addEventListener('click', ()=> setIssuerLocked(!issuerEl.readOnly));
  setIssuerLocked(false);

  // Upload: audience=kid en issuer=audience (kid)
  const jwkInput = document.getElementById('private_jwk');
  const audKid   = document.getElementById('aud_kid');
  jwkInput?.addEventListener('change', ()=>{
    const f = jwkInput.files && jwkInput.files[0]; if(!f) return;
    const r = new FileReader();
    r.onload = e=>{
      try{
        const jwk = JSON.parse(String(e.target.result||'{}'));
        if (jwk.kid) audKid.value = jwk.kid;
        if (audKid.value) { issuerEl.value = audKid.value; setIssuerLocked(true); }
      }catch{}
    };
    r.readAsText(f,'utf-8');
  });

  // Vault dropdown laden
  async function loadVault(){
    try{
      const res = await fetch('/token2dcb/vault.json',{cache:'no-store'});
      if(!res.ok) return;
      const vault = await res.json(); // { kid: {label: ...}, ... }
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

  // Vault-keuze ⇒ audience/issuer vullen & locken
  document.getElementById('vault')?.addEventListener('change', (ev)=>{
    const kid = ev.target.value;
    if (!kid) return;
    audKid.value = kid;
    issuerEl.value = kid;
    setIssuerLocked(true);
    if (jwkInput) jwkInput.value = "";
  });

    // --- OP RADIO HANDLER ---
    document.querySelectorAll('input[name="op_radio"]').forEach(r => {
    r.addEventListener('change', ev => {
        document.getElementById('op_base').value = ev.target.value;
    });
    });

  // Copy helpers
  async function copyTextById(id,btnId,ok){
    const el = document.getElementById(id); if(!el) return alert('Niets om te kopiëren.');
    try{
      await navigator.clipboard.writeText(el.textContent.trim());
      const b = document.getElementById(btnId);
      if (b){ const old=b.textContent; b.textContent=ok; b.disabled=true;
        setTimeout(()=>{b.textContent=old; b.disabled=false;},1800); }
    }catch(e){ alert('Kopiëren mislukt: '+e.message); }
  }
  window.copyToken  = ()=>copyTextById('accessTokenText','copyTokenBtn','Gekopieerd ✔');
  window.copyClaims = ()=>copyTextById('claimsText','copyClaimsBtn','Claims gekopieerd ✔');

  // Generieke toggles
  document.addEventListener('click',(ev)=>{
    const t = ev.target.closest('[data-toggle-target]'); if(!t) return;
    const id = t.getAttribute('data-toggle-target');
    const showLbl = t.getAttribute('data-show') || 'Toon';
    const hideLbl = t.getAttribute('data-hide') || 'Verberg';
    const el = document.getElementById(id); if(!el) return;
    el.classList.toggle('hidden');
    t.textContent = el.classList.contains('hidden') ? showLbl : hideLbl;
  });
</script>
    """

    # --------- RESULTAAT-tab ---------
    result_parts = []
    if error:
        result_parts.append(f"<div class='error'>⚠️ {error}</div>")

    token_block = ""
    if access_token:
        token_block += (
            "<div class='download'>"
            "<span class='pill'>Access Token:</span> "
            f"<span id='accessTokenText' class='pill'>{access_token}</span>"
            "<button id='copyTokenBtn' class='btn' type='button' onclick='copyToken()'>Kopieer token</button>"
            "<button class='btn' type='button' data-toggle-target='accessTokenText' data-show='Toon token' data-hide='Verberg token'>Verberg token</button>"
        )
        if token_download_url:
            token_block += f" {token_download_url}Download</a>"
        token_block += "</div>"
    else:
        token_block += (
            "<div class='download'>"
            "<span class='pill'>Access Token:</span> <span class='pill'>-</span>"
            "<button class='btn' type='button' disabled>Kopieer token</button>"
            "<button class='btn' type='button' disabled>Toon token</button>"
            "</div>"
        )
    result_parts.append(token_block)

    if token_url:
        result_parts.append(f"<p class='muted'>Token URL: <code>{token_url}</code></p>")

    if result_json:
        result_parts.append(
            "<div class='section-toggle'>"
            "<button class='btn' type='button' data-toggle-target='jsonPanel' data-show='Toon JSON' data-hide='Verberg JSON'>Verberg JSON</button>"
            "</div>"
            f"<div id='jsonPanel'><pre>{result_json}</pre></div>"
        )
    else:
        result_parts.append("<div class='section-toggle'><button class='btn' type='button' disabled>Toon JSON</button></div>")

    result_tab = "\n".join(result_parts)

    # --------- CLAIMS-tab ---------
    if claims_json:
        claims_tab = (
            "<div class='download'>"
            "<button id='copyClaimsBtn' class='btn' type='button' onclick='copyClaims()'>Copy claims</button>"
            "</div>"
            f"<div id='claimsPanel'><pre id='claimsText'>{claims_json}</pre></div>"
        )
    else:
        claims_tab = "<p class='muted'>Geen claims beschikbaar. Vraag eerst een token aan.</p>"

    # --------- SCOPES-tab ---------
    scopes_parts = []
    if scope_table_html:
        scopes_parts.append(
            "<div class='section-toggle'>"
            "<button class='btn' type='button' data-toggle-target='scopesTable' data-show='Toon scope‑overzicht' data-hide='Verberg scope‑overzicht'>Verberg scope‑overzicht</button>"
            "</div>"
            f"<div id='scopesTable'>{scope_table_html}</div>"
        )
    else:
        scopes_parts.append("<div class='section-toggle'><button class='btn' type='button' disabled>Toon scope‑overzicht</button></div>")

    scopes_parts.append(
        "<div class='section-toggle'>"
        "<button class='btn' type='button' data-toggle-target='stdScopes' data-show='Toon standaard-scopekeys' data-hide='Verberg standaard-scopekeys'>Toon standaard-scopekeys</button>"
        "</div>"
        f"<div id='stdScopes' class='hidden'><pre>{SCOPES_DEFAULT_KEYS_STR}</pre></div>"
    )

    scopes_parts.append(
        "<div class='section-toggle'>"
        "<button class='btn' type='button' data-toggle-target='scopesEditorWrap' data-show='Toon scope‑mapping' data-hide='Verberg scope‑mapping'>Toon scope‑mapping</button>"
        "</div>"
        "<div id='scopesEditorWrap' class='hidden'>"
        "<p class='muted'>Bewerkt bestand: <code>config/token2dcb_scopes.json</code></p>"
        "<textarea id='scopesEditor' class='in' rows='12'></textarea>"
        "<div class='download'>"
        "<button class='btn' id='loadScopesBtn' type='button'>Herladen</button>"
        "<button class='btn' id='saveScopesBtn' type='button'>Opslaan</button>"
        " /token2dcb/scopes.jsonOpen JSON</a>"
        "</div>"
        "</div>"
    )
    scopes_tab = "\n".join(scopes_parts)

    body = body.replace("__RESULT_TAB__", result_tab).replace("__CLAIMS_TAB__", claims_tab).replace("__SCOPES_TAB__", scopes_tab)
    return _page("Token DCBaaS", body)

def _render_scope_table(scopes_space_sep: str, mapping: Dict[str, str]) -> str:
    scopes = set([s for s in (scopes_space_sep or "").split() if s.strip()])
    rows = []
    for key, label in mapping.items():
        ok = "✔️" if key in scopes else "❌"
        rows.append(f"<tr><td>{label}</td><td style='width:80px;text-align:center'>{ok}</td></tr>")
    extra = [s for s in sorted(scopes) if s not in mapping]
    extra_rows = ""
    if extra:
        extra_rows = (
            "<tr><th colspan='2'>Overige scopes (niet in mapping)</th></tr>" +
            "".join(f"<tr><td colspan='2'><code>{s}</code></td></tr>" for s in extra)
        )
    return "<table><tr><th>Betekenis</th><th>Aanwezig</th></tr>" + "".join(rows) + extra_rows + "</table>"

# ------- Web routes -------
def register_web_routes(app: Flask):
    @app.get("/token2dcb")
    def token2dcb_index():
        return _form()

    @app.post("/token2dcb")
    def token2dcb_post():
        try:
            issuer  = (request.form.get("issuer")  or "").strip()
            op_base = (request.form.get("op_base") or "").strip()
            aud_kid = (request.form.get("aud_kid") or "").strip()
            scope   = (request.form.get("scope")   or "").strip()
            vault_kid = (request.form.get("vault") or "").strip()

            jwk_json = ""
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

            # issuer = audience (kid), enforced
            if not aud_kid:
                aud_kid = jwk_obj.get("kid") or ""
            if not aud_kid:
                return _form(error="Audience (kid) is verplicht. Upload/kies een JWK."), 400
            issuer = aud_kid

            if op_base not in OP_BASES:
                return _form(error="OP omgeving is ongeldig."), 400

            # client_assertion
            now = int(time.time())
            jwt_claims = {"iss": issuer, "sub": issuer, "aud": op_base, "iat": now, "exp": now + 600}
            client_assertion = jwt.encode(jwt_claims, key, algorithm=alg)

            token_url = op_base.rstrip("/") + TOKEN_SUFFIX

            # scopes: user + ALWAYS_SCOPES → set → één regel met spaties
            scopes_user = (scope or "").split()
            merged_scopes = " ".join(sorted(set(scopes_user) | ALWAYS_SCOPES))

            payload = {
                "grant_type": "client_credentials",
                "audience": aud_kid,
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": client_assertion,
                "scope": merged_scopes,
            }

            import requests
            resp = requests.post(token_url, data=payload, headers={"Accept": "application/json"}, timeout=30)
            txt = resp.text
            try:
                data = resp.json()
            except Exception:
                data = {"_raw": txt}

            if resp.status_code >= 400:
                pretty = json.dumps(data, ensure_ascii=False, indent=2)
                return _form(
                    error=f"Token aanvraag faalde (HTTP {resp.status_code})",
                    result_json=pretty,
                    token_url=token_url,
                    claims_json=json.dumps(jwt_claims, ensure_ascii=False, indent=2),
                ), resp.status_code

            pretty = json.dumps(data, ensure_ascii=False, indent=2)
            access_token = data.get("access_token") or ""
            scopes_resp  = data.get("scope") or ""

            token_id = str(uuid.uuid4()); TOKENS[token_id] = access_token
            dl = url_for("token2dcb_download", token_id=token_id, _external=False)

            mapping = _load_scope_mapping()
            table_html = _render_scope_table(scopes_resp, mapping)

            return _form(
                error=None,
                result_json=pretty,
                access_token=access_token,
                scope_table_html=table_html,
                token_url=token_url,
                token_download_url=dl,
                claims_json=json.dumps(jwt_claims, ensure_ascii=False, indent=2),
            )
        except Exception as e:
            return _form(error=f"Fout: {e}"), 400

    @app.get("/token2dcb/scopes.json")
    def token2dcb_scopes_get():
        return jsonify(_load_scope_mapping())

    @app.post("/token2dcb/scopes.json")
    def token2dcb_scopes_post():
        try:
            body = request.get_json(force=True, silent=False)
            if not isinstance(body, dict): return jsonify({"error":"JSON object verwacht"}), 400
            for k, v in body.items():
                if not isinstance(k,str) or not isinstance(v,str):
                    return jsonify({"error":"Alle keys/values moeten strings zijn."}), 400
            _save_scope_mapping(body); return jsonify({"status":"ok"})
        except Exception as e:
            return jsonify({"error":str(e)}), 400

    @app.get("/token2dcb/clients.json")
    def token2dcb_clients_get():
        return jsonify(_load_clients_mapping())

    @app.get("/token2dcb/vault.json")
    def token2dcb_vault_get():
        return jsonify(_load_vault_meta())

    @app.get("/token2dcb/download/<token_id>")
    def token2dcb_download(token_id: str):
        token = TOKENS.get(token_id, "")
        if not token: abort(404)
        return Response(token, mimetype="text/plain",
                        headers={"Content-Disposition": 'attachment; filename=\"access_token.txt\"'})

# Standalone
if __name__ == "__main__":
    _ensure_config_dir()
    _app = Flask("token2dcb_standalone")
    register_web_routes(_app)
    print("Token DCBaaS standalone draait op: http://127.0.0.1:5006/token2dcb")
    _app.run("127.0.0.1", 5006, debug=True)
