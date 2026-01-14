from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from flask import request

from beheer.main_layout import render_page

# ==========================================================
# Paths
# ==========================================================
BASE_DIR = Path(__file__).resolve().parents[2]  # .../CyNiT-Hub
CONFIG_DIR = BASE_DIR / "config"
TOOLS_JSON = CONFIG_DIR / "tools.json"


# ==========================================================
# Helpers: load/save that preserves either LIST or {"tools": [...]}
# We also allow a top-level "ui" object for Hub display prefs.
# ==========================================================
def _load_tools_file() -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Returns (root_obj, tools_list).
    root_obj is always a dict in memory.
    tools_list is always a list of dicts.
    """
    if not TOOLS_JSON.exists():
        return ({"tools": [], "ui": {}}, [])

    raw = TOOLS_JSON.read_text(encoding="utf-8").strip()
    if not raw:
        return ({"tools": [], "ui": {}}, [])

    data = json.loads(raw)

    # Case A: file is a list of tools
    if isinstance(data, list):
        tools = [t for t in data if isinstance(t, dict)]
        root = {"tools": tools, "ui": {}}
        return (root, tools)

    # Case B: file is a dict
    if isinstance(data, dict):
        tools = data.get("tools", [])
        if not isinstance(tools, list):
            tools = []
        tools = [t for t in tools if isinstance(t, dict)]
        root = dict(data)
        root["tools"] = tools
        if "ui" not in root or not isinstance(root.get("ui"), dict):
            root["ui"] = {}
        return (root, tools)

    # Unknown format -> reset safely
    return ({"tools": [], "ui": {}}, [])


def _save_tools_file(root: Dict[str, Any], tools: List[Dict[str, Any]]) -> None:
    """
    Always save as dict-form:
      { "ui": {...}, "tools": [...] }
    """
    root = dict(root)
    root["tools"] = tools
    if "ui" not in root or not isinstance(root.get("ui"), dict):
        root["ui"] = {}

    TOOLS_JSON.parent.mkdir(parents=True, exist_ok=True)
    TOOLS_JSON.write_text(json.dumps(root, indent=2, ensure_ascii=False), encoding="utf-8")


def _bool_from_form(name: str) -> bool:
    return request.form.get(name) is not None


def _clamp_int(val: str, default: int, lo: int, hi: int) -> int:
    try:
        n = int(val)
    except Exception:
        return default
    return max(lo, min(hi, n))


def _safe_json(s: str, fallback: Any) -> Any:
    try:
        return json.loads(s)
    except Exception:
        return fallback


def _hex_to_rgb(accent: str) -> str:
    """
    '#00ff66' -> '0,255,102' (fallback: CyNiT accent)
    """
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


def _html(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _attr_json(s: str) -> str:
    """
    Safely embed JSON into a single-quoted HTML attribute value.
    """
    return _html(s).replace("'", "&#39;")


# ==========================================================
# Editor: GET/POST handler
# ==========================================================
def handle_tools_editor() -> str:
    root, tools = _load_tools_file()
    ui = root.get("ui", {})
    if not isinstance(ui, dict):
        ui = {}

    # ---------- POST: save ----------
    if request.method == "POST":
        # Global UI options
        home_cols = _clamp_int(request.form.get("home_columns", "2"), default=2, lo=1, hi=12)
        card_bg = _bool_from_form("card_bg")
        card_round = _bool_from_form("card_round")
        button_bg = _bool_from_form("button_bg")
        button_rounded = _bool_from_form("button_rounded")

        ui["home_columns"] = home_cols
        ui["card_bg"] = bool(card_bg)
        ui["card_round"] = bool(card_round)
        ui["button_bg"] = bool(button_bg)
        ui["button_rounded"] = bool(button_rounded)
        root["ui"] = ui

        row_count = _clamp_int(request.form.get("row_count", "0"), default=0, lo=0, hi=500)

        new_tools: List[Dict[str, Any]] = []
        for i in range(row_count):
            orig_raw = request.form.get(f"orig_{i}", "{}")
            base = _safe_json(orig_raw, {})
            if not isinstance(base, dict):
                base = {}

            deleted = request.form.get(f"deleted_{i}", "0") == "1"
            if deleted:
                continue

            enabled = request.form.get(f"enabled_{i}") is not None
            hidden = request.form.get(f"hidden_{i}") is not None

            name = (request.form.get(f"name_{i}") or "").strip()
            icon = (request.form.get(f"icon_{i}") or "").strip()
            accent = (request.form.get(f"accent_{i}") or "").strip()

            accent_mode = (request.form.get(f"accent_mode_{i}") or "").strip() or "left"
            stripe_px = _clamp_int(request.form.get(f"stripe_px_{i}", str(base.get("stripe_px", 6))), default=6, lo=0, hi=40)
            ring_px = _clamp_int(request.form.get(f"ring_px_{i}", str(base.get("ring_px", 2))), default=2, lo=0, hi=20)
            glow_px = _clamp_int(request.form.get(f"glow_px_{i}", str(base.get("glow_px", 22))), default=22, lo=0, hi=80)

            # Normalize minimal fields
            if not name:
                name = base.get("name") or base.get("id") or f"Tool {i+1}"
            if not icon:
                icon = base.get("icon_web") or base.get("icon") or "🧩"
            if not accent:
                accent = base.get("accent") or "#35e6df"

            base["enabled"] = bool(enabled)
            base["hidden"] = bool(hidden)
            base["name"] = name
            base["icon"] = icon
            base["accent"] = accent

            # Accent styling fields
            base["accent_mode"] = accent_mode  # "left" | "ring" | "bg"
            base["stripe_px"] = int(stripe_px)
            base["ring_px"] = int(ring_px)
            base["glow_px"] = int(glow_px)

            new_tools.append(base)

        _save_tools_file(root, new_tools)

        # reload view
        root, tools = _load_tools_file()
        ui = root.get("ui", {}) if isinstance(root.get("ui"), dict) else {}

    # ---------- render ----------
    home_cols = int(ui.get("home_columns") or 2)
    card_bg = bool(ui.get("card_bg", True))
    card_round = bool(ui.get("card_round", True))
    button_bg = bool(ui.get("button_bg", True))
    button_rounded = bool(ui.get("button_rounded", True))

    # Inline CSS: editor-only. (Fix: inputs/selects dark + readable)
    editor_css = """
<style>
/* --- view switch --- */
.viewbar{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:14px; }
.viewtab{ user-select:none; }
.viewtab input{ display:none; }
.viewtab span{
  display:inline-flex; align-items:center; gap:8px;
  padding: 10px 14px; border-radius: 999px;
  border: 1px solid rgba(255,255,255,.14);
  background: rgba(255,255,255,.03);
  cursor:pointer;
}
.viewtab input:checked + span{
  border-color: rgba(53,230,223,.55);
  box-shadow: 0 0 0 2px rgba(53,230,223,.10);
  background: rgba(255,255,255,.05);
}

/* --- editor grid/cards --- */
.editor-grid{
  display:grid;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 14px;
  margin-top: 14px;
}
.e-card{
  border: 1px solid rgba(255,255,255,.10);
  padding: 14px;
  box-shadow: 0 12px 40px rgba(0,0,0,.35);
}
.e-card.bg-on{ background: rgba(10,15,18,.65); }
.e-card.round-on{ border-radius: 18px; }

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

/* --- toggles --- */
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

/* --- FIX: editor inputs/selects dark --- */
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

/* --- table editor --- */
.tablewrap{ overflow:auto; border-radius: 16px; border: 1px solid rgba(255,255,255,.08); margin-top: 14px; }
.tooltable{ width: 100%; border-collapse: collapse; min-width: 1100px; }
.tooltable th, .tooltable td{
  border-bottom: 1px solid rgba(255,255,255,.06);
  padding: 10px;
  vertical-align: middle;
}
.tooltable th{
  text-align:left;
  color: rgba(255,255,255,.65);
  font-weight:700;
  background: rgba(255,255,255,.02);
}
</style>
"""

    editor_js = """
<script>
(function(){
  function qs(sel){ return document.querySelector(sel); }
  function qsa(sel){ return Array.from(document.querySelectorAll(sel)); }

  const viewCards = qs("#view_cards");
  const viewTable = qs("#view_table");
  const paneCards = qs("#pane_cards");
  const paneTable = qs("#pane_table");

  function applyView(){
    const v = (viewTable && viewTable.checked) ? "table" : "cards";
    if (paneCards) paneCards.style.display = (v==="cards") ? "block" : "none";
    if (paneTable) paneTable.style.display = (v==="table") ? "block" : "none";
  }
  if (viewCards) viewCards.addEventListener("change", applyView);
  if (viewTable) viewTable.addEventListener("change", applyView);
  applyView();

  // bind colorpickers -> sync to text inputs
  qsa('input[type="color"][data-bind="accent"]').forEach(cp=>{
    cp.addEventListener("input", ()=>{
      const idx = cp.getAttribute("data-idx");
      const txt = qs('input[name="accent_'+idx+'"]');
      if (txt) txt.value = cp.value;
    });
  });

  // delete buttons: set deleted_i=1 and hide blocks/rows
  qsa('[data-action="delete"]').forEach(btn=>{
    btn.addEventListener("click", ()=>{
      const idx = btn.getAttribute("data-idx");
      const del = qs('input[name="deleted_'+idx+'"]');
      if (del) del.value = "1";

      const card = qs('[data-card-idx="'+idx+'"]');
      if (card) card.style.display = "none";
      const row = qs('tr[data-row-idx="'+idx+'"]');
      if (row) row.style.display = "none";
    });
  });
})();
</script>
"""

    rows_html_cards: List[str] = []
    rows_html_table: List[str] = []

    for i, t in enumerate(tools):
        enabled = bool(t.get("enabled", True))
        hidden = bool(t.get("hidden", False))

        name = (t.get("name") or t.get("id") or "Tool").strip()
        icon = (t.get("icon_web") or t.get("icon") or "🧩").strip()
        accent = (t.get("accent") or "#35e6df").strip()

        accent_mode = (t.get("accent_mode") or "left").strip()
        stripe_px = int(t.get("stripe_px") or 6)
        ring_px = int(t.get("ring_px") or 2)
        glow_px = int(t.get("glow_px") or 22)

        tid = (t.get("id") or "").strip()
        web_path = (t.get("web_path") or t.get("path") or "").strip()
        script = (t.get("script") or "").strip()

        orig_json = json.dumps(t, ensure_ascii=False)
        hidden_fields = f"""
          <input type="hidden" name="orig_{i}" value='{_attr_json(orig_json)}'>
          <input type="hidden" name="deleted_{i}" value="0">
        """

        rgb = _hex_to_rgb(accent)

        def _mode_label(m: str) -> str:
            if m == "ring":
                return "ring (random)"
            if m == "bg":
                return "bg (background + ring)"
            return "left (stripe)"

        mode_options = f"""
          <option value="left" {"selected" if accent_mode=="left" else ""}>left (stripe)</option>
          <option value="ring" {"selected" if accent_mode=="ring" else ""}>ring (random)</option>
          <option value="bg"   {"selected" if accent_mode=="bg" else ""}>bg (background + ring)</option>
        """

        rows_html_cards.append(f"""
<div class="e-card {'bg-on' if card_bg else ''} {'round-on' if card_round else ''}" data-card-idx="{i}" style="--accent:{_html(accent)}; --accent-rgb:{rgb};">
  {hidden_fields}
  <div class="e-head">
    <div>
      <div class="e-title">
        <span style="font-size:18px;">{_html(icon)}</span>
        <span>{_html(name)}</span>
      </div>
      <div class="e-sub">{_html(tid)} • {_html(web_path)} • {_html(script)}</div>

      <div class="badges">
        <div class="badge">Accent: {_html(accent_mode or "left")}</div>
        <div class="badge">Stripe: {int(stripe_px)}px</div>
        <div class="badge">Ring: {int(ring_px)}px</div>
        <div class="badge">Glow: {int(glow_px)}px</div>
      </div>
    </div>

    <div style="display:flex; gap:12px; align-items:center;">
      <div style="display:flex; gap:10px; align-items:center;">
        <div class="e-sub" style="margin:0;">Hidden</div>
        <label class="switch" title="Hidden">
          <input type="checkbox" name="hidden_{i}" {"checked" if hidden else ""}>
          <span class="slider"></span>
        </label>
      </div>

      <div style="display:flex; gap:10px; align-items:center;">
        <div class="e-sub" style="margin:0;">Enabled</div>
        <label class="switch" title="Enabled">
          <input type="checkbox" name="enabled_{i}" {"checked" if enabled else ""}>
          <span class="slider"></span>
        </label>
      </div>

      <button type="button" class="mini danger" data-action="delete" data-idx="{i}" title="Verwijderen">✖</button>
    </div>
  </div>

  <div class="e-row">
    <input class="inp" name="name_{i}" value="{_html(name)}" placeholder="Naam">
    <input class="inp" name="icon_{i}" value="{_html(icon)}" placeholder="Icon (emoji)">
  </div>

  <div class="e-row">
    <div class="accentbox" style="flex:1;">
      <input class="inp" name="accent_{i}" value="{_html(accent)}" placeholder="#00ff66">
      <input type="color" class="colorpick" value="{_html(accent)}" data-bind="accent" data-idx="{i}">
    </div>

    <select class="inp" name="accent_mode_{i}" style="min-width: 260px;">
      {mode_options}
    </select>
  </div>

  <div class="e-row">
    <label class="badge" style="display:flex; gap:10px; align-items:center;">
      Stripe px
      <input class="inp" style="width:110px;" type="number" min="0" max="40" name="stripe_px_{i}" value="{int(stripe_px)}">
    </label>

    <label class="badge" style="display:flex; gap:10px; align-items:center;">
      Ring px
      <input class="inp" style="width:110px;" type="number" min="0" max="20" name="ring_px_{i}" value="{int(ring_px)}">
    </label>

    <label class="badge" style="display:flex; gap:10px; align-items:center;">
      Glow px
      <input class="inp" style="width:110px;" type="number" min="0" max="80" name="glow_px_{i}" value="{int(glow_px)}">
    </label>
  </div>
</div>
""")

        rows_html_table.append(f"""
<tr data-row-idx="{i}">
  <td style="width:110px;">
    {hidden_fields}
    <label class="switch" title="Enabled">
      <input type="checkbox" name="enabled_{i}" {"checked" if enabled else ""}>
      <span class="slider"></span>
    </label>
  </td>

  <td style="width:110px;">
    <label class="switch" title="Hidden">
      <input type="checkbox" name="hidden_{i}" {"checked" if hidden else ""}>
      <span class="slider"></span>
    </label>
  </td>

  <td style="width:120px;"><input class="inp" name="icon_{i}" value="{_html(icon)}"></td>
  <td style="min-width:240px;"><input class="inp" name="name_{i}" value="{_html(name)}"></td>

  <td style="min-width:240px;">
    <div class="accentbox">
      <input class="inp" name="accent_{i}" value="{_html(accent)}">
      <input type="color" class="colorpick" value="{_html(accent)}" data-bind="accent" data-idx="{i}">
    </div>
  </td>

  <td style="min-width:240px;">
    <select class="inp" name="accent_mode_{i}">
      {mode_options}
    </select>
  </td>

  <td style="width:130px;"><input class="inp" type="number" min="0" max="40" name="stripe_px_{i}" value="{int(stripe_px)}"></td>
  <td style="width:130px;"><input class="inp" type="number" min="0" max="20" name="ring_px_{i}" value="{int(ring_px)}"></td>
  <td style="width:130px;"><input class="inp" type="number" min="0" max="80" name="glow_px_{i}" value="{int(glow_px)}"></td>

  <td style="width:70px;">
    <button type="button" class="mini danger" data-action="delete" data-idx="{i}">✖</button>
  </td>
</tr>
""")

    ui_block = f"""
<div class="panel">
  <h2 style="margin:0 0 10px 0;">Tools editor</h2>

  <div class="hint" style="margin-bottom:14px;">
    Wijzigt <code>config/tools.json</code> (enabled/hidden, icon, naam, accent + accent mode + widths + globale UI).
  </div>

  <div class="tools-toolbar" style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
    <div class="pill">Home</div>

    <label class="btn" style="gap:10px;">
      Kolommen
      <input class="inp" style="width:110px;" type="number" min="1" max="12" name="home_columns" value="{home_cols}">
    </label>

    <label class="btn" style="gap:10px;">
      <input type="checkbox" name="card_bg" {"checked" if card_bg else ""}>
      Card background
    </label>

    <label class="btn" style="gap:10px;">
      <input type="checkbox" name="card_round" {"checked" if card_round else ""}>
      Rounded corners
    </label>

    <label class="btn" style="gap:10px;">
      <input type="checkbox" name="button_bg" {"checked" if button_bg else ""}>
      Button background
    </label>

    <label class="btn" style="gap:10px;">
      <input type="checkbox" name="button_rounded" {"checked" if button_rounded else ""}>
      Button rounded
    </label>

    <button class="btn btn-primary" type="submit">💾 Opslaan</button>
  </div>

  <div class="viewbar">
    <label class="viewtab">
      <input id="view_cards" type="radio" name="_view" value="cards" checked>
      <span>🧩 Visueel</span>
    </label>
    <label class="viewtab">
      <input id="view_table" type="radio" name="_view" value="table">
      <span>📋 Tabel</span>
    </label>
  </div>
</div>
"""

    cards_pane = f"""
<div id="pane_cards">
  <div class="editor-grid">
    {''.join(rows_html_cards) if rows_html_cards else "<div class='panel'>Geen tools</div>"}
  </div>
</div>
"""

    table_pane = f"""
<div id="pane_table" style="display:none;">
  <div class="tablewrap">
    <table class="tooltable">
      <thead>
        <tr>
          <th>Enabled</th>
          <th>Hidden</th>
          <th>Icon</th>
          <th>Naam</th>
          <th>Kleur</th>
          <th>Mode</th>
          <th>Stripe px</th>
          <th>Ring px</th>
          <th>Glow px</th>
          <th>Del</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows_html_table) if rows_html_table else ""}
      </tbody>
    </table>
  </div>
</div>
"""

    content = f"""
{editor_css}
<form method="post">
  <input type="hidden" name="row_count" value="{len(tools)}">
  {ui_block}
  {cards_pane}
  {table_pane}
</form>
{editor_js}
"""

    return render_page(title="Tools Editor", content_html=content)
