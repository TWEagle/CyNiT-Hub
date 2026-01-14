from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from flask import request
from beheer.main_layout import render_page

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = BASE_DIR / "config"
TOOLS_JSON = CONFIG_DIR / "tools.json"


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


def _attr_json(s: str) -> str:
    return _html(s).replace("'", "&#39;")


def _safe_json(s: str, fallback: Any) -> Any:
    try:
        return json.loads(s)
    except Exception:
        return fallback


def _clamp_int(val: str, default: int, lo: int, hi: int) -> int:
    try:
        n = int(val)
    except Exception:
        return default
    return max(lo, min(hi, n))


def _hex_to_rgb(accent: str) -> str:
    s = (accent or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return "53,230,223"
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
        return f"{r},{g},{b}"
    except Exception:
        return "53,230,223"


def _load_tools_file() -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    tools.json supports:
      - list of tools
      - dict: {"tools":[...], ...}
    We keep ONLY tools here; hub/theme settings are split out.
    """
    if not TOOLS_JSON.exists():
        return ({"tools": []}, [])

    raw = TOOLS_JSON.read_text(encoding="utf-8").strip()
    if not raw:
        return ({"tools": []}, [])

    data = json.loads(raw)

    if isinstance(data, list):
        tools = [t for t in data if isinstance(t, dict)]
        return ({"tools": tools}, tools)

    if isinstance(data, dict):
        tools = data.get("tools", [])
        if not isinstance(tools, list):
            tools = []
        tools = [t for t in tools if isinstance(t, dict)]
        root = dict(data)
        root["tools"] = tools
        # ensure we don't keep old ui block in memory
        root.pop("ui", None)
        return (root, tools)

    return ({"tools": []}, [])


def _save_tools_file(root: Dict[str, Any], tools: List[Dict[str, Any]]) -> None:
    """
    Always save dict form:
      { "tools": [...] }
    and explicitly drop any old "ui" key (split out).
    """
    root = dict(root)
    root["tools"] = tools
    root.pop("ui", None)

    TOOLS_JSON.parent.mkdir(parents=True, exist_ok=True)
    TOOLS_JSON.write_text(json.dumps(root, indent=2, ensure_ascii=False), encoding="utf-8")


# -------------------------
# main handler
# -------------------------
def handle_tools_editor() -> str:
    root, tools = _load_tools_file()

    if request.method == "POST":
        # Order comes from drag&drop (CSV of ids)
        order_csv = (request.form.get("order_ids") or "").strip()
        ordered_ids = [x.strip() for x in order_csv.split(",") if x.strip()]

        row_count = _clamp_int(request.form.get("row_count", "0"), default=0, lo=0, hi=500)

        # Collect updates by id (or fallback key)
        new_tools_by_key: Dict[str, Dict[str, Any]] = {}

        for i in range(row_count):
            base = _safe_json(request.form.get(f"orig_{i}", "{}"), {})
            if not isinstance(base, dict):
                base = {}

            if request.form.get(f"deleted_{i}", "0") == "1":
                continue

            tid = str(base.get("id") or "").strip()
            key = tid if tid else f"__noid_{i}"

            enabled = request.form.get(f"enabled_{i}") is not None
            hidden = request.form.get(f"hidden_{i}") is not None

            name = (request.form.get(f"name_{i}") or "").strip()
            icon = (request.form.get(f"icon_{i}") or "").strip()
            accent = (request.form.get(f"accent_{i}") or "").strip()

            accent_mode = (request.form.get(f"accent_mode_{i}") or "left").strip().lower()
            if accent_mode not in ("left", "ring", "bg"):
                accent_mode = "left"

            accent_width = _clamp_int(
                request.form.get(f"accent_width_{i}", str(base.get("accent_width", 5))),
                default=5, lo=0, hi=80
            )
            ring_width = _clamp_int(
                request.form.get(f"ring_width_{i}", str(base.get("ring_width", 1))),
                default=1, lo=0, hi=40
            )
            ring_glow = _clamp_int(
                request.form.get(f"ring_glow_{i}", str(base.get("ring_glow", 18))),
                default=18, lo=0, hi=160
            )

            # Normalize minimal fields
            if not name:
                name = (base.get("name") or base.get("id") or f"Tool {i+1}").strip()
            if not icon:
                icon = (base.get("icon_web") or base.get("icon") or "🧩").strip()
            if not accent:
                accent = (base.get("accent") or "#35e6df").strip()

            base["enabled"] = bool(enabled)
            base["hidden"] = bool(hidden)
            base["name"] = name
            base["icon"] = icon
            base["accent"] = accent

            base["accent_mode"] = accent_mode
            base["accent_width"] = int(accent_width)
            base["ring_width"] = int(ring_width)
            base["ring_glow"] = int(ring_glow)

            # Keep original id as-is (we don't invent ids)
            new_tools_by_key[key] = base

        # Apply drag-drop order if provided
        final_tools: List[Dict[str, Any]] = []
        used = set()

        # ordered_ids is list of real ids (so only those will reorder)
        for tid in ordered_ids:
            if tid in new_tools_by_key:
                final_tools.append(new_tools_by_key[tid])
                used.add(tid)

        # Append remaining tools (including no-id tools)
        for key, t in new_tools_by_key.items():
            if key not in used:
                final_tools.append(t)

        _save_tools_file(root, final_tools)
        root, tools = _load_tools_file()

    # -------------------------
    # render
    # -------------------------
    editor_css = """
<style>
.editor-grid{
  display:grid;
  grid-template-columns: repeat(auto-fit, minmax(460px, 1fr));
  gap: 14px;
  margin-top: 14px;
}
.e-card{
  border: 1px solid rgba(255,255,255,.10);
  padding: 14px;
  border-radius: 18px;
  background: rgba(10,15,18,.65);
  box-shadow: 0 12px 40px rgba(0,0,0,.35);
  position: relative;
}
.dragbar{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap: 10px;
  margin-bottom: 8px;
}
.draghandle{
  display:inline-flex;
  align-items:center;
  gap: 10px;
  border: 1px solid rgba(255,255,255,.12);
  background: rgba(255,255,255,.03);
  border-radius: 999px;
  padding: 8px 12px;
  cursor: grab;
  user-select:none;
}
.draghandle:active{ cursor: grabbing; }
.draghint{ color: rgba(255,255,255,.55); font-size: 12px; }

.e-head{ display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
.e-title{ font-weight:800; display:flex; gap:10px; align-items:center; }
.e-sub{ color: rgba(255,255,255,.55); font-size: 12px; margin-top: 4px; }
.e-row{ display:flex; gap:10px; margin-top: 10px; align-items:center; flex-wrap:wrap; }
.e-row .inp{ flex: 1; min-width: 160px; }

.badges{ display:flex; gap:10px; flex-wrap:wrap; margin: 10px 0 0 0; }
.badge{
  border: 1px solid rgba(255,255,255,.14);
  background: rgba(255,255,255,.03);
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
  color: rgba(255,255,255,.78);
}

.switch{ position: relative; display:inline-block; width: 46px; height: 26px; }
.switch input{ display:none; }
.slider{
  position:absolute; cursor:pointer; top:0; left:0; right:0; bottom:0;
  background: rgba(255,255,255,.15);
  border: 1px solid rgba(255,255,255,.18);
  transition: .2s;
  border-radius: 999px;
}
.slider:before{
  position:absolute; content:"";
  height: 20px; width: 20px;
  left: 3px; top: 2px;
  background: #fff;
  transition: .2s;
  border-radius: 999px;
}
.switch input:checked + .slider{
  background: rgba(53,230,223,.35);
  border-color: rgba(53,230,223,.35);
}
.switch input:checked + .slider:before{ transform: translateX(20px); }

.mini{
  padding: 6px 10px;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,.10);
  background: rgba(255,255,255,.03);
  color: #e8f2f2;
  cursor:pointer;
}
.mini:hover{ background: rgba(255,255,255,.06); }
.mini.danger{ border-color: rgba(255,80,80,.35); }

.inp, .inp[type="text"], .inp[type="number"], select.inp{
  background: rgba(0,0,0,.65) !important;
  color: #e8f2f2 !important;
  border: 1px solid rgba(255,255,255,.22) !important;
  border-radius: 12px !important;
  padding: 10px 12px !important;
  outline: none !important;
}
.inp:focus, select.inp:focus{
  border-color: rgba(53,230,223,.55) !important;
  box-shadow: 0 0 0 2px rgba(53,230,223,.12) !important;
}
select.inp option{
  background: #0b0f12 !important;
  color: #e8f2f2 !important;
}

.colorpick{
  width: 44px; height: 36px;
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 12px;
  background: transparent;
  padding: 0;
}
.accentbox{ display:flex; align-items:center; gap:10px; }

.previewwrap{
  margin-top: 12px;
  border-top: 1px solid rgba(255,255,255,.08);
  padding-top: 12px;
}
.previewlabel{ color: rgba(255,255,255,.60); font-size: 12px; margin-bottom: 8px; }
.previewrow{ display:flex; gap:12px; align-items: stretch; flex-wrap: wrap; }
.previewcard{ flex: 1; min-width: 260px; }
.previewcard .toolcard{ pointer-events:none; }

.e-card.dragging{ opacity: .60; }
.e-card.drop-target{ outline: 2px dashed rgba(53,230,223,.45); outline-offset: 6px; }
</style>
"""

    editor_js = """
<script>
(function(){
  function qs(sel){ return document.querySelector(sel); }
  function qsa(sel){ return Array.from(document.querySelectorAll(sel)); }

  // ===== live preview updates =====
  function hexToRgb(hex){
    hex = (hex||"").trim().replace("#","");
    if(hex.length===3){ hex = hex.split("").map(c=>c+c).join(""); }
    if(hex.length!==6) return "53,230,223";
    const r = parseInt(hex.slice(0,2),16);
    const g = parseInt(hex.slice(2,4),16);
    const b = parseInt(hex.slice(4,6),16);
    if([r,g,b].some(n=>Number.isNaN(n))) return "53,230,223";
    return r+","+g+","+b;
  }
  function modeClass(mode){
    mode = (mode||"left").toLowerCase();
    if(mode==="ring") return "accent-ring";
    if(mode==="bg") return "accent-bg";
    return "";
  }
  window.updatePreview = function(idx){
    const name = qs('input[name="name_'+idx+'"]')?.value || "Tool";
    const icon = qs('input[name="icon_'+idx+'"]')?.value || "🧩";
    const accent = qs('input[name="accent_'+idx+'"]')?.value || "#35e6df";
    const mode = qs('select[name="accent_mode_'+idx+'"]')?.value || "left";
    const aw = parseInt(qs('input[name="accent_width_'+idx+'"]')?.value || "5",10) || 0;
    const rw = parseInt(qs('input[name="ring_width_'+idx+'"]')?.value || "1",10) || 0;
    const rg = parseInt(qs('input[name="ring_glow_'+idx+'"]')?.value || "18",10) || 0;

    const pv = qs('#pv_'+idx);
    if(!pv) return;

    pv.classList.remove("accent-ring","accent-bg");
    const cls = modeClass(mode);
    if(cls) pv.classList.add(cls);

    pv.style.setProperty("--accent", accent);
    pv.style.setProperty("--accent-rgb", hexToRgb(accent));
    pv.style.setProperty("--accent-width", aw+"px");
    pv.style.setProperty("--ring-width", rw+"px");
    pv.style.setProperty("--ring-glow", rg+"px");

    const tt = pv.querySelector("[data-pv-title]");
    const ti = pv.querySelector("[data-pv-icon]");
    const td = pv.querySelector("[data-pv-desc]");
    if(tt) tt.textContent = name;
    if(ti) ti.textContent = icon;
    if(td) td.textContent = "Live preview ("+mode+")";
  };

  // Bind inputs to preview
  qsa('[data-idx]').forEach(el=>{
    const idx = el.getAttribute("data-idx");
    if(!idx) return;
    el.addEventListener("input", ()=>updatePreview(idx));
    el.addEventListener("change", ()=>updatePreview(idx));
  });

  // Color pickers -> sync text + preview
  qsa('input[type="color"][data-bind="accent"]').forEach(cp=>{
    cp.addEventListener("input", ()=>{
      const idx = cp.getAttribute("data-idx");
      const txt = qs('input[name="accent_'+idx+'"]');
      if (txt) txt.value = cp.value;
      updatePreview(idx);
    });
  });

  // Init previews
  qsa('[id^="pv_"]').forEach(pv=>{
    const idx = pv.id.replace("pv_","");
    updatePreview(idx);
  });

  // ===== delete button =====
  function syncOrderIds(){
    const grid = qs("#editor_grid");
    const orderInput = qs('input[name="order_ids"]');
    if(!grid || !orderInput) return;

    const ids = qsa('#editor_grid .e-card')
      .filter(c=>c.style.display!=="none")
      .map(c=>c.getAttribute("data-tool-id"))
      .filter(Boolean);

    orderInput.value = ids.join(",");
  }

  qsa('[data-action="delete"]').forEach(btn=>{
    btn.addEventListener("click", ()=>{
      const idx = btn.getAttribute("data-idx");
      const del = qs('input[name="deleted_'+idx+'"]');
      if (del) del.value = "1";
      const card = qs('[data-card-idx="'+idx+'"]');
      if (card) card.style.display = "none";
      syncOrderIds();
    });
  });

  // ===== drag & drop ordering =====
  let dragEl = null;

  function handleDragStart(e){
    const card = e.currentTarget.closest(".e-card");
    if(!card) return;
    dragEl = card;
    card.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", card.getAttribute("data-tool-id") || "");
  }

  function handleDragOver(e){
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const over = e.currentTarget.closest(".e-card");
    if(!over || !dragEl || over===dragEl) return;
    over.classList.add("drop-target");
  }

  function handleDragLeave(e){
    const over = e.currentTarget.closest(".e-card");
    if(over) over.classList.remove("drop-target");
  }

  function handleDrop(e){
    e.preventDefault();
    const target = e.currentTarget.closest(".e-card");
    if(!target || !dragEl || target===dragEl) return;

    target.classList.remove("drop-target");

    const rect = target.getBoundingClientRect();
    const before = (e.clientY - rect.top) < (rect.height / 2);

    if(before){
      target.parentNode.insertBefore(dragEl, target);
    }else{
      target.parentNode.insertBefore(dragEl, target.nextSibling);
    }
    syncOrderIds();
  }

  function handleDragEnd(){
    if(dragEl) dragEl.classList.remove("dragging");
    qsa(".e-card.drop-target").forEach(x=>x.classList.remove("drop-target"));
    dragEl = null;
    syncOrderIds();
  }

  qsa(".draghandle").forEach(h=>{
    h.setAttribute("draggable","true");
    h.addEventListener("dragstart", handleDragStart);
    h.addEventListener("dragend", handleDragEnd);
  });

  qsa("#editor_grid .e-card").forEach(c=>{
    c.addEventListener("dragover", handleDragOver);
    c.addEventListener("dragleave", handleDragLeave);
    c.addEventListener("drop", handleDrop);
  });

  // initial
  syncOrderIds();

  // before submit
  const form = qs("#tools_form");
  if(form){
    form.addEventListener("submit", ()=>syncOrderIds());
  }
})();
</script>
"""

    rows_cards: List[str] = []
    for i, t in enumerate(tools):
        enabled = bool(t.get("enabled", True))
        hidden = bool(t.get("hidden", False))

        tid = str(t.get("id") or "").strip()
        name = (t.get("name") or tid or "Tool").strip()
        icon = (t.get("icon_web") or t.get("icon") or "🧩").strip()
        accent = (t.get("accent") or "#35e6df").strip()

        accent_mode = (t.get("accent_mode") or "left").strip().lower()
        accent_width = int(t.get("accent_width") or 5)
        ring_width = int(t.get("ring_width") or 1)
        ring_glow = int(t.get("ring_glow") or 18)

        web_path = (t.get("web_path") or "").strip()
        script = (t.get("script") or "").strip()

        orig_json = json.dumps(t, ensure_ascii=False)
        hidden_fields = f"""
          <input type="hidden" name="orig_{i}" value='{_attr_json(orig_json)}'>
          <input type="hidden" name="deleted_{i}" value="0">
        """

        rgb = _hex_to_rgb(accent)

        mode_options = f"""
          <option value="left" {"selected" if accent_mode=="left" else ""}>left (stripe)</option>
          <option value="ring" {"selected" if accent_mode=="ring" else ""}>ring (ring + glow)</option>
          <option value="bg"   {"selected" if accent_mode=="bg" else ""}>bg (background + ring)</option>
        """

        mode_class = ""
        if accent_mode == "ring":
            mode_class = "accent-ring"
        elif accent_mode == "bg":
            mode_class = "accent-bg"

        rows_cards.append(f"""
<div class="e-card" data-card-idx="{i}" data-tool-id="{_html(tid)}">
  {hidden_fields}

  <div class="dragbar">
    <div class="draghandle" title="Sleep mij om de volgorde te veranderen">
      ⠿ <b>Drag</b>
      <span class="draghint">({_html(tid)})</span>
    </div>
    <div style="display:flex; gap:10px; align-items:center;">
      <button type="button" class="mini danger" data-action="delete" data-idx="{i}" title="Verwijderen">✖</button>
      <button class="btn btn-primary" type="submit">💾 Opslaan</button>
    </div>
  </div>

  <div class="e-head">
    <div>
      <div class="e-title">
        <span style="font-size:18px;">{_html(icon)}</span>
        <span>{_html(name)}</span>
      </div>
      <div class="e-sub">{_html(tid)} • {_html(web_path)} • {_html(script)}</div>

      <div class="badges">
        <div class="badge">Mode: {_html(accent_mode)}</div>
        <div class="badge">Stripe: {int(accent_width)}px</div>
        <div class="badge">Ring: {int(ring_width)}px</div>
        <div class="badge">Glow: {int(ring_glow)}px</div>
      </div>
    </div>

    <div style="display:flex; gap:12px; align-items:center;">
      <div style="display:flex; gap:10px; align-items:center;">
        <div class="e-sub" style="margin:0;">Hidden</div>
        <label class="switch" title="Hidden">
          <input type="checkbox" name="hidden_{i}" {"checked" if hidden else ""} data-idx="{i}">
          <span class="slider"></span>
        </label>
      </div>

      <div style="display:flex; gap:10px; align-items:center;">
        <div class="e-sub" style="margin:0;">Enabled</div>
        <label class="switch" title="Enabled">
          <input type="checkbox" name="enabled_{i}" {"checked" if enabled else ""} data-idx="{i}">
          <span class="slider"></span>
        </label>
      </div>
    </div>
  </div>

  <div class="e-row">
    <input class="inp" name="name_{i}" value="{_html(name)}" placeholder="Naam" data-idx="{i}">
    <input class="inp" name="icon_{i}" value="{_html(icon)}" placeholder="Icon (emoji)" data-idx="{i}">
  </div>

  <div class="e-row">
    <div class="accentbox" style="flex:1;">
      <input class="inp" name="accent_{i}" value="{_html(accent)}" placeholder="#00ff66" data-idx="{i}">
      <input type="color" class="colorpick" value="{_html(accent)}" data-bind="accent" data-idx="{i}">
    </div>

    <select class="inp" name="accent_mode_{i}" style="min-width: 260px;" data-idx="{i}">
      {mode_options}
    </select>
  </div>

  <div class="e-row">
    <label class="badge" style="display:flex; gap:10px; align-items:center;">
      Stripe px
      <input class="inp" style="width:110px;" type="number" min="0" max="80" name="accent_width_{i}" value="{int(accent_width)}" data-idx="{i}">
    </label>

    <label class="badge" style="display:flex; gap:10px; align-items:center;">
      Ring px
      <input class="inp" style="width:110px;" type="number" min="0" max="40" name="ring_width_{i}" value="{int(ring_width)}" data-idx="{i}">
    </label>

    <label class="badge" style="display:flex; gap:10px; align-items:center;">
      Glow px
      <input class="inp" style="width:110px;" type="number" min="0" max="160" name="ring_glow_{i}" value="{int(ring_glow)}" data-idx="{i}">
    </label>
  </div>

  <div class="previewwrap">
    <div class="previewlabel">Toolcard live preview</div>
    <div class="previewrow">
      <div class="previewcard">
        <a id="pv_{i}" class="toolcard {mode_class}" href="#"
           style="--accent:{_html(accent)}; --accent-rgb:{rgb};
                  --accent-width:{int(accent_width)}px; --ring-width:{int(ring_width)}px; --ring-glow:{int(ring_glow)}px;">
          <div class="toolcard-head">
            <div class="toolcard-icon" data-pv-icon>{_html(icon)}</div>
            <div data-pv-title>{_html(name)}</div>
          </div>
          <div class="toolcard-desc" data-pv-desc>Live preview</div>
        </a>
      </div>
    </div>
  </div>
</div>
""")

    content = f"""
{editor_css}
<form id="tools_form" method="post">
  <input type="hidden" name="row_count" value="{len(tools)}">
  <input type="hidden" name="order_ids" value="">

  <div class="panel">
    <h2 style="margin:0 0 10px 0;">Tools editor</h2>
    <div class="hint" style="margin-bottom:14px;">
      Drag &amp; drop om volgorde te wijzigen. Opslaan schrijft de tools array in <code>config/tools.json</code> in die volgorde weg.
    </div>
  </div>

  <div id="editor_grid" class="editor-grid">
    {''.join(rows_cards) if rows_cards else "<div class='panel'>Geen tools</div>"}
  </div>
</form>
{editor_js}
"""
    return render_page(title="Tools Editor", content_html=content)
