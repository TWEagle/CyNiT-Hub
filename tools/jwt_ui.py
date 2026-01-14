
# tools/jwt_ui.py
"""
JWT Generator tool for CyNiT-Hub
- Routes:
    GET  /jwt               → formulier (links uitleg, rechts invulvelden)
    POST /jwt               → token genereren (iat=now, exp=now+10m, sub=iss)
    GET  /jwt/download/<id> → token downloaden als tekstbestand
- UI:
    - Download JWT
    - Kopieer token
    - Toon/Verberg token
    - Toon/Verberg claims
    - Copy claims (JSON)
- Opmaak:
    Split layout (links uitleg, rechts formulier), donkere inputs (#111, witte tekst),
    sluit aan op bestaande main.css (.panel, .in, .btn). Fallback CSS als beheer.main_layout
    niet aanwezig is.
"""

from __future__ import annotations
import json, time, uuid, base64
from flask import request, url_for, abort, Response

# In-memory opslag van tokens (kortlevend)
TOKENS: dict[str, str] = {}

ALLOWED_AUDIENCES = {
    "https://authenticatie.vlaanderen.be/op",
    "https://authenticatie-ti.vlaanderen.be/op",
}

# --- JWK helpers ---
try:
    import jwt  # PyJWT
    from jwt.algorithms import RSAAlgorithm, ECAlgorithm
except Exception as e:  # pragma: no cover
    raise RuntimeError("PyJWT is vereist. Installeer: pip install PyJWT cryptography") from e


def _choose_alg_from_jwk(jwk_obj: dict) -> str:
    kty = jwk_obj.get("kty")
    if kty == "RSA":
        return "RS256"
    if kty == "EC":
        crv = jwk_obj.get("crv", "")
        return {
            "P-256": "ES256", "secp256r1": "ES256",
            "P-384": "ES384", "secp384r1": "ES384",
            "P-521": "ES512", "secp521r1": "ES512",
        }.get(crv, "ES256")
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
    return key, alg


# --- Rendering helpers ---
def _page(title: str, body_html: str):
    """
    Wrap body_html met jouw beheer.main_layout indien beschikbaar; anders fallback
    met compacte, donkere stijl die op je hub lijkt.
    """
    try:
        from beheer.main_layout import render_page  # type: ignore
        return render_page(title=title, content_html=body_html)
    except Exception:
        # Minimal fallback layout (zwarte achtergrond, witte tekst, panel/in/btn)
        return (
            "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
            f"<title>{title}</title>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>"
            "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:2rem;background:#000;color:#e8f2f2}"
            ".panel{background:rgba(10,15,18,.85);border:1px solid rgba(255,255,255,.10);border-radius:18px;"
            "box-shadow:0 12px 40px rgba(0,0,0,.55);padding:24px}"
            ".in{width:100%;padding:10px 12px;border-radius:10px;border:1px solid rgba(255,255,255,.10);"
            "background:#111;color:#fff;outline:none}"
            ".btn{display:inline-flex;align-items:center;gap:8px;padding:10px 12px;border-radius:10px;"
            "border:1px solid rgba(255,255,255,.10);background:#35e6df;color:#000;cursor:pointer;font-weight:700}"
            ".btn:hover{filter:brightness(0.95)}"
            ".jwt-flex{display:flex;gap:32px;align-items:flex-start}"
            ".jwt-info{flex:1 1 0;min-width:240px}"
            ".jwt-form{flex:1 1 0;min-width:320px;display:flex;flex-direction:column;gap:14px}"
            ".download{margin-top:16px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}"
            ".hidden{display:none}"
            "pre{background:#0b1020;color:#cfe3ff;padding:12px;border-radius:8px;overflow:auto}"
            "@media(max-width:800px){.jwt-flex{flex-direction:column;gap:18px}.jwt-info,.jwt-form{min-width:0}}"
            "</style></head><body>"
            + body_html +
            "</body></html>"
        )


def _form(error: str | None = None, download_url: str | None = None,
          token: str | None = None, claims_json: str | None = None) -> str:
    """
    Bouwt de split layout (links info, rechts form).
    Geen f-strings in HTML/JS; we gebruiken placeholders + .replace().
    """

    body = """
<div class="panel jwt-panel">
  <div class="jwt-flex">
    <!-- Uitleg links -->
    <div class="jwt-info">
      <h2>JWT generator</h2>
      <p>
        Vul <strong>issuer</strong> in, kies de <strong>audience</strong>, upload een <strong>private.jwk</strong>.<br>
        <small>Subject wordt automatisch gelijk aan issuer. <code>iat</code> en <code>exp</code> worden server-side gezet.</small>
      </p>
      <ul>
        <li><b>Issuer</b>: unieke ID (meestal een GUID)</li>
        <li><b>Audience</b>: kies productie of test</li>
        <li><b>private.jwk</b>: upload je private JWK (RSA/EC/HMAC)</li>
      </ul>
      <p class="muted">Resultaat: downloadbare en kopieerbare JWT + claims.</p>
    </div>

    <!-- Formulier rechts -->
    <form method="post" action="/jwt" enctype="multipart/form-data" class="jwt-form">
      <label for="issuer">Issuer</label>
      <input class="in" id="issuer" name="issuer" type="text" required placeholder="bijv. 2ea9d30f-dcb3-4936-b7a6-68d458d0236c" />

      <label for="audience">Audience</label>
      <select class="in" id="audience" name="audience" required>
        <option value="https://authenticatie.vlaanderen.be/op">https://authenticatie.vlaanderen.be/op</option>
        <option value="https://authenticatie-ti.vlaanderen.be/op">https://authenticatie-ti.vlaanderen.be/op</option>
      </select>

      <label for="subject">Subject (altijd gelijk aan issuer)</label>
      <input class="in" id="subject" name="subject" type="text" readonly />

      <label for="private_jwk">private.jwk (JWK JSON)</label>
      <input class="in" id="private_jwk" name="private_jwk" type="file" accept=".jwk,application/json" required />

      <button class="btn" type="submit">Genereer JWT</button>
    </form>
  </div>

  <!-- Resultaat / knoppen -->
  __RESULT_SECTION__
</div>
"""

    # Errormelding (bovenaan resultaatgedeelte)
    result_section = ""
    if error:
        result_section += "<div class='error'>⚠️ " + str(error) + "</div>"

    # Download/Copy/Toggles + panels
    if download_url:
        token_safe = (token or "").replace("<", "&lt;").replace(">", "&gt;")
        claims_safe = (claims_json or "").replace("<", "&lt;").replace(">", "&gt;")

        result_section += """
  <div class="ok">✅ JWT aangemaakt.</div>
  <div class="download">
    __DL_ANCHOR__
    <button id="copyBtn" class="btn" type="button">Kopieer token</button>
    <button id="toggleTokenBtn" class="btn" type="button">Toon token</button>
    <button id="toggleClaimsBtn" class="btn" type="button">Toon claims</button>
    <button id="copyClaimsBtn" class="btn" type="button">Copy claims</button>
  </div>

  <div id="tokenPanel" class="hidden" aria-live="polite">
    <h3>Token</h3>
    <pre id="tokenText">__TOKEN__</pre>
  </div>

  <div id="claimsPanel" class="hidden" aria-live="polite">
    <h3>Claim set</h3>
    <pre id="claimsText">__CLAIMS__</pre>
  </div>

  <script>
    // subject = issuer (right column)
    const issuerInput = document.getElementById('issuer');
    const subjectInput = document.getElementById('subject');
    function syncSubject(){ subjectInput.value = issuerInput.value; }
    issuerInput.addEventListener('input', syncSubject);
    window.addEventListener('DOMContentLoaded', syncSubject);

    // Copy token
    const copyBtn = document.getElementById('copyBtn');
    const tokenPanel = document.getElementById('tokenPanel');
    const tokenText = document.getElementById('tokenText');
    copyBtn.addEventListener('click', async () => {
      try {
        const inlineToken = tokenText ? tokenText.textContent.trim() : '';
        // fallback: haal via download-url als panel nog niet open staat
        const token = inlineToken || (await (await fetch('__DOWNLOAD_URL__')).text());
        await navigator.clipboard.writeText(token.trim());
        copyBtn.textContent = 'Gekopieerd ✔';
        copyBtn.disabled = true;
        setTimeout(() => { copyBtn.textContent = 'Kopieer token'; copyBtn.disabled = false; }, 2000);
      } catch(e){ alert('Kopiëren mislukt: ' + e.message); }
    });

    // Toggles (token/claims)
    const claimsPanel = document.getElementById('claimsPanel');
    const toggleTokenBtn = document.getElementById('toggleTokenBtn');
    const toggleClaimsBtn = document.getElementById('toggleClaimsBtn');
    function toggle(el, btn, showLabel, hideLabel){
      const isHidden = el.classList.contains('hidden');
      el.classList.toggle('hidden');
      btn.textContent = isHidden ? hideLabel : showLabel;
    }
    toggleTokenBtn.addEventListener('click', () =>
      toggle(tokenPanel, toggleTokenBtn, 'Toon token','Verberg token'));
    toggleClaimsBtn.addEventListener('click', () =>
      toggle(claimsPanel, toggleClaimsBtn, 'Toon claims','Verberg claims'));

    // Copy claims JSON
    const copyClaimsBtn = document.getElementById('copyClaimsBtn');
    const claimsText = document.getElementById('claimsText');
    copyClaimsBtn.addEventListener('click', async () => {
      try {
        const claims = claimsText.textContent.trim();
        await navigator.clipboard.writeText(claims);
        copyClaimsBtn.textContent = 'Claims gekopieerd ✔';
        copyClaimsBtn.disabled = true;
        setTimeout(() => { copyClaimsBtn.textContent = 'Copy claims'; copyClaimsBtn.disabled = false; }, 2000);
      } catch(e){ alert('Kopiëren mislukt: ' + e.message); }
    });
  </script>
"""
        result_section = (
            result_section
            .replace("__DL_ANCHOR__", f"{download_url}Download JWT</a>")
            .replace("__DOWNLOAD_URL__", download_url)
            .replace("__TOKEN__", token_safe)
            .replace("__CLAIMS__", claims_safe)
        )

    # Injecteer de result section in body
    body = body.replace("__RESULT_SECTION__", result_section)

    return _page("JWT", body)


# ---- Public hook for master.register_tools() ----
def register_web_routes(app):
    @app.get("/jwt")
    def jwt_index():
        return _form()

    @app.post("/jwt")
    def jwt_generate():
        try:
            issuer = (request.form.get("issuer") or "").strip()
            audience = (request.form.get("audience") or "").strip()
            if not issuer:
                return _form(error="Issuer is verplicht."), 400
            if audience not in ALLOWED_AUDIENCES:
                return _form(error="Audience is ongeldig."), 400

            f = request.files.get("private_jwk")
            if not f or not f.filename:
                return _form(error="Upload een private.jwk (JWK JSON)."), 400

            jwk_json = f.read().decode("utf-8")
            key, alg = _key_from_jwk(jwk_json)

            now = int(time.time())
            claims = {
                "iss": issuer,
                "sub": issuer,     # subject = issuer
                "aud": audience,
                "iat": now,
                "exp": now + 600,  # 10 minuten
            }
            token = jwt.encode(claims, key, algorithm=alg)

            token_id = str(uuid.uuid4())
            TOKENS[token_id] = token
            dl = url_for("jwt_download", token_id=token_id, _external=False)
            return _form(error=None, download_url=dl,
                         token=token,
                         claims_json=json.dumps(claims, ensure_ascii=False, indent=2))

        except Exception as e:
            return _form(error=f"Fout: {e}"), 400

    @app.get("/jwt/download/<token_id>")
    def jwt_download(token_id: str):
        token = TOKENS.get(token_id)
        if not token:
            abort(404)
        return Response(
            token,
            mimetype="text/plain",
            headers={"Content-Disposition": 'attachment; filename=\"token.jwt\"'},
        )
