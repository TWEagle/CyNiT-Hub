from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from flask import request

from beheer.main_layout import render_page

BASE_DIR = Path(__file__).resolve().parents[2]  # .../CyNiT-Hub
CONFIG_DIR = BASE_DIR / "config"
THEME_JSON = CONFIG_DIR / "theme.json"


def _html(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _load_theme() -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "bg": "#000000",
        "text": "#e8f2f2",
        "muted": "#9fb3b3",
        "border": "rgba(255,255,255,.10)",
        "shadow": "0 12px 40px rgba(0,0,0,.55)",
        "accent": "#35e6df",
    }

    if not THEME_JSON.exists():
        return defaults

    raw = THEME_JSON.read_text(encoding="utf-8").strip()
    if not raw:
        return defaults

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            defaults.update({k: data[k] for k in defaults.keys() if k in data})
    except Exception:
        pass

    return defaults


def _save_theme(theme: Dict[str, Any]) -> None:
    THEME_JSON.parent.mkdir(parents=True, exist_ok=True)
    THEME_JSON.write_text(json.dumps(theme, indent=2, ensure_ascii=False), encoding="utf-8")


def handle_theme_editor() -> str:
    theme = _load_theme()
    defaults = _load_theme()  # same call gives defaults merged; we'll recreate explicit defaults
    defaults = {
        "bg": "#000000",
        "text": "#e8f2f2",
        "muted": "#9fb3b3",
        "border": "rgba(255,255,255,.10)",
        "shadow": "0 12px 40px rgba(0,0,0,.55)",
        "accent": "#35e6df",
    }

    if request.method == "POST":
        if request.form.get("action") == "reset":
            theme = dict(defaults)
            _save_theme(theme)
        else:
            # Save
            theme["bg"] = (request.form.get("bg") or defaults["bg"]).strip() or defaults["bg"]
            theme["text"] = (request.form.get("text") or defaults["text"]).strip() or defaults["text"]
            theme["muted"] = (request.form.get("muted") or defaults["muted"]).strip() or defaults["muted"]
            theme["accent"] = (request.form.get("accent") or defaults["accent"]).strip() or defaults["accent"]
            theme["border"] = (request.form.get("border") or defaults["border"]).strip() or defaults["border"]
            theme["shadow"] = (request.form.get("shadow") or defaults["shadow"]).strip() or defaults["shadow"]
            _save_theme(theme)

        # Reload from disk (zekerheid)
        theme = _load_theme()

    editor_css = """
<style>
.theme-grid{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-top: 14px;
}
@media (max-width: 980px){
  .theme-grid{ grid-template-columns: 1fr; }
}
.field{
  display:flex;
  flex-direction:column;
  gap:8px;
}
.row{
  display:flex;
  gap:10px;
  flex-wrap:wrap;
  align-items:center;
}
.inp, select.inp{
  background: rgba(0,0,0,.65) !important;
  color: #e8f2f2 !important;
  border: 1px solid rgba(255,255,255,.22) !important;
  border-radius: 12px !important;
  padding: 10px 12px !important;
  outline:none !important;
  min-width: 260px;
  flex: 1;
}
.inp:focus{
  border-color: rgba(53,230,223,.55) !important;
  box-shadow: 0 0 0 2px rgba(53,230,223,.12) !important;
}
.colorpick{
  width: 46px; height: 38px;
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 12px;
  background: transparent;
  padding: 0;
}
.smallhelp{ color: rgba(255,255,255,.55); font-size: 12px; }

.preview-surface{
  border: 1px solid rgba(255,255,255,.10);
  border-radius: 18px;
  padding: 16px;
  background:
    radial-gradient(1200px 700px at 50% 0%, #08121a 0%, #000 60%);
}
.preview-surface .panel{
  margin-bottom: 14px;
}
.preview-surface .toolcard{
  pointer-events:none;
}
</style>
"""

    # Live preview vars (apply to a wrapper)
    pv_style = f"""
--bg:{theme.get('bg')};
--text:{theme.get('text')};
--muted:{theme.get('muted')};
--border:{theme.get('border')};
--shadow:{theme.get('shadow')};
--accent:{theme.get('accent')};
"""

    content = f"""
{editor_css}
<div class="panel">
  <h2 style="margin:0 0 10px 0;">Theme editor</h2>
  <div class="hint" style="margin-bottom:14px;">
    Bewaart naar <code>config/theme.json</code>. Wordt automatisch geladen via <code>/static/theme.css</code>.
  </div>

  <form method="post" style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
    <button class="btn btn-primary" type="submit" name="action" value="save">💾 Opslaan</button>
    <button class="btn" type="submit" name="action" value="reset" title="Reset naar defaults">↩ Reset</button>
    <span class="pill">Tip: refresh is niet nodig; reload pagina is genoeg.</span>
  </form>
</div>

<div class="theme-grid">
  <div class="panel">
    <h3 style="margin-top:0;">Kleuren</h3>

    <div class="field">
      <label class="smallhelp">Background (--bg)</label>
      <div class="row">
        <input class="inp" name="bg" value="{_html(str(theme.get("bg","")))}">
        <input type="color" class="colorpick" value="{_html(str(theme.get("bg","#000000")))}"
               oninput="document.querySelector('input[name=bg]').value=this.value; document.getElementById('pvwrap').style.setProperty('--bg', this.value);">
      </div>
    </div>

    <div class="field" style="margin-top:12px;">
      <label class="smallhelp">Text (--text)</label>
      <div class="row">
        <input class="inp" name="text" value="{_html(str(theme.get("text","")))}">
        <input type="color" class="colorpick" value="{_html(str(theme.get("text","#e8f2f2")))}"
               oninput="document.querySelector('input[name=text]').value=this.value; document.getElementById('pvwrap').style.setProperty('--text', this.value);">
      </div>
    </div>

    <div class="field" style="margin-top:12px;">
      <label class="smallhelp">Muted (--muted)</label>
      <div class="row">
        <input class="inp" name="muted" value="{_html(str(theme.get("muted","")))}">
        <input type="color" class="colorpick" value="{_html(str(theme.get("muted","#9fb3b3")))}"
               oninput="document.querySelector('input[name=muted]').value=this.value; document.getElementById('pvwrap').style.setProperty('--muted', this.value);">
      </div>
    </div>

    <div class="field" style="margin-top:12px;">
      <label class="smallhelp">Accent (--accent)</label>
      <div class="row">
        <input class="inp" name="accent" value="{_html(str(theme.get("accent","")))}">
        <input type="color" class="colorpick" value="{_html(str(theme.get("accent","#35e6df")))}"
               oninput="document.querySelector('input[name=accent]').value=this.value; document.getElementById('pvwrap').style.setProperty('--accent', this.value);">
      </div>
    </div>
  </div>

  <div class="panel">
    <h3 style="margin-top:0;">Borders & shadow</h3>

    <div class="field">
      <label class="smallhelp">Border (--border) (CSS value)</label>
      <input class="inp" name="border" value="{_html(str(theme.get("border","")))}"
             oninput="document.getElementById('pvwrap').style.setProperty('--border', this.value);">
      <div class="smallhelp">Voorbeeld: <code>rgba(255,255,255,.10)</code></div>
    </div>

    <div class="field" style="margin-top:12px;">
      <label class="smallhelp">Shadow (--shadow) (CSS value)</label>
      <input class="inp" name="shadow" value="{_html(str(theme.get("shadow","")))}"
             oninput="document.getElementById('pvwrap').style.setProperty('--shadow', this.value);">
      <div class="smallhelp">Voorbeeld: <code>0 12px 40px rgba(0,0,0,.55)</code></div>
    </div>
  </div>
</div>

<div class="panel" style="margin-top:14px;">
  <h3 style="margin:0 0 10px 0;">Live preview</h3>
  <div id="pvwrap" class="preview-surface" style="{_html(pv_style)}">
    <div class="panel" style="background: rgba(10,15,18,.75); border:1px solid var(--border); box-shadow: var(--shadow);">
      <div class="toolcard-head" style="margin-bottom:8px;">
        <div class="toolcard-icon">🎨</div>
        <div>Preview panel</div>
      </div>
      <div class="toolcard-desc">Dit gebruikt je echte <code>main.css</code> + theme vars.</div>
    </div>

    <div class="cards">
      <a class="toolcard accent-bg"
         href="#"
         style="--accent: var(--accent); --accent-rgb: 53,230,223; --accent-width: 6px; --ring-width: 2px; --ring-glow: 20px;">
        <div class="toolcard-head">
          <div class="toolcard-icon">🧩</div>
          <div>Toolcard preview</div>
        </div>
        <div class="toolcard-desc">Accent/bg/ring reageren op theme.</div>
      </a>

      <div style="display:flex; gap:10px; flex-wrap:wrap;">
        <a class="btn" href="#">Button</a>
        <a class="btn" href="#">Button 2</a>
        <input class="in" value="Input preview">
      </div>
    </div>
  </div>
</div>
"""
    return render_page(title="Theme", content_html=content)
