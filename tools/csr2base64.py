#!/usr/bin/env python3
"""tools/csr2base64.py

CSR2Base64 (CyNiT-Hub tool + standalone).

Wat doet dit?
- Upload of plak CSR/CRT/PEM (of eender welke tekst/binary)
- Output: Base64 encoded, single-line, kopieerbaar + download .b64

Hub-integratie
- master.py laadt tools als "tools.<script zonder .py>" en verwacht:
    def register_web_routes(app: Flask) -> None

Routes (Hub)
- GET/POST /csr2base64
- GET      /csr2base64/download

Standalone
- python .\\tools\\csr2base64.py  -> http://127.0.0.1:5008/
  (root redirect naar /csr2base64)

Opmerking
- We encoden de *ruwe bytes*.
  * Upload: exact file bytes.
  * Plakken: UTF-8 bytes (line-endings genormaliseerd naar '\n').
"""

from __future__ import annotations

import base64
import sys
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, make_response, redirect, render_template_string, request, send_file

# =========================================================
# Hub layout import (met standalone fallback)
# =========================================================

_THIS = Path(__file__).resolve()
_ROOT = _THIS.parent.parent  # .../CyNiT-Hub
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    # In jouw hub lijkt render_page keyword-only args te verwachten:
    #   render_page(*, title=..., content_html=...)
    from beheer.main_layout import render_page as hub_render_page  # type: ignore
except Exception:

    def hub_render_page(*, title: str, content_html: str) -> str:  # type: ignore
        """Fallback HTML wrapper als 'beheer' niet bestaat (pure standalone buiten hub)."""
        return f"""<!doctype html>
<html lang='nl'>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  <title>{title}</title>
  <style>
    :root {{ --border: rgba(255,255,255,.14); --muted: #9fb3b3; }}
    body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial; margin:0; background:#0b0f12; color:#e8f2f2;}}
    .top{{padding:14px 18px; border-bottom:1px solid rgba(255,255,255,.10); background:rgba(0,0,0,.25);}}
    .top a{{color:#9fb3b3; text-decoration:none;}}
    .main{{padding:18px;}}
  </style>
</head>
<body>
  <div class='top'><a href='/'>CSR2Base64</a> <span style='opacity:.6'>/</span> {title}</div>
  <div class='main'>{content_html}</div>
</body>
</html>"""


LAST_RESULT: Optional[Dict[str, Any]] = None


def _b64_single_line(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _safe_stem(filename: str) -> str:
    stem = Path(filename or "output").stem or "output"
    safe = "".join(ch if ch.isalnum() or ch in "-_. ," else "_" for ch in stem).strip()
    safe = safe.replace(" ", "_")
    return (safe[:80] or "output")


CONTENT_TEMPLATE = r"""
<style>
  .wrap { max-width: 1100px; margin: 0 auto; }
  .card {
    background: rgba(10,15,18,.85);
    border-radius: 12px;
    padding: 16px 20px;
    margin-bottom: 18px;
    border: 1px solid var(--border, rgba(255,255,255,.10));
  }
  .muted { color: var(--muted, #9fb3b3); }
  .row { display:flex; gap: 14px; flex-wrap: wrap; }
  .col { flex: 1 1 440px; }

  textarea {
    width: 100%;
    min-height: 220px;
    resize: vertical;
    padding: 10px 12px;
    border-radius: 10px;
    background: #111;
    color: #fff;
    border: 1px solid var(--border, rgba(255,255,255,.18));
    font-family: Consolas, ui-monospace, SFMono-Regular, Menlo, Monaco, "Liberation Mono", monospace;
    font-size: 0.92rem;
    line-height: 1.35;
    box-sizing: border-box;
  }
  input[type=file] { width: 100%; }

  .btns { display:flex; gap:10px; flex-wrap:wrap; margin-top: 10px; }
  .btn {
    display:inline-flex; align-items:center; gap:8px;
    padding: 10px 14px; border-radius: 10px;
    border: 1px solid rgba(255,255,255,.16);
    background: rgba(255,255,255,.06);
    color: #e8f2f2;
    cursor: pointer;
    font-weight: 700;
    text-decoration: none;
  }
  .btn:hover { filter: brightness(1.06); }
  .btn.secondary { opacity: .9; }

  .error { background: rgba(255, 80, 80, .16); border: 1px solid rgba(255, 80, 80, .28);
           padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
  .ok { background: rgba(0, 255, 160, .12); border: 1px solid rgba(0, 255, 160, .22);
        padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }

  .meta { display:flex; gap: 12px; flex-wrap: wrap; font-size: .92rem; }
  .chip { padding: 6px 10px; border-radius: 999px; border: 1px solid rgba(255,255,255,.14);
          background: rgba(255,255,255,.04); }

  .out { min-height: 200px; }
  .small { font-size: .9rem; }
</style>

<script>
async function copyOut() {
  const el = document.getElementById('b64_out');
  if (!el) return;
  const txt = el.value || '';
  try {
    await navigator.clipboard.writeText(txt);
  } catch(e) {
    el.select();
    document.execCommand('copy');
  }
}
function clearInput() {
  const t = document.getElementById('input_text');
  if (t) t.value = '';
}
</script>

<div class="wrap">
  <div class="card">
    <h1>CSR2Base64</h1>
    <p class="muted">Upload een CSR/CRT/PEM (of plak tekst) en krijg Base64 in 1 lijn, klaar om te copy/pasten.</p>
  </div>

  {% if err %}<div class="error"><strong>Fout:</strong> {{ err }}</div>{% endif %}
  {% if ok %}<div class="ok"><strong>{{ ok }}</strong></div>{% endif %}

  <div class="row">
    <div class="col">
      <div class="card">
        <h2>Input</h2>
        <form method="post" action="/csr2base64" enctype="multipart/form-data">
          <div class="small muted">1) Kies bestand (CSR/CRT/PEM/DER/...) of 2) plak tekst hieronder.</div>
          <div style="margin-top:10px;">
            <input type="file" name="file" accept=".csr,.crt,.cer,.pem,.der,.txt,.b64,.key,*/*">
          </div>
          <div style="margin-top:10px;">
            <label class="small muted">Plak hier (optioneel)</label>
            <textarea id="input_text" name="input_text" placeholder="-----BEGIN CERTIFICATE REQUEST-----\n...\n-----END CERTIFICATE REQUEST-----">{{ input_text or '' }}</textarea>
          </div>
          <div class="btns">
            <button class="btn" type="submit">Encode → Base64</button>
            <button class="btn secondary" type="button" onclick="clearInput()">Clear</button>
          </div>
        </form>
      </div>
    </div>

    <div class="col">
      <div class="card">
        <h2>Output (single line)</h2>

        {% if result %}
          <div class="meta" style="margin-bottom:10px;">
            <span class="chip">Source: <code>{{ result.source }}</code></span>
            <span class="chip">Bytes: <code>{{ result.byte_len }}</code></span>
            <span class="chip">Base64 chars: <code>{{ result.b64_len }}</code></span>
          </div>
        {% endif %}

        <textarea id="b64_out" class="out" readonly placeholder="Hier verschijnt de Base64 output...">{% if result %}{{ result.b64 }}{% endif %}</textarea>

        <div class="btns">
          <button class="btn" type="button" onclick="copyOut()">Copy</button>
          <a class="btn secondary" href="/csr2base64/download">Download .b64</a>
        </div>

        <p class="muted small" style="margin-top:10px;">
          Tip: dit is <strong>Base64 van de ruwe bytes</strong>. Voor PEM wordt dus ook de header/footer mee-gebase64’d.
          Als je ooit “enkel de PEM-body” wil (header/footer weg), zeg het maar.
        </p>
      </div>
    </div>
  </div>
</div>
"""


def _render(err: Optional[str] = None, ok: Optional[str] = None, input_text: str = "", result: Optional[Dict[str, Any]] = None):
    content_html = render_template_string(
        CONTENT_TEMPLATE,
        err=err,
        ok=ok,
        input_text=input_text,
        result=result,
    )
    # IMPORTANT: render_page is keyword-only in jouw hub
    return hub_render_page(title="CSR2Base64", content_html=content_html)


def register_web_routes(app: Flask) -> None:
    @app.get("/csr2base64")
    @app.post("/csr2base64")
    def csr2base64_page():
        global LAST_RESULT

        if request.method == "GET":
            return _render(None, None, input_text="", result=LAST_RESULT)

        # POST
        input_text = (request.form.get("input_text") or "").strip()

        raw: Optional[bytes] = None
        source = ""

        # 1) file upload heeft voorrang
        up = request.files.get("file")
        if up and up.filename:
            try:
                raw = up.read() or b""
                source = f"file: {up.filename}"
            except Exception as exc:
                return _render(err=f"Kon bestand niet lezen: {exc}", input_text=input_text)

        # 2) anders textarea
        if (raw is None) and input_text:
            normalized = input_text.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
            raw = normalized.encode("utf-8", errors="replace")
            source = "textarea"

        if raw is None:
            return _render(err="Geen input. Kies een bestand of plak tekst.", input_text=input_text)

        if len(raw) == 0:
            return _render(err="Input is leeg.", input_text=input_text)

        b64 = _b64_single_line(raw)
        LAST_RESULT = {
            "source": source,
            "byte_len": len(raw),
            "b64_len": len(b64),
            "b64": b64,
        }

        return _render(ok="OK: Base64 gegenereerd.", input_text=input_text, result=LAST_RESULT)

    @app.get("/csr2base64/download")
    def csr2base64_download():
        if not LAST_RESULT:
            return make_response("Nog niets om te downloaden. Doe eerst een encode.", 400)

        b64 = (LAST_RESULT.get("b64") or "").strip() + "\n"
        data = b64.encode("utf-8")

        suggested = "csr2base64_output.b64"
        src = str(LAST_RESULT.get("source") or "")
        if src.startswith("file:"):
            fn = src.replace("file:", "", 1).strip()
            suggested = f"{_safe_stem(fn)}.b64"

        bio = BytesIO(data)
        bio.seek(0)
        return send_file(
            bio,
            as_attachment=True,
            download_name=suggested,
            mimetype="text/plain",
        )


# -------------------------
# Standalone entrypoint
# -------------------------
if __name__ == "__main__":
    app = Flask("csr2base64")
    register_web_routes(app)

    # Standalone-only: root redirect + favicon to avoid noisy 404s
    @app.get("/")
    def _root():
        return redirect("/csr2base64", code=302)

    @app.get("/favicon.ico")
    def _favicon():
        return ("", 204)

    app.run("127.0.0.1", 5003, debug=True)
