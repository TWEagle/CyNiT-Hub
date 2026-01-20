
# tools/dcbapi.py
"""
DCBaaS API Tool – Hub-stijl (Optie B) + standalone

- Eigen pagina/route: /dcbapi (werkt met en zonder trailing slash)
- In Hub-stijl: gebruikt beheer.main_layout als die aanwezig is; geen afwijkend thema
- Top-toolbar (Prod/T&I, JWK kiezen / Vault, Genereer token, Health, Tokenstatus, Scopes)
- Token via client_credentials; token + scopes in sessie én op disk (dcbapi/session_<id>/)
- Dynamische API-calls o.b.v. config/dcbapi_endpoints.json met placeholders:
    .n .oc .sn .temp -> text
    .r .desc         -> textarea
    .dur             -> number
    .cp              -> list (meerdere waarden)
    .cert            -> file (client-side Base64)
- Endpoints-editor (GET/POST /dcbapi/endpoints.json)
- Standalone: http://127.0.0.1:5010/dcbapi
"""

from __future__ import annotations
import os, json, time, uuid, base64, pathlib
from typing import Dict, Any, Optional, Tuple
from flask import Flask, request, abort, Response, jsonify

# ---------------- In-memory sessies ----------------
# session_id -> dict(token, scopes, op_base, created_ts)
SESSIONS: Dict[str, Dict[str, Any]] = {}

# ---------------- OP / Token settings --------------
OP_BASES = [
    "https://authenticatie.vlaanderen.be/op",
    "https://authenticatie-ti.vlaanderen.be/op",
]
TOKEN_SUFFIX = "/v1/token"

# ---------------- Configpaden ----------------------
CONFIG_DIR = os.environ.get("CONFIG_DIR", "config")
DATA_DIR = os.environ.get("DCBAPI_DATA_DIR", "dcbapi")
SCOPES_FILE = os.path.join(CONFIG_DIR, "token2dcb_scopes.json")
VAULT_FILE = os.path.join(CONFIG_DIR, "token2dcb_vault.json")
ENDPOINTS_FILE = os.path.join(CONFIG_DIR, "dcbapi_endpoints.json")

# Altijd toe te voegen DCBaaS scopes (spatie-gescheiden in request)
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

# ---------------- Helpers: bestand & config --------
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
        "dvl_dcbaas_app_application_admin": "DCBaaS Beheer Toepassingen",
        "dvl_dcbaas_app_certificate_admin": "DCBaaS Beheer Certificaten",
        "dvl_dcbaas_app_config_admin": "DCBaaS Beheer Configuratie",
        "dvl_dcbaas_app_helpdesk": "DCBaaS Beheer Helpdesk",
        "dvl_dcbaas_info": "DCBaaS Informatie",
        "dvl_dcbaas_org_certificate_admin_organization": "DCBaaS Certificaatbeheerder Organisatie",
        "dvl_dcbaas_org_workflow_operator": "DCBaaS Workflowbeheerder",
        "vo_info": "VO Info",
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

# ---------------- JWK / JWT helpers ----------------
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

# ---------------- UI via main_layout ----------------
def _page(title: str, body_html: str) -> str:
    """Render via beheer.main_layout als die bestaat; anders minimal fallback."""
    try:
        from beheer.main_layout import render_page  # type: ignore
        return render_page(title=title, content_html=body_html)
    except Exception:
        # Minimal fallback zonder eigen thema
        return (
            "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
            f"<title>{title}</title><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "</head><body>" + body_html + "</body></html>"
        )

# ---------------- Pagina (Hub-stijl, neutrale markup) ----------------
def _form(
    error: Optional[str] = None,
    info: Optional[str] = None,
    result_json: Optional[str] = None,
    access_token: Optional[str] = None,
    token_url: Optional[str] = None,
    session_id: Optional[str] = None,
    scopes_embed: Optional[str] = None,
) -> str:
    # Tekstblokken (geen f-strings in HTML/JS; we .replace() placeholders)
    token_url_block = f"<div class='muted'>Token URL: <code>{token_url}</code></div>" if token_url else ""
    token_text = access_token or "-"
    copy_disabled = "disabled" if not access_token else ""
    run_disabled = "disabled" if not access_token else ""

    if session_id and access_token:
        download_html = f'<a class="btn" href="/dcbapi/download/{session_id}/access_token" target="_blank">Download token</a>'
    else:
        download_html = ""

    result_block = (
        "<details open><summary>Resultaat JSON</summary><pre style='overflow:auto'>__RESULT_JSON__</pre></details>"
        if result_json else "<details><summary>Resultaat JSON</summary><div class='muted'>Nog geen resultaat</div></details>"
    )

    # Scopes mini-knop (tooltip-panel)
    scopes_button = (
        "<button id='scopeTooltipBtn' class='btn' type='button' title='Toon scopes'>Scopes</button>"
        if access_token else "<button class='btn' type='button' disabled>Scopes</button>"
    )
    scopes_panel = (
        "<div id='scopeTooltipPanel' class='hidden' role='dialog' aria-label='Scopes in token' "
        "style='position:absolute; right:0; top:100%; min-width:320px; max-width:520px; z-index:50;'>"
        "<div id='scopeTooltipContent' style='max-height:340px; overflow:auto;'></div></div>"
    )

    body = r"""
<div class="dcbapi">
  <!-- Top toolbar (Productie / T&I + JWK/Vault + Genereer token + Health + Tokenstatus + Scopes) -->
  <section>
    <form id="tokenForm" method="post" action="/dcbapi/token/generate" enctype="multipart/form-data">
      <input type="hidden" name="session_id" id="session_id" value="__SESSION_ID__">

      <div class="toolbar" style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;position:relative">
        <!-- Omgeving -->
        <div style="display:flex;gap:10px;align-items:center;">
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
            <input type="radio" name="op_radio" value="https://authenticatie.vlaanderen.be/op" checked> Productie
          </label>
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
            <input type="radio" name="op_radio" value="https://authenticatie-ti.vlaanderen.be/op"> T&amp;I
          </label>
          <input type="hidden" id="op_base" name="op_base" value="https://authenticatie.vlaanderen.be/op">
        </div>

        <!-- Token URL -->
        <div id="tokenUrlBox" style="min-width:260px;">__TOKEN_URL_BLOCK__</div>

        <!-- Scopes input -->
        <div style="display:flex;gap:6px;align-items:center;min-width:260px;">
          <label for="scope" class="muted">extra scopes</label>
          <input class="in" id="scope" name="scope" type="text" placeholder="spatie-gescheiden; vaste DCBaaS scopes worden toegevoegd">
        </div>

        <!-- JWK upload en Vault -->
        <div style="display:flex;gap:8px;align-items:center;min-width:280px;">
          <input class="in" id="private_jwk" name="private_jwk" type="file" accept=".jwk,application/json" />
          <select class="in" id="vault" name="vault">
            <option value="">-- Kies uit opgeslagen JWK’s --</option>
          </select>
        </div>

        <!-- Genereer token -->
        <button id="genTokenBtn" class="btn" type="submit">Genereer token</button>

        <!-- Health -->
        <button id="healthBtn" class="btn" type="button" title="GET /health">Health</button>

        <!-- Tokenstatus + scopes -->
        <div id="tokenStatus" style="display:flex;gap:8px;align-items:center;position:relative">
          <span class="pill" id="accessTokenText">__ACCESS_TOKEN__</span>
          <button id="copyTokenBtn" class="btn" type="button" __COPY_DISABLED__>Kopieer</button>
          <button id="toggleTokenBtn" class="btn" type="button" __COPY_DISABLED__>Toon token</button>
          __DOWNLOAD_HTML__
          """ + scopes_button + scopes_panel + """
        </div>
      </div>

      <div style="display:flex;gap:10px;align-items:center;margin-top:6px;">
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

  <!-- Result JSON -->
  <section style="margin-top:12px;">
    __RESULT_BLOCK__
  </section>

  <!-- API-calls -->
  <section style="margin-top:16px;">
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
      <div style="display:flex;gap:6px;align-items:center;">
        <label class="muted">API omgeving</label>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
          <input type="radio" name="api_radio" value="prod" checked> Productie
        </label>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
          <input type="radio" name="api_radio" value="ti"> T&amp;I
        </label>
      </div>
      <div style="display:flex;gap:6px;align-items:center;min-width:280px;">
        <label for="api_base" class="muted">API base</label>
        <input class="in" id="api_base" type="text" placeholder="https://extapi.dcb.vlaanderen.be">
      </div>
      <div style="display:flex;gap:6px;align-items:center;">
        <label for="op_select" class="muted">Operatie</label>
        <select class="in" id="op_select"></select>
      </div>
      <div id="progressCall" class="hidden" style="height:4px;flex:1;background:rgba(255,255,255,.08);border-radius:3px;">
        <div id="progressCallBar" style="height:100%;width:0;background:linear-gradient(90deg,#37ffe2,#10b8ff);"></div>
      </div>
    </div>

    <!-- Methode/Pad + dynamische velden -->
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

      <div style="display:flex;gap:8px;align-items:center;margin-top:10px;">
        <button class="btn" id="toggleRawBtn" type="button">Toon Raw JSON</button>
        <button class="btn" id="runBtn" type="button" __RUN_DISABLED__>▶️ Uitvoeren</button>
        <button class="btn" id="clearRespBtn" type="button">Wissen</button>
        <a class="btn" href="/dcbapi/endpoints.json" target="_blank">Open endpoints.json</a>
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
        <a class="btn" href="/dcbapi/endpoints.json" target="_blank">Open JSON</a>
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
  // ------- Kleine helpers
  function setProgress(id, show, pct){
    const wrap = document.getElementById(id);
    const bar  = wrap?.querySelector('div');
    if (!wrap || !bar) return;
    wrap.classList.toggle('hidden', !show);
    if (typeof pct === 'number') bar.style.width = Math.max(0, Math.min(100, pct)) + '%';
  }
  function log(s){
    const lb = document.getElementById('logBox');
    const ts = new Date().toISOString().replace('T',' ').replace('Z','');
    lb.textContent += `[${ts}] ${s}\n`;
    lb.scrollTop = lb.scrollHeight;
  }

  // ------- Issuer lock
  const issuerEl = document.getElementById('issuer');
  const issuerLockBtn = document.getElementById('issuerLockBtn');
  function setIssuerLocked(locked){
    issuerEl.readOnly = !!locked;
    issuerLockBtn.textContent = locked ? '🔒' : '🔓';
    issuerLockBtn.title = locked ? 'Ontgrendel issuer' : 'Vergrendel issuer';
  }
  issuerLockBtn?.addEventListener('click', ()=> setIssuerLocked(!issuerEl.readOnly));
  setIssuerLocked(false);

  // ------- OP radio -> hidden veld
  document.querySelectorAll('input[name="op_radio"]').forEach(r => {
    r.addEventListener('change', ev => { document.getElementById('op_base').value = ev.target.value; });
  });

  // ------- Upload JWK -> aud/issuer
  const jwkInput = document.getElementById('private_jwk');
  const audKid   = document.getElementById('aud_kid');
  jwkInput?.addEventListener('change', ()=>{
    const f = jwkInput.files && jwkInput.files[0]; if(!f) return;
    const r = new FileReader();
    r.onload = e=>{
      try{
        const jwk = JSON.parse(String(e.target.result||'{}'));
        if (jwk.kid) audKid.value = jwk.kid;
        if (audKid.value){ issuerEl.value = audKid.value; setIssuerLocked(true); }
      }catch{}
    };
    r.readAsText(f,'utf-8');
  });

  // ------- Vault dropdown
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
    if (!kid) return;
    audKid.value = kid;
    issuerEl.value = kid;
    setIssuerLocked(true);
    if (jwkInput) jwkInput.value = "";
  });

  // ------- Token toggle & copy
  const accessTokenEl = document.getElementById('accessTokenText');
  const toggleTokenBtn = document.getElementById('toggleTokenBtn');
  function maskToken(){
    if (!accessTokenEl) return;
    const full = accessTokenEl.textContent || '';
    if (!full || full === '-') return;
    accessTokenEl.setAttribute('data-full', full);
    accessTokenEl.setAttribute('data-hidden','1');
    const masked = full.length>12 ? (full.slice(0,6) + "…" + full.slice(-6)) : "•••";
    accessTokenEl.textContent = masked;
    toggleTokenBtn.textContent = 'Toon token';
  }
  if (toggleTokenBtn){
    maskToken();
    toggleTokenBtn.addEventListener('click', ()=>{
      const isHidden = accessTokenEl.getAttribute('data-hidden') === '1';
      if (isHidden){
        accessTokenEl.textContent = accessTokenEl.getAttribute('data-full') || '';
        accessTokenEl.setAttribute('data-hidden','0');
        toggleTokenBtn.textContent = 'Verberg token';
      } else {
        maskToken();
      }
    });
  }
  document.getElementById('copyTokenBtn')?.addEventListener('click', async ()=>{
    const txt = accessTokenEl.getAttribute('data-full') || accessTokenEl.textContent || '';
    try { await navigator.clipboard.writeText(txt); } catch(e){ alert('Kopiëren mislukt: '+e.message); }
  });

  // ------- Scopes tooltip
  (()=>{
    const btn   = document.getElementById('scopeTooltipBtn');
    const wrap  = document.getElementById('tokenStatus');
    const panel = document.getElementById('scopeTooltipPanel');
    if (!btn || !panel || !wrap) return;
    const openPanel  = ()=>{ panel.classList.remove('hidden'); btn.setAttribute('aria-expanded','true'); };
    const closePanel = ()=>{ panel.classList.add('hidden'); btn.setAttribute('aria-expanded','false'); };
    const togglePanel= ()=>{ panel.classList.contains('hidden') ? openPanel() : closePanel(); };
    btn.addEventListener('click', togglePanel);
    document.addEventListener('keydown', e=>{ if(e.key==='Escape') closePanel(); });
    document.addEventListener('click', e=>{ if (!wrap.contains(e.target)) closePanel(); });
    wrap.addEventListener('mouseenter', ()=>openPanel());
    wrap.addEventListener('mouseleave', ()=>closePanel());
  })();

  // ------- Scopes content (server-embed na token)
  (()=>{
    const dataEl = document.getElementById('scopesData');
    const content = document.getElementById('scopeTooltipContent');
    if (!dataEl || !content) return;
    let payload = {};
    try { payload = JSON.parse(dataEl.textContent || '{}'); } catch {}
    const scopesStr = (payload.scopes || '').trim();
    const mapping   = payload.mapping || {};
    if (!scopesStr) { content.textContent = 'Geen scopes in token.'; return; }
    const scopes = Array.from(new Set(scopesStr.split(/\s+/).filter(Boolean))).sort();
    const mappedRows = [], extras = [];
    scopes.forEach(s => { if (mapping[s]) mappedRows.push({key:s, label:mapping[s]}); else extras.push(s); });
    const row = (label, ok)=>`<tr><td>${label}</td><td style="width:80px;text-align:center">${ok?'✔️':'❌'}</td></tr>`;
    let html = `<table><tr><th>Betekenis</th><th>Aanwezig</th></tr>`;
    mappedRows.forEach(r => { html += row(r.label, true); });
    if (extras.length){
      html += `<tr><th colspan="2">Overige scopes (niet in mapping)</th></tr>`;
      extras.forEach(s => { html += `<tr><td class="k" colspan="2">${s}</td></tr>`; });
    }
    html += `</table>`;
    content.innerHTML = html;
  })();

  // ------- API omgeving radio -> base
  function setApiBaseByRadio(v){
    const apiBase = document.getElementById('api_base');
    if (!apiBase) return;
    apiBase.value = (v === 'prod') ? 'https://extapi.dcb.vlaanderen.be' : 'https://extapi-ti.dcb.vlaanderen.be';
  }
  document.querySelectorAll('input[name="api_radio"]').forEach(r=>{
    r.addEventListener('change', ev => setApiBaseByRadio(ev.target.value));
  });
  setApiBaseByRadio('prod');

  // ------- Endpoints (laden/editor)
  async function loadEndpoints(){
    try{
      const res = await fetch('/dcbapi/endpoints.json',{cache:'no-store'});
      const obj = await res.json();
      document.getElementById('endpointsEditor').value = JSON.stringify(obj, null, 2);
      const sel = document.getElementById('op_select');
      sel.innerHTML = '';
      Object.keys(obj).sort().forEach(k=>{
        const o = document.createElement('option');
        o.value = k; o.textContent = k;
        sel.appendChild(o);
      });
      const first = Object.keys(obj)[0];
      if (first){ sel.value = first; applyOperation(obj, first); }
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
      if (!res.ok) { alert('Opslaan mislukt'); return; }
      await loadEndpoints();
      log('Endpoints opgeslagen.');
    }catch(e){ alert('Ongeldige JSON of fout bij opslaan.'); }
  });

  // ------- Placeholder-engine (client)
  function classify(ph){
    if (typeof ph !== 'string') return {type:'text', ph:''};
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
    for (const k of Object.keys(tmpl)){
      const v = tmpl[k];
      const label = k.replace(/_/g, ' ').replace(/\b\w/g,m=>m.toUpperCase());
      if (Array.isArray(v)){
        const ph = (v.length===1 && typeof v[0]==='string') ? v[0] : '';
        const info = classify(ph);
        if (info.type === 'list'){
          const id = `fld_${k}`;
          const wrap = `
            <div id="${id}" class="input-row">
              <button type="button" class="btn" data-add="${id}">+ Voeg toe</button>
            </div>`;
          dyn.insertAdjacentHTML('beforeend', `<div class="lbl">${label}</div><div>${wrap}</div>`);
          addListRow(id, info.ph);
          dyn.querySelector(`[data-add="${id}"]`)?.addEventListener('click', ()=> addListRow(id, info.ph));
        } else {
          const id = `fld_${k}`;
          dyn.insertAdjacentHTML('beforeend', `<div class="lbl">${label}</div><div><textarea class="in" rows="3" id="${id}" placeholder="Komma-gescheiden waarden"></textarea></div>`);
        }
      } else {
        const info = classify(v);
        const id = `fld_${k}`;
        if (info.type==='textarea'){
          dyn.insertAdjacentHTML('beforeend', `<div class="lbl">${label}</div><div><textarea class="in" rows="3" id="${id}" data-ph="${info.ph}"></textarea></div>`);
        } else if (info.type==='number'){
          dyn.insertAdjacentHTML('beforeend', `<div class="lbl">${label}</div><div><input class="in" id="${id}" type="number" step="1" data-ph="${info.ph}"/></div>`);
        } else if (info.type==='file'){
          dyn.insertAdjacentHTML('beforeend', `<div class="lbl">${label} (bestand → Base64)</div><div class="input-row">
            <input class="in" type="file" id="${id}_file" />
            <button type="button" class="btn" id="${id}_to64">Lees & Base64</button>
          </div>
          <textarea class="in" rows="3" id="${id}" data-ph="${info.ph}" placeholder="Base64 inhoud..."></textarea>`);
          const fileEl = document.getElementById(`${id}_file`);
          const btn64  = document.getElementById(`${id}_to64`);
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

  // ------- Raw toggle
  document.getElementById('toggleRawBtn')?.addEventListener('click', ()=>{
    const raw = document.getElementById('op_body');
    const isHidden = raw.classList.contains('hidden');
    if (isHidden){
      const body = buildBodyFromDyn();
      document.getElementById('op_body').value = JSON.stringify(body, null, 2);
      raw.classList.remove('hidden');
      document.getElementById('toggleRawBtn').textContent = 'Verberg Raw JSON';
    } else {
      raw.classList.add('hidden');
      document.getElementById('toggleRawBtn').textContent = 'Toon Raw JSON';
    }
  });

  // ------- Body bouwen uit form
  function buildBodyFromDyn(){
    const sel = document.getElementById('op_select');
    const ops = window.__ENDPOINTS__ || {};
    const cur = ops[sel.value] || {};
    const tmpl = cur.body_template || {};
    const body = {};
    for (const k of Object.keys(tmpl)){
      const v = tmpl[k];
      if (Array.isArray(v)){
        const ph = (v.length===1 && typeof v[0]==='string') ? v[0] : '';
        const rows = Array.from(document.querySelectorAll(`#fld_${k} [data-ph="${ph}"]`));
        const values = rows.map(el => el.value).filter(x=>x!==undefined && x!=="");
        body[k] = values;
      } else {
        const el = document.getElementById(`fld_${k}`);
        if (!el){ body[k] = ""; continue; }
        const type = el.getAttribute('type') || (el.tagName.toLowerCase()==='textarea' ? 'textarea' : 'text');
        let val = el.value;
        if (type === 'number' && val !== "") {
          const n = Number(val); val = (Number.isFinite(n) ? n : val);
        }
        body[k] = val;
      }
    }
    return body;
  }

  // ------- Uitvoeren + Health
  async function executeCall(method, path, body){
    const sid = document.getElementById('session_id').value.trim();
    if (!sid){ alert('Geen sessie/token. Genereer eerst een token.'); return; }
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
      let pretty = txt; try{ pretty = JSON.stringify(JSON.parse(txt), null, 2); }catch(_){}
      document.getElementById('respText').textContent = pretty;
      setProgress('progressCall', false, 100);
      log(`Response: HTTP ${res.status}`);
    }catch(e){
      setProgress('progressCall', false, 0);
      alert('Call mislukt: '+ e.message);
      log('Call error: '+ e.message);
    }
  }

  document.getElementById('runBtn')?.addEventListener('click', async ()=>{
    const method = (document.getElementById('op_method')?.value || 'GET').toUpperCase();
    const path   = document.getElementById('op_path')?.value || '/health';
    const raw = document.getElementById('op_body');
    let body = null;
    if (!raw.classList.contains('hidden')){
      const txt = raw.value; try{ body = txt ? JSON.parse(txt) : (['POST','PUT','PATCH'].includes(method) ? {} : null); }
      catch(e){ alert('Raw JSON is ongeldig.'); return; }
    } else {
      body = buildBodyFromDyn();
      if (!['POST','PUT','PATCH'].includes(method)) body = null;
    }
    await executeCall(method, path, body);
  });

  document.getElementById('healthBtn')?.addEventListener('click', async ()=>{
    await executeCall('GET', '/health', null);
  });

  document.getElementById('clearRespBtn')?.addEventListener('click', ()=>{
    document.getElementById('respText').textContent = '(geen response)';
  });

  // ------- Token form progress
  (()=>{
    const form = document.getElementById('tokenForm');
    const btn  = document.getElementById('genTokenBtn');
    form?.addEventListener('submit', ()=>{
      btn.disabled = true;
      setProgress('progressGen', true, 25);
      setTimeout(()=>setProgress('progressGen', true, 60), 300);
    });
  })();
</script>
__SCOPES_EMBED__
"""

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
    # Scopes: button & panel zitten in de markup; content embed volgt hieronder
    body = body.replace("__SCOPES_EMBED__", scopes_embed or "")

    # Fout/Info
    if error:
        body = body.replace("__ERROR_BLOCK__", f"<div class='error'>⚠️ {error}</div>")
    else:
        body = body.replace("__ERROR_BLOCK__", "")
    if info:
        body = body.replace("__INFO_BLOCK__", f"<div class='muted'>ℹ️ {info}</div>")
    else:
        body = body.replace("__INFO_BLOCK__", "")

    return _page("DCBaaS API Tool", body)

# ---------------- Web routes -----------------------
def register_web_routes(app: Flask):
    import requests

    @app.get("/dcbapi", strict_slashes=False)
    def dcbapi_index():
        return _form()

    @app.post("/dcbapi/token/generate", strict_slashes=False)
    def dcbapi_token_generate():
        try:
            session_id = (request.form.get("session_id") or "").strip() or str(uuid.uuid4())
            issuer = (request.form.get("issuer") or "").strip()
            op_base = (request.form.get("op_base") or "").strip()
            aud_kid = (request.form.get("aud_kid") or "").strip()
            scope = (request.form.get("scope") or "").strip()
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

            # scopes: user + ALWAYS_SCOPES -> set -> één regel
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
                return _form(
                    error=f"Token aanvraag faalde (HTTP {resp.status_code})",
                    result_json=pretty,
                    token_url=token_url,
                    session_id=session_id
                ), resp.status_code

            pretty = json.dumps(data, ensure_ascii=False, indent=2)
            access_token = data.get("access_token") or ""
            scopes_resp = data.get("scope") or ""

            # Sessie bijwerken
            SESSIONS[session_id] = {
                "token": access_token,
                "scopes": scopes_resp,
                "op_base": op_base,
                "created_ts": int(time.time())
            }

            # Map + files
            _ensure_data_dir()
            sd = _session_dir(session_id)
            _save_file(os.path.join(sd, "access_token.txt"), access_token)
            _save_file(os.path.join(sd, "scopes.json"), json.dumps({"scope": scopes_resp}, ensure_ascii=False, indent=2))

            # Scopes embedden voor tooltip
            mapping = _load_scope_mapping()
            scopes_json_script = (
                "<script id='scopesData' type='application/json'>"
                + json.dumps({"scopes": scopes_resp, "mapping": mapping}, ensure_ascii=False)
                + "</script>"
            )

            return _form(
                error=None,
                info=f"Sessie-ID: {session_id}. Token opgeslagen in {sd}/access_token.txt",
                result_json=pretty,
                access_token=access_token,
                token_url=token_url,
                session_id=session_id,
                scopes_embed=scopes_json_script
            )

        except Exception as e:
            return _form(error=f"Fout: {e}"), 400

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
            resp = requests.request(method, url, json=payload if method in ("POST","PUT","PATCH") else None,
                                    headers=headers, timeout=60)

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
            # minimale validatie: key -> {method, path}
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

# ---------------- Standalone -----------------------
if __name__ == "__main__":
    _ensure_config_dir()
    _ensure_data_dir()
    app = Flask("dcbapi_standalone")
    # Laat alle paden zowel met als zonder trailing slash werken
    app.url_map.strict_slashes = False
    register_web_routes(app)
    print("DCBaaS API Tool draait op: http://127.0.0.1:5010/dcbapi")
    app.run("127.0.0.1", 5010, debug=True)
