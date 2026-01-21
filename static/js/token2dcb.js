
// token2dcb.js — tabs, toggles, copy, issuer lock, vault load, JWK upload,
// env radios → OP/API hidden inputs, loading overlay en busy states

function tdcbReady(cb){ if(document.readyState !== 'loading') cb(); else document.addEventListener('DOMContentLoaded', cb); }

// --- Helpers: copy + overlay -------------------------------------------------
async function tdcbCopy(selOrEl, btnId, okText){
  try{
    const el = (typeof selOrEl === 'string') ? document.querySelector(selOrEl) : selOrEl;
    if(!el) return alert('Niets om te kopiëren.');
    const text = (el.value ?? el.textContent ?? '').toString().trim();
    await navigator.clipboard.writeText(text);
    if(btnId){
      const b = document.getElementById(btnId);
      if(b){
        const old = b.textContent;
        b.textContent = okText || 'Gekopieerd ✔';
        b.disabled = true;
        setTimeout(()=>{ b.textContent = old; b.disabled = false; }, 1200);
      }
    }
  }catch(e){ alert('Kopiëren mislukt: ' + (e && e.message ? e.message : e)); }
}
function tdcbShowProgress(stepText){
  const overlay = document.getElementById('tdcb-progress-overlay');
  const label   = document.getElementById('tdcb-progress-text');
  if(!overlay || !label) return;
  label.textContent = (stepText || '') + 'Bezig met verwerken...';
  overlay.style.display = 'flex';
}
function tdcbHideProgress(){
  const overlay = document.getElementById('tdcb-progress-overlay');
  if(overlay) overlay.style.display = 'none';
}

// --- Init --------------------------------------------------------------------
tdcbReady(() => {

  // Tabs
  document.querySelectorAll('.tdcb-tab-btn').forEach(btn=>{
    btn.addEventListener('click',()=>{
      document.querySelectorAll('.tdcb-tab-btn').forEach(b=>b.classList.remove('active'));
      document.querySelectorAll('.tdcb-tab').forEach(t=>t.classList.remove('active'));
      btn.classList.add('active');
      const id = btn.getAttribute('data-tab');
      const tab = document.getElementById(id);
      if(tab) tab.classList.add('active');
    });
  });

  // Generieke toggles
  document.addEventListener('click',(ev)=>{
    const t = ev.target.closest('[data-toggle-target]');
    if(!t) return;
    const id = t.getAttribute('data-toggle-target');
    const showLbl = t.getAttribute('data-show') || 'Toon';
    const hideLbl = t.getAttribute('data-hide') || 'Verberg';
    const el = document.getElementById(id); if(!el) return;
    el.classList.toggle('hidden');
    t.textContent = el.classList.contains('hidden') ? showLbl : hideLbl;
  });

  // Issuer lock/unlock
  const issuerEl = document.getElementById('issuer');
  const issuerLockBtn = document.getElementById('issuerLockBtn');
  function setIssuerLocked(locked){
    if(!issuerEl || !issuerLockBtn) return;
    issuerEl.readOnly = !!locked;
    issuerEl.classList.toggle('ro', !!locked);
    issuerLockBtn.textContent = locked ? '🔒 Ontgrendel' : '🔓 Vergrendel';
    issuerLockBtn.title = locked ? 'Ontgrendel issuer' : 'Vergrendel issuer';
  }
  issuerLockBtn?.addEventListener('click', ()=> setIssuerLocked(!issuerEl.readOnly));
  setIssuerLocked(false);

  // Vault dropdown vullen
  (async function loadVault(){
    try{
      const res = await fetch('/token2dcb/vault.json',{cache:'no-store'});
      if(!res.ok) return;
      const vault = await res.json(); // { kid: {label} }
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

  // Vault keuze → audience/issuer & clear file
  document.getElementById('vault')?.addEventListener('change', (ev)=>{
    const kid = ev.target.value; if(!kid) return;
    const audKid = document.getElementById('aud_kid');
    if(audKid) audKid.value = kid;
    if(issuerEl){ issuerEl.value = kid; setIssuerLocked(true); }
    const f = document.getElementById('private_jwk'); if(f) f.value = "";
  });

  // JWK upload → aud_kid & issuer vullen uit JWK.kid
  (function(){
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
  })();

  // Één radiogroep (env_mode) stuurt op_base (token/health) en api_base (health)
  (function(){
    function activeEnvRadio(){ return document.querySelector('input[name="env_mode"]:checked'); }
    function applyEnv(rad){
      if(!rad) return;
      const op  = rad.getAttribute('data-op');
      const api = rad.getAttribute('data-api');
      const opT = document.getElementById('op_base_tkn');
      const opH = document.getElementById('op_base_hlt');
      const apH = document.getElementById('api_base_hlt');
      if(opT) opT.value = op;
      if(opH) opH.value = op;
      if(apH) apH.value = api;
      // health-knop tooltip
      const hb = document.getElementById('healthBtn');
      if(hb) hb.title = 'GET ' + api + '/health';
    }
    applyEnv(activeEnvRadio());
    document.querySelectorAll('input[name="env_mode"]').forEach(r=>{
      r.addEventListener('change', ()=> applyEnv(r));
    });
  })();

  // Busy states + overlay bij submit (token + health)
  (function(){
    const tForm = document.getElementById('tdcb-form');
    const hForm = document.getElementById('tdcb-health-form');
    const tBtn  = document.getElementById('submitBtn');
    const hBtn  = document.getElementById('healthBtn');

    function ensureSpinner(btn){
      if(!btn || btn.querySelector('.tdcb-btn__spinner')) return;
      const sp = document.createElement('span');
      sp.className = 'tdcb-btn__spinner';
      btn.insertBefore(sp, btn.firstChild);
      btn.insertBefore(document.createTextNode(' '), sp.nextSibling);
    }

    if(tForm && tBtn){
      tForm.addEventListener('submit', ()=>{
        try{
          tBtn.classList.add('is-busy');
          tBtn.setAttribute('disabled','disabled');
          ensureSpinner(tBtn);
          tdcbShowProgress('Token aanvragen… ');
        }catch(e){}
      });
    }
    if(hForm && hBtn){
      hForm.addEventListener('submit', ()=>{
        try{
          hBtn.classList.add('is-busy');
          hBtn.setAttribute('disabled','disabled');
          ensureSpinner(hBtn);
          tdcbShowProgress('Health check… ');
        }catch(e){}
      });
    }
  })();

  // Expose helpers voor inline onclick hooks
  window.tdcbCopyById = (id,btn,ok) => tdcbCopy(document.getElementById(id), btn, ok);
  window.tdcbCopy     = tdcbCopy;
  window.tdcbShowProgress = tdcbShowProgress;
  window.tdcbHideProgress  = tdcbHideProgress;
});
