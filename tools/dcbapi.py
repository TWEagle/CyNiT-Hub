
# -*- coding: utf-8 -*-
"""
DCB API Tool — Application stack (Hub header/footer + Standalone)

- Token flow: client_credentials via OP; client_assertion iss=sub=kid; aud=OP base
- Form 'audience' = kid (client id)  ✅
- ALWAYS_SCOPES één regel, spatie-gescheiden
- Diagnose-tab: decode header/payload (zonder verify) + context
- Manuele token: enkel via /dcbapi/token/generate
- Token wordt weggeschreven naar dcbapi/<env>.dcb (ti.dcb of productie.dcb)
"""

from __future__ import annotations
import json, time, logging, base64
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string
import requests

# Hub layout (header/footer)
try:
    from beheer.main_layout import render_page as hub_render_page  # type: ignore
except Exception:
    hub_render_page = None

# PyJWT
try:
    import jwt  # PyJWT
    from jwt.algorithms import RSAAlgorithm, ECAlgorithm
except Exception as e:
    raise RuntimeError("PyJWT + cryptography vereist. Installeer: pip install PyJWT cryptography") from e

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dcbapi")

# ---- Config ----
APP_PORT = 5010
OP_BASES = [
    "https://authenticatie.vlaanderen.be/op",
    "https://authenticatie-ti.vlaanderen.be/op",
]
TOKEN_SUFFIX = "/v1/token"
EXTAPI = {
    "prod": "https://extapi.dcb.vlaanderen.be",
    "ti":   "https://extapi.dcb-ti.vlaanderen.be",
}
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

# ---- State ----
STATE: Dict[str, Any] = {
    "env": "ti",         # UI switch
    "jwk": None,         # uploaded JWK dict
    "token": None,       # Bearer token
    "token_exp": 0,      # epoch seconds
}

# ---- Helpers ----
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

def _key_from_jwk(jwk_json: str):
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

def _get_extapi_base() -> str:
    return EXTAPI.get(STATE.get("env") or "ti", EXTAPI["ti"])

def _get_op_base() -> str:
    return OP_BASES[0] if STATE.get("env") == "prod" else OP_BASES[1]

def _hub_root() -> Path:
    """
    tools/dcbapi.py -> parent = tools/
                      parents[1] = hub-root (CyNiT-Hub)
    """
    try:
        return Path(__file__).resolve().parents[1]
    except Exception:
        return Path.cwd()

def _save_token_to_file(token: str) -> str:
    """
    Schrijft de token weg als plain-text naar dcbapi/<env>.dcb
    TI  -> dcbapi/ti.dcb
    PROD-> dcbapi/productie.dcb
    """
    hub_root = _hub_root()
    base = hub_root / "dcbapi"
    base.mkdir(parents=True, exist_ok=True)
    env = (STATE.get("env") or "ti")
    fname = "ti.dcb" if env == "ti" else "productie.dcb"
    fp = base / fname
    fp.write_text(token or "", encoding="utf-8")
    logger.info("[TOKEN] saved to %s", str(fp))
    return str(fp)

def _ensure_token() -> Tuple[Optional[str], Optional[str]]:
    """
    Maakt of vernieuwt de token als hij er nog niet is of verlopen is.
    Wordt alleen aangeroepen door /token/generate (manueel).
    """
    now = int(time.time())
    if STATE.get("token") and STATE.get("token_exp", 0) - 30 > now:
        return STATE["token"], None

    jwk = STATE.get("jwk")
    if not jwk:
        return None, "Geen JWK geladen. Upload een private.jwk."
    kid = jwk.get("kid")
    if not kid:
        return None, "JWK mist 'kid' (vereist voor audience/issuer)."

    try:
        key, alg, jwk_obj = _key_from_jwk(json.dumps(jwk))
    except Exception as ex:
        return None, f"JWK ongeldig: {ex}"

    op_base = _get_op_base()
    token_url = op_base.rstrip("/") + TOKEN_SUFFIX

    # JWT client assertion
    now = int(time.time())
    claims = {"iss": kid, "sub": kid, "aud": op_base, "iat": now, "exp": now + 600}
    client_assertion = jwt.encode(claims, key, algorithm=alg)

    scopes = " ".join(sorted(ALWAYS_SCOPES))
    form = {
        "grant_type": "client_credentials",
        "audience": kid,  # <-- audience = client id = kid (zoals gevraagd)
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": client_assertion,
        "scope": scopes,
    }

    try:
        resp = requests.post(token_url, data=form, headers={"Accept": "application/json"}, timeout=30)
        data = resp.json() if resp.headers.get("content-type","").startswith("application/json") else {"_raw": resp.text}
        if resp.status_code >= 400:
            return None, f"Token aanvraag faalde ({resp.status_code}): {json.dumps(data, ensure_ascii=False)}"
        token = data.get("access_token")
        if not token:
            return None, "Token response zonder 'access_token'."
        exp = now + int(data.get("expires_in", 600))
        STATE["token"] = token
        STATE["token_exp"] = exp
        try:
            prev = (token or '')[:24]
            logger.info("[TOKEN] preview=%s… exp=%s env=%s", prev, exp, STATE.get("env"))
        except Exception:
            pass

        # Sla token altijd op naar dcbapi/<env>.dcb
        try:
            _save_token_to_file(token)
        except Exception as _e:
            logger.warning("[TOKEN] persist failed: %s", _e)

        return token, None
    except Exception as ex:
        return None, f"Token aanvraag exception: {ex}"

# ---- UI (content-only; hub wrapper adds header/footer) ----
INDEX_HTML = r"""
<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>DCB API — Application stack</title>
<style>
 :root{ --bg:#0b0b0c; --panel:#111214; --muted:#c7c7c7; --text:#f8f8f8; --accent:#ff4d4f; --ok:#10b981; --err:#ef4444; --line:#2a2b2f; }
 html,body{margin:0;padding:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif}
 .wrap{padding:16px 18px}
 .toolbar{display:flex;gap:18px;align-items:center;flex-wrap:wrap;padding:10px;border-bottom:1px solid var(--line);background:var(--panel);border-radius:8px}
 .radio{display:flex;gap:8px;align-items:center}
 .btn{padding:10px 16px;border:2px solid var(--accent);background:transparent;color:#fff;border-radius:8px;cursor:pointer}
 .btn.disabled{ opacity:.45; pointer-events:none; border-color:#444 !important; box-shadow:none !important; cursor:not-allowed }
 .pill{padding:6px 10px;border:1px solid var(--line);border-radius:8px;color:#c7c7c7;font-size:12px}
 input[type=file]{display:none}
 .light{width:18px;height:18px;border-radius:50%;background:#3a3a3a;border:1px solid #000;box-shadow:inset 0 0 4px rgba(0,0,0,.6),0 0 10px rgba(0,0,0,.3)}
 .ok{background:radial-gradient(circle at 30% 30%, #34d399, #059669 70%);box-shadow:0 0 14px rgba(16,185,129,.55), inset 0 0 4px rgba(0,0,0,.6)}
 .err{background:radial-gradient(circle at 30% 30%, #fb7185, #ef4444 70%);box-shadow:0 0 14px rgba(239,68,68,.55), inset 0 0 4px rgba(0,0,0,.6)}
 .tabs{display:flex;gap:2px;margin-top:14px;border-bottom:1px solid var(--line)}
 .tab{padding:10px 12px;cursor:pointer;border:1px solid var(--line);border-bottom:none;border-radius:8px 8px 0 0;background:#121316;color:#ddd}
 .tab.active{background:#1a1c20;color:#fff;border-color:#34363b}
 .panel{background:#111214;border:1px solid var(--line);border-radius:0 8px 8px 8px;padding:16px;margin-bottom:30px}
 .grid{display:grid;grid-template-columns: 280px 1fr;gap:14px}
 label{display:block;margin-bottom:6px;color:#e7e7e7}
 input[type=text], textarea{width:100%;background:#0f1012;border:1px solid #2b2d31;color:#fff;padding:10px;border-radius:8px}
 textarea{min-height:88px}
 .actions{display:flex;gap:12px;align-items:center;margin-top:10px}
 .result{margin-top:10px;padding:10px;background:#0f1012;border:1px solid #2b2d31;border-radius:8px;font-family:ui-monospace,Consolas,Menlo,monospace;font-size:12px;white-space:pre-wrap}
 /* Loader overlay */
 #dcb-progress-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.75); display: none; align-items:center; justify-content:center; z-index: 2000; }
 .dcb-progress-box { background: rgba(10,15,18,.92); border:1px solid var(--line); padding:20px 30px; border-radius:12px; box-shadow:0 0 20px rgba(0,0,0,.9); min-width:280px; max-width:520px; text-align:center; }
 .dcb-progress-title { font-size:1.05em; margin-bottom:12px; color:#e8f2f2; }
 .dcb-progress-outer { width:100%; height:10px; background:#222; border-radius:6px; overflow:hidden; margin-top:6px; }
 .dcb-progress-inner { width:40%; height:100%; background:linear-gradient(90deg,#35e6df,#2dd4bf); border-radius:6px; animation:dcb-bar-move 1.0s linear infinite; }
 @keyframes dcb-bar-move { 0% { margin-left:-40%; } 100% { margin-left:100%; } }
</style>
</head>
<body>
<div class="wrap">
  <div id="dcb-progress-overlay">
    <div class="dcb-progress-box">
      <div class="dcb-progress-title" id="dcb-progress-text">Bezig…</div>
      <div class="dcb-progress-outer"><div class="dcb-progress-inner"></div></div>
      <div style="margin-top:10px;color:#9fb3b3;">Even geduld…</div>
    </div>
  </div>

  <div class="toolbar">
    <div class="radio"><input id="env_prod" type="radio" name="env" value="prod"><label for="env_prod">Productie</label></div>
    <div class="radio"><input id="env_ti" type="radio" name="env" value="ti" checked><label for="env_ti">T&I</label></div>
    <span class="pill" id="baseUrl"></span>
    <span class="pill" id="tokenStatus">Token: niet gezet</span>
    <label class="btn" id="btnJwk" for="jwkFile">Kies bestand</label>
    <input id="jwkFile" type="file" accept=".jwk,.json" />
    <button class="btn" id="btnGenToken">Genereer token</button>
    <button class="btn" id="btnHealth">Health</button>
    <div>Backend:</div><div class="light" id="l-backend"></div>
    <div>Database:</div><div class="light" id="l-database"></div>
    <div>FWP:</div><div class="light" id="l-fwp"></div>
    <div>ES:</div><div class="light" id="l-es"></div>
  </div>

  <div class="tabs">
    <div class="tab active" data-tab="app_add">App Toevoegen</div>
    <div class="tab" data-tab="app_update">App Updaten</div>
    <div class="tab" data-tab="app_delegate">App Delegeren</div>
    <div class="tab" data-tab="app_approve">App Goedkeuren</div>
    <div class="tab" data-tab="app_delete">App Verwijderen</div>
    <div class="tab" data-tab="diag">Diagnose</div>
  </div>

  <div class="panel">
    <div id="panel_app_add">
      <div class="grid">
        <div><b>App Toevoegen</b><br>organization_code is optioneel</div>
        <div>
          <label for="add_name">Naam *</label><input id="add_name" type="text">
          <label for="add_reason" style="margin-top:10px">Reden *</label><textarea id="add_reason"></textarea>
          <label for="add_org" style="margin-top:10px">Organization code (optioneel)</label><input id="add_org" type="text">
          <div class="actions"><button class="btn" id="btnAdd">Verstuur</button></div>
          <div id="resAdd" class="result" hidden></div>
        </div>
      </div>
    </div>

    <div id="panel_app_update" style="display:none">
      <div class="grid">
        <div><b>App Updaten</b><br>organization_code is optioneel</div>
        <div>
          <label for="upd_name">Naam *</label><input id="upd_name" type="text">
          <label for="upd_reason" style="margin-top:10px">Reden *</label><textarea id="upd_reason"></textarea>
          <label for="upd_org" style="margin-top:10px">Organization code (optioneel)</label><input id="upd_org" type="text">
          <div class="actions"><button class="btn" id="btnUpdate">Verstuur</button></div>
          <div id="resUpdate" class="result" hidden></div>
        </div>
      </div>
    </div>

    <div id="panel_app_delegate" style="display:none">
      <div class="grid">
        <div><b>App Delegeren</b><br>duration is optioneel</div>
        <div>
          <label for="del_name">Naam *</label><input id="del_name" type="text">
          <label for="del_orgd" style="margin-top:10px">Organization code (gedelegeerd) *</label><input id="del_orgd" type="text">
          <label style="margin-top:10px">Duur (maanden) (optioneel)</label>
          <div id="del_durations"></div>
          <div class="actions"><button class="btn" id="btnDelegate">Verstuur</button></div>
          <div id="resDelegate" class="result" hidden></div>
        </div>
      </div>
    </div>

    <div id="panel_app_approve" style="display:none">
      <div class="grid">
        <div><b>App Goedkeuren</b><br>duration is optioneel</div>
        <div>
          <label for="appr_name">Naam *</label><input id="appr_name" type="text">
          <label style="margin-top:10px">Duur (maanden) (optioneel)</label>
          <div id="appr_durations"></div>
          <div class="actions"><button class="btn" id="btnApprove">Verstuur</button></div>
          <div id="resApprove" class="result" hidden></div>
        </div>
      </div>
    </div>

    <div id="panel_app_delete" style="display:none">
      <div class="grid">
        <div><b>App Verwijderen</b><br>organization_code is optioneel</div>
        <div>
          <label for="delv_name">Naam *</label><input id="delv_name" type="text">
          <label for="delv_org" style="margin-top:10px">Organization code (optioneel)</label><input id="delv_org" type="text">
          <div class="actions"><button class="btn" id="btnDelete">Verstuur</button></div>
          <div id="resDelete" class="result" hidden></div>
        </div>
      </div>
    </div>

    <div id="panel_diag" style="display:none">
      <div class="grid">
        <div><b>Token & Omgeving Diagnose</b><br>Decode header/payload (zonder signature).</div>
        <div>
          <div class="actions"><button class="btn" id="btnDiag">Vernieuw diagnose</button></div>
          <div id="resDiag" class="result" hidden></div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
  const DURATIONS = [0,1,3,6,12,24];
  function byId(id){return document.getElementById(id)}
  function setLights(m){['backend','database','fwp','es'].forEach(k=>{const el=byId('l-'+k);el.classList.remove('ok','err'); if(!m) return; el.classList.add(m[k]?'ok':'err')})}
  function setBtnState(el, state){ if(!el) return; el.classList.remove('state-ok','state-bad','state-warn'); if(state){ el.classList.add('state-'+state); } }
  function setDisabled(on){ ['btnJwk','btnGenToken','btnHealth','btnAdd','btnUpdate','btnDelegate','btnApprove','btnDelete','btnDiag'].forEach(id=>{ const el=byId(id); if(el) el.classList.toggle('disabled', !!on); }); const fi=byId('jwkFile'); if(fi) fi.disabled=!!on; }
  function showLoader(msg){ const ov=byId('dcb-progress-overlay'); const t=byId('dcb-progress-text'); if(t) t.textContent = msg || 'Bezig…'; if(ov) ov.style.display='flex'; setDisabled(true); }
  function hideLoader(){ const ov=byId('dcb-progress-overlay'); if(ov) ov.style.display='none'; setDisabled(false); }
  async function withLoader(message, fn){ try{ showLoader(message); return await fn(); } finally { hideLoader(); } }

  // env switch
  document.querySelectorAll('input[name="env"]').forEach(r=>{
    r.addEventListener('change', async (e)=>{
      const env=e.target.value;
      await withLoader('Omgeving wijzigen…', async()=>{
        const res=await fetch('set_env',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({env})});
        const js=await res.json(); byId('baseUrl').textContent=js.base_url||''; byId('tokenStatus').textContent='Token: niet gezet (genereer opnieuw)';
      });
    });
  });
  (async()=>{const res=await fetch('get_env'); const js=await res.json(); byId('baseUrl').textContent=js.base_url||'';})();

  // durations radios
  function renderDur(cId){const c=byId(cId); if(!c) return; c.innerHTML=''; DURATIONS.forEach(v=>{const id=cId+'_'+v; const w=document.createElement('label'); w.style.marginRight='8px'; w.innerHTML=`<input type="radio" name="${cId}" value="${v}" id="${id}"> ${v}`; c.appendChild(w)}); const clr=document.createElement('button'); clr.className='btn'; clr.textContent='Leegmaken'; clr.onclick=()=>document.querySelectorAll(`input[name='${cId}']`).forEach(x=>x.checked=false); c.appendChild(clr)}
  renderDur('del_durations'); renderDur('appr_durations');

  // jwk upload
  byId('jwkFile').addEventListener('change', async (e)=>{
    const f=e.target.files[0]; if(!f) return;
    await withLoader('JWK uploaden…', async()=>{
      const fd=new FormData(); fd.append('file', f);
      const res=await fetch('upload_jwk',{method:'POST',body:fd}); const js=await res.json();
      if(js.ok){ byId('tokenStatus').textContent='JWK ok — token wordt on-demand opgehaald'; } else { alert(js.error||'JWK fout'); }
    });
  });

  // Health
  byId('btnHealth').addEventListener('click', async ()=>{
    await withLoader('Health check…', async()=>{
      setLights(null); const res=await fetch('health',{method:'POST'}); const js=await res.json(); if(js.ok){ setLights(js.mapped); setBtnState(byId('btnHealth'),'ok'); } else { setBtnState(byId('btnHealth'),'bad'); alert(js.error||'Health fout') }
    });
  });

  // Genereer token (handmatig)
  byId('btnGenToken').addEventListener('click', async ()=>{
    await withLoader('Token genereren…', async()=>{
      const res = await fetch('token/generate',{method:'POST'});
      const js  = await res.json();
      if(js.ok){
        const expStr  = js.expires ? (' (exp '+ new Date(js.expires*1000).toLocaleTimeString()+')') : '';
        const fileStr = js.token_file ? (' • opgeslagen in: ' + js.token_file) : '';
        byId('tokenStatus').textContent = 'Token: ok' + expStr + fileStr;
        console.log('token preview:', js.token_preview||'(none)');
      } else { alert(js.error||'Token generatie fout'); }
    });
  });

  // helpers
  function pickDuration(name){const x=document.querySelector(`input[name='${name}']:checked`); return x?parseInt(x.value,10):null}
  async function postJSON(url, payload){ return await withLoader('Versturen…', async()=>{ const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); const js=await res.json(); return {ok: res.ok, js}; }); }

  // Application actions (allemaal vereisen token)
  byId('btnAdd').addEventListener('click', async ()=>{ const p={name:byId('add_name').value.trim(), reason:byId('add_reason').value.trim(), organization_code:byId('add_org').value.trim()}; const {ok, js}=await postJSON('application/add', p); const el=byId('resAdd'); el.hidden=false; el.textContent=JSON.stringify(js,null,2); if(!ok) alert('Fout: details in resultaat') })
  byId('btnUpdate').addEventListener('click', async ()=>{ const p={name:byId('upd_name').value.trim(), reason:byId('upd_reason').value.trim(), organization_code:byId('upd_org').value.trim()}; const {ok, js}=await postJSON('application/update', p); const el=byId('resUpdate'); el.hidden=false; el.textContent=JSON.stringify(js,null,2); if(!ok) alert('Fout: details in resultaat') })
  byId('btnDelegate').addEventListener('click', async ()=>{ const p={name:byId('del_name').value.trim(), organization_code_delegated:byId('del_orgd').value.trim(), duration:pickDuration('del_durations')}; const {ok, js}=await postJSON('application/delegate', p); const el=byId('resDelegate'); el.hidden=false; el.textContent=JSON.stringify(js,null,2); if(!ok) alert('Fout: details in resultaat') })
  byId('btnApprove').addEventListener('click', async ()=>{ const p={name:byId('appr_name').value.trim(), duration:pickDuration('appr_durations')}; const {ok, js}=await postJSON('application/approve', p); const el=byId('resApprove'); el.hidden=false; el.textContent=JSON.stringify(js,null,2); if(!ok) alert('Fout: details in resultaat') })
  byId('btnDelete').addEventListener('click', async ()=>{ const p={name:byId('delv_name').value.trim(), organization_code:byId('delv_org').value.trim()}; const {ok, js}=await postJSON('application/delete', p); const el=byId('resDelete'); el.hidden=false; el.textContent=JSON.stringify(js,null,2); if(!ok) alert('Fout: details in resultaat') })

  // Diagnose
  byId('btnDiag').addEventListener('click', async ()=>{
    await withLoader('Diagnose ophalen…', async()=>{
      const res = await fetch('token/diagnose'); const js = await res.json(); const box=byId('resDiag'); box.hidden=false; box.textContent=JSON.stringify(js, null, 2);
    });
  });

  // Tabs
  const tabs = document.querySelectorAll('.tab');
  tabs.forEach(t=>t.addEventListener('click',()=>{ tabs.forEach(x=>x.classList.remove('active')); t.classList.add('active'); document.querySelectorAll('[id^=panel_]').forEach(p=>p.style.display='none'); const target='panel_'+t.dataset.tab; document.getElementById(target).style.display=''; }))
</script>
</body>
</html>
"""

# ---- Routes ----
def register_web_routes(app: Flask, base_path: str = "/dcbapi"):
    def _render_page():
        content = render_template_string(INDEX_HTML)
        if hub_render_page:
            return hub_render_page(title="DCB API — Application stack", content_html=content)
        return content

    bp = base_path.rstrip("/")

    @app.get(bp + "/")
    def dcbapi_index():
        return _render_page()

    @app.post(bp + "/set_env")
    def dcbapi_set_env():
        data = request.get_json(force=True, silent=True) or {}
        env = data.get("env")
        if env not in EXTAPI:
            return jsonify({"ok": False, "error": "Invalid environment"}), 400
        STATE["env"] = env
        # reset in-memory token; bestand blijft staan
        STATE["token"] = None
        STATE["token_exp"] = 0
        return jsonify({"ok": True, "base_url": _get_extapi_base(), "op_base": _get_op_base()})

    @app.get(bp + "/get_env")
    def dcbapi_get_env():
        return jsonify({"env": STATE.get("env"), "base_url": _get_extapi_base(), "op_base": _get_op_base()})

    @app.post(bp + "/upload_jwk")
    def dcbapi_upload_jwk():
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "No file uploaded"}), 400
        f = request.files["file"]
        try:
            jwk = json.loads(f.read().decode("utf-8"))
            STATE["jwk"] = jwk
            STATE["token"] = None
            STATE["token_exp"] = 0
            return jsonify({"ok": True, "kid": jwk.get("kid"), "kty": jwk.get("kty"), "alg": jwk.get("alg")})
        except Exception as ex:
            return jsonify({"ok": False, "error": f"Invalid JWK: {ex}"}), 400

    @app.post(bp + "/health")
    def dcbapi_health():
        url = _get_extapi_base() + "/health"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            r = data.get("response", {}) if isinstance(data, dict) else {}
            mapped = {
                "backend": bool(r.get("backend")) is True,
                "database": bool(r.get("database")) is True,
                "fwp": bool(r.get("fwp")) is True,
                "es": bool(r.get("es")) is True,
            }
            return jsonify({"ok": True, "mapped": mapped, "raw": data})
        except Exception as ex:
            return jsonify({"ok": False, "error": str(ex)}), 502

    # Token genereren (manueel)
    @app.post(bp + "/token/generate")
    def dcbapi_token_generate():
        tok, err = _ensure_token()
        if err:
            return jsonify({"ok": False, "error": err}), 400
        try:
            token_file = _save_token_to_file(tok or "")
        except Exception:
            token_file = None
        return jsonify({
            "ok": True,
            "expires": STATE.get("token_exp", 0),
            "scopes": " ".join(sorted(ALWAYS_SCOPES)),
            "token_preview": (STATE.get("token") or "")[:24] + "…",
            "token_file": token_file,
        })

    # Diagnose (decode no verify)
    def _b64url_decode(s):
        s = s.encode('utf-8') if isinstance(s, str) else s
        pad = b'=' * (-len(s) % 4)
        try:
            return base64.urlsafe_b64decode(s + pad)
        except Exception:
            return b''
    def _jwt_decode_noverify(tok):
        try:
            parts = (tok or '').split('.')
            if len(parts) < 2:
                return {}, {}
            header = _b64url_decode(parts[0]).decode('utf-8') or '{}'
            payload = _b64url_decode(parts[1]).decode('utf-8') or '{}'
            return json.loads(header), json.loads(payload)
        except Exception:
            return {}, {}

    @app.get(bp + "/token/diagnose")
    def dcbapi_token_diagnose():
        now = int(time.time())
        tok = STATE.get("token") or ''
        exp = int(STATE.get("token_exp") or 0)
        h, pld = _jwt_decode_noverify(tok)
        jwk = STATE.get('jwk') or {}
        form_audience = (jwk.get('kid') or '')
        return jsonify({
            "env": STATE.get("env"),
            "base_urls": {"extapi": _get_extapi_base(), "op": _get_op_base()},
            "jwk": {"present": bool(jwk), "kid": jwk.get('kid'), "kty": jwk.get('kty'), "alg": jwk.get('alg')},
            "token": {
                "present": bool(tok),
                "expires": exp,
                "expires_in": (exp - now) if exp > 0 else None,
                "header": h,
                "payload": pld,
                "preview": (tok[:24] + '…') if tok else None,
            },
            "scopes": sorted(list(ALWAYS_SCOPES)),
            "client_form": {"grant_type": "client_credentials", "audience": form_audience},
        })

    # ---- Application endpoints ----
    def _auth_headers():
        # Geen auto-token; vereist: eerst /token/generate
        now = int(time.time())
        tok = STATE.get("token")
        exp = int(STATE.get("token_exp") or 0)
        if not tok or exp <= now:
            return None, jsonify({"ok": False, "error": "Geen (geldige) token. Klik \"Genereer token\" eerst."}), 400
        logger.info("[AUTH] bearer set: %s…", (tok or "")[:16])
        return {"Authorization": f"Bearer {tok}", "Origin": "localhost", "Content-Type": "application/json"}, None, None

    def _post_json(path: str, payload: dict):
        headers, err_resp, status = _auth_headers()
        if err_resp:
            return err_resp, status
        url = _get_extapi_base() + path
        try:
            resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
            out = resp.json() if resp.headers.get("content-type","").startswith("application/json") else {"_raw": resp.text}
            return (jsonify({"ok": resp.status_code < 400, "status": resp.status_code, "url": url, "payload": payload, "response": out}), resp.status_code)
        except Exception as ex:
            return jsonify({"ok": False, "error": str(ex)}), 502

    @app.post(bp + "/application/add")
    def dcbapi_app_add():
        body = request.get_json(force=True, silent=True) or {}
        name = (body.get("name") or "").strip()
        reason = (body.get("reason") or "").strip()
        if not name or not reason:
            return jsonify({"ok": False, "error": "'name' en 'reason' zijn verplicht"}), 400
        payload = {"name": name, "reason": reason}
        if body.get("organization_code"):
            payload["organization_code"] = body.get("organization_code")
        return _post_json("/application/add", payload)

    @app.post(bp + "/application/update")
    def dcbapi_app_update():
        body = request.get_json(force=True, silent=True) or {}
        name = (body.get("name") or "").strip()
        reason = (body.get("reason") or "").strip()
        if not name or not reason:
            return jsonify({"ok": False, "error": "'name' en 'reason' zijn verplicht"}), 400
        payload = {"name": name, "reason": reason}
        if body.get("organization_code"):
            payload["organization_code"] = body.get("organization_code")
        return _post_json("/application/update", payload)

    @app.post(bp + "/application/delegate")
    def dcbapi_app_delegate():
        body = request.get_json(force=True, silent=True) or {}
        name = (body.get("name") or "").strip()
        orgd = (body.get("organization_code_delegated") or "").strip()
        if not name or not orgd:
            return jsonify({"ok": False, "error": "'name' en 'organization_code_delegated' zijn verplicht"}), 400
        payload = {"name": name, "organization_code": orgd}
        if body.get("duration") is not None:
            payload["duration"] = int(body.get("duration"))
        return _post_json("/application/delegate", payload)

    @app.post(bp + "/application/approve")
    def dcbapi_app_approve():
        body = request.get_json(force=True, silent=True) or {}
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "'name' is verplicht"}), 400
        payload = {"name": name}
        if body.get("duration") is not None:
            payload["duration"] = int(body.get("duration"))
        return _post_json("/application/approve", payload)

    @app.post(bp + "/application/delete")
    def dcbapi_app_delete():
        body = request.get_json(force=True, silent=True) or {}
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "'name' is verplicht"}), 400
        payload = {"name": name}
        if body.get("organization_code"):
            payload["organization_code"] = body.get("organization_code")
        return _post_json("/application/delete", payload)

    # --- Noop sink voor click logging om 500-logs te vermijden ---
    @app.post("/_log/click")
    def _noop_click_logger():
        return ("", 204)

# ---- Standalone bootstrap (optioneel) ----
def create_app() -> Flask:
    app = Flask("dcbapi_tool")
    register_web_routes(app, base_path="/")
    return app

if __name__ == "__main__":
    app = create_app()
    logger.info("DCB API Tool (application stack) op http://127.0.0.1:%s/", APP_PORT)
    app.run(host="0.0.0.0", port=APP_PORT, debug=True)
