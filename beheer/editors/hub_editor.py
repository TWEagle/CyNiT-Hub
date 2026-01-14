from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from flask import request

from beheer.main_layout import render_page

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = BASE_DIR / "config"
HUB_SETTINGS_JSON = CONFIG_DIR / "hub_settings.json"


# -------------------------
# helpers
# -------------------------
def _html(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _bool_from_form(name: str) -> bool:
    return request.form.get(name) is not None


def _clamp_int(val: str, default: int, lo: int, hi: int) -> int:
    try:
        n = int(val)
    except Exception:
        return default
    return max(lo, min(hi, n))


def _clean_text(s: str, default: str = "") -> str:
    s = (s or "").strip()
    return s if s else default


def _normalize_sections_order(order: Any) -> List[str]:
    allowed = ["layout", "app", "branding"]
    if not isinstance(order, list):
        order = []
    order = [str(x).strip() for x in order if str(x).strip() in allowed]
    # ensure all exist
    for x in allowed:
        if x not in order:
            order.append(x)
    return order[:3]


def _load_hub_settings() -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "flask_app_name": "CyNiT-Hub",
        "brand_tools": "CyNiT Tools",
        "brand_beheer": "CyNiT Beheer",
        "logo_src": "/images/logo.png?v=1",
        "favicon_ico": "/images/logo.ico",

        "home_columns": 2,
        "card_bg": True,
        "card_round": True,
        "button_bg": True,
        "button_rounded": True,

        # bonus
        "show_section_order": False,
        "sections_order": ["app", "branding", "layout"],  # default feel: app -> branding -> layout
    }

    if not HUB_SETTINGS_JSON.exists():
        defaults["sections_order"] = _normalize_sections_order(defaults.get("sections_order"))
        return dict(defaults)

    raw = HUB_SETTINGS_JSON.read_text(encoding="utf-8").strip()
    if not raw:
        defaults["sections_order"] = _normalize_sections_order(defaults.get("sections_order"))
        return dict(defaults)

    try:
        data = json.loads(raw)

        # legacy: [ { ... } ]
        if isinstance(data, list):
            if data and isinstance(data[0], dict):
                defaults.update(data[0])

        elif isinstance(data, dict):
            defaults.update(data)

    except Exception:
        pass

    # normalize types
    defaults["home_columns"] = int(defaults.get("home_columns", 2) or 2)
    defaults["card_bg"] = bool(defaults.get("card_bg", True))
    defaults["card_round"] = bool(defaults.get("card_round", True))
    defaults["button_bg"] = bool(defaults.get("button_bg", True))
    defaults["button_rounded"] = bool(defaults.get("button_rounded", True))
    defaults["show_section_order"] = bool(defaults.get("show_section_order", False))
    defaults["sections_order"] = _normalize_sections_order(defaults.get("sections_order"))

    return dict(defaults)


def _save_hub_settings(data: Dict[str, Any]) -> None:
    HUB_SETTINGS_JSON.parent.mkdir(parents=True, exist_ok=True)
    HUB_SETTINGS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _section_title(key: str) -> str:
    if key == "layout":
        return "Layout"
    if key == "app":
        return "App (forced)"
    if key == "branding":
        return "Branding"
    return key


# -------------------------
# main handler
# -------------------------
def handle_hub_editor() -> str:
    hub = _load_hub_settings()

    if request.method == "POST":
        # update basic fields
        hub["flask_app_name"] = _clean_text(request.form.get("flask_app_name"), hub.get("flask_app_name", "CyNiT-Hub"))
        hub["brand_tools"] = _clean_text(request.form.get("brand_tools"), hub.get("brand_tools", "CyNiT Tools"))
        hub["brand_beheer"] = _clean_text(request.form.get("brand_beheer"), hub.get("brand_beheer", "CyNiT Beheer"))
        hub["logo_src"] = _clean_text(request.form.get("logo_src"), hub.get("logo_src", "/images/logo.png?v=1"))
        hub["favicon_ico"] = _clean_text(request.form.get("favicon_ico"), hub.get("favicon_ico", "/images/logo.ico"))

        hub["home_columns"] = _clamp_int(request.form.get("home_columns", str(hub.get("home_columns", 2))), default=2, lo=1, hi=12)

        hub["card_bg"] = _bool_from_form("card_bg")
        hub["card_round"] = _bool_from_form("card_round")
        hub["button_bg"] = _bool_from_form("button_bg")
        hub["button_rounded"] = _bool_from_form("button_rounded")

        # bonus toggle
        hub["show_section_order"] = _bool_from_form("show_section_order")

        # section order from hidden input (CSV)
        order_csv = (request.form.get("sections_order_csv") or "").strip()
        if order_csv:
            order = [x.strip() for x in order_csv.split(",") if x.strip()]
            hub["sections_order"] = _normalize_sections_order(order)
        else:
            hub["sections_order"] = _normalize_sections_order(hub.get("sections_order"))

        _save_hub_settings(hub)
        # reload (zekerheid)
        hub = _load_hub_settings()

    # -------------------------
    # render sections in chosen order
    # -------------------------
    sections_order: List[str] = _normalize_sections_order(hub.get("sections_order"))

    # ===== editor-only CSS =====
    editor_css = """
<style>
.hub-grid{ display:grid; gap: 14px; }

.section{
  background: rgba(10,15,18,.55);
  border: 1px solid rgba(255,255,255,.10);
  border-radius: 18px;
  padding: 14px;
}

.section .pill{ margin-bottom: 10px; display:inline-flex; }

.field{ display:grid; gap: 6px; margin-top: 12px; }
.field label{ color: rgba(255,255,255,.65); font-size: 14px; }
.field .hint{ color: rgba(255,255,255,.55); font-size: 12px; }

.inp{
  width: 100%;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,.22);
  background: rgba(0,0,0,.55);
  color: #e8f2f2;
  outline: none;
}
.inp:focus{
  border-color: rgba(53,230,223,.55);
  box-shadow: 0 0 0 2px rgba(53,230,223,.12);
}

.row{
  display:flex; gap: 10px; flex-wrap: wrap; align-items:center; margin-top: 10px;
}

.chk{
  display:inline-flex; gap:10px; align-items:center;
  padding: 10px 12px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,.14);
  background: rgba(255,255,255,.03);
}

.btnbar{
  display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top: 14px;
}

.btn-primary{
  border: 1px solid rgba(255,255,255,.18);
  background: rgba(255,255,255,.06);
}

/* ===== bonus: reorder UI ===== */
.reorder-wrap{
  margin-top: 14px;
  border-top: 1px solid rgba(255,255,255,.08);
  padding-top: 14px;
}
.reorder-grid{
  display:grid;
  gap: 10px;
  max-width: 520px;
}
.reorder-item{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,.12);
  background: rgba(255,255,255,.03);
}
.reorder-handle{
  display:inline-flex;
  align-items:center;
  gap: 10px;
  cursor: grab;
  user-select:none;
}
.reorder-handle:active{ cursor: grabbing; }
.reorder-meta{ color: rgba(255,255,255,.55); font-size: 12px; }
.reorder-item.dragging{ opacity: .60; }
.reorder-item.drop-target{ outline: 2px dashed rgba(53,230,223,.45); outline-offset: 4px; }
</style>
"""

    # ===== bonus JS (drag&drop reorder of sections) =====
    editor_js = """
<script>
(function(){
  function qs(sel){ return document.querySelector(sel); }
  function qsa(sel){ return Array.from(document.querySelectorAll(sel)); }

  const list = qs("#sections_list");
  const out = qs('input[name="sections_order_csv"]');

  function sync(){
    if(!list || !out) return;
    const keys = qsa("#sections_list .reorder-item").map(x=>x.getAttribute("data-key")).filter(Boolean);
    out.value = keys.join(",");
  }

  let dragEl = null;

  function onDragStart(e){
    const it = e.currentTarget.closest(".reorder-item");
    if(!it) return;
    dragEl = it;
    it.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", it.getAttribute("data-key") || "");
  }

  function onDragOver(e){
    e.preventDefault();
    const over = e.currentTarget.closest(".reorder-item");
    if(!over || !dragEl || over===dragEl) return;
    over.classList.add("drop-target");
    e.dataTransfer.dropEffect = "move";
  }

  function onDragLeave(e){
    const over = e.currentTarget.closest(".reorder-item");
    if(over) over.classList.remove("drop-target");
  }

  function onDrop(e){
    e.preventDefault();
    const target = e.currentTarget.closest(".reorder-item");
    if(!target || !dragEl || target===dragEl) return;

    target.classList.remove("drop-target");

    const rect = target.getBoundingClientRect();
    const before = (e.clientY - rect.top) < (rect.height / 2);

    if(before){
      target.parentNode.insertBefore(dragEl, target);
    }else{
      target.parentNode.insertBefore(dragEl, target.nextSibling);
    }
    sync();
  }

  function onDragEnd(){
    if(dragEl) dragEl.classList.remove("dragging");
    qsa(".reorder-item.drop-target").forEach(x=>x.classList.remove("drop-target"));
    dragEl = null;
    sync();
  }

  qsa(".reorder-handle").forEach(h=>{
    h.setAttribute("draggable","true");
    h.addEventListener("dragstart", onDragStart);
    h.addEventListener("dragend", onDragEnd);
  });

  qsa("#sections_list .reorder-item").forEach(it=>{
    it.addEventListener("dragover", onDragOver);
    it.addEventListener("dragleave", onDragLeave);
    it.addEventListener("drop", onDrop);
  });

  // initial sync
  sync();

  // also sync before submit
  const form = qs("#hub_form");
  if(form){
    form.addEventListener("submit", ()=>sync());
  }
})();
</script>
"""

    # -------------------------
    # Build section HTML blocks
    # -------------------------
    section_app = f"""
<div class="section" data-section="app">
  <div class="pill">App (forced)</div>

  <div class="field">
    <label>Flask app name (forced)</label>
    <input class="inp" name="flask_app_name" value="{_html(str(hub.get("flask_app_name","")))}" placeholder="CyNiT-Hub">
    <div class="hint">Wordt bij startup hard gezet op <code>app.config["FLASK_APP_NAME"]</code>.</div>
  </div>
</div>
"""

    section_branding = f"""
<div class="section" data-section="branding">
  <div class="pill">Branding</div>

  <div class="field">
    <label>Brand (Tools)</label>
    <input class="inp" name="brand_tools" value="{_html(str(hub.get("brand_tools","")))}">
  </div>

  <div class="field">
    <label>Brand (Beheer)</label>
    <input class="inp" name="brand_beheer" value="{_html(str(hub.get("brand_beheer","")))}">
  </div>

  <div class="field">
    <label>Logo src</label>
    <input class="inp" name="logo_src" value="{_html(str(hub.get("logo_src","")))}">
  </div>

  <div class="field">
    <label>Favicon ico</label>
    <input class="inp" name="favicon_ico" value="{_html(str(hub.get("favicon_ico","")))}">
  </div>
</div>
"""

    section_layout = f"""
<div class="section" data-section="layout">
  <div class="pill">Layout</div>

  <div class="row">
    <label class="chk" style="gap:10px;">
      Home kolommen
      <input class="inp" style="width:110px;" type="number" min="1" max="12" name="home_columns" value="{int(hub.get("home_columns",2) or 2)}">
    </label>

    <label class="chk">
      <input type="checkbox" name="card_bg" {"checked" if hub.get("card_bg",True) else ""}>
      Card background
    </label>

    <label class="chk">
      <input type="checkbox" name="card_round" {"checked" if hub.get("card_round",True) else ""}>
      Rounded corners
    </label>

    <label class="chk">
      <input type="checkbox" name="button_bg" {"checked" if hub.get("button_bg",True) else ""}>
      Button background
    </label>

    <label class="chk">
      <input type="checkbox" name="button_rounded" {"checked" if hub.get("button_rounded",True) else ""}>
      Button rounded
    </label>
  </div>

  <div class="btnbar">
    <label class="chk">
      <input type="checkbox" name="show_section_order" {"checked" if hub.get("show_section_order",False) else ""}>
      Volgorde secties tonen (onderaan)
    </label>

    <button class="btn btn-primary" type="submit">💾 Opslaan</button>
  </div>
</div>
"""

    sections_map = {
        "app": section_app,
        "branding": section_branding,
        "layout": section_layout,
    }

    ordered_sections_html = "\n".join(sections_map[k] for k in sections_order)

    # -------------------------
    # Bonus: reorder block (shown only when checkbox enabled)
    # -------------------------
    show_order = bool(hub.get("show_section_order", False))

    reorder_block = ""
    if show_order:
        items_html = []
        for key in sections_order:
            items_html.append(f"""
<div class="reorder-item" data-key="{_html(key)}">
  <div class="reorder-handle" title="Sleep om te herschikken">
    ⠿ <b>{_html(_section_title(key))}</b>
    <span class="reorder-meta">({ _html(key) })</span>
  </div>
  <div class="reorder-meta">drag &amp; drop</div>
</div>
""")

        reorder_block = f"""
<div class="section reorder-wrap">
  <div class="pill">Volgorde secties</div>
  <div class="hint" style="margin-bottom:10px;">
    Sleep de secties in de gewenste volgorde. Opslaan schrijft dit weg als <code>sections_order</code> in <code>config/hub_settings.json</code>.
  </div>

  <input type="hidden" name="sections_order_csv" value="">

  <div id="sections_list" class="reorder-grid">
    {''.join(items_html)}
  </div>
</div>
"""

    content = f"""
{editor_css}

<div class="panel">
  <h2 style="margin:0 0 10px 0;">Hub editor</h2>
  <div class="hint">Wijzigt <code>config/hub_settings.json</code> (globale hub instellingen).</div>

  <form id="hub_form" method="post" class="hub-grid" style="margin-top:14px;">
    {ordered_sections_html}
    {reorder_block}
  </form>
</div>

{editor_js}
"""

    return render_page(title="Hub", content_html=content)
