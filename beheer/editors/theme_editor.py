from __future__ import annotations

import json
from typing import Any, Dict, Tuple, List

from flask import request

from beheer.main_layout import render_page, load_theme_config


# =========================
# Helpers
# =========================
def _html(s: Any) -> str:
    return (
        str(s if s is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _attr_json(s: str) -> str:
    return _html(s).replace("'", "&#39;")


def _safe_json_load(s: str, fallback: Any) -> Any:
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


def _hex_norm(v: str, fallback: str) -> str:
    s = (v or "").strip()
    if not s:
        return fallback
    if not s.startswith("#"):
        # allow rgba(...) etc
        if s.lower().startswith("rgb"):
            return s
        return fallback
    if len(s) == 4:  # #abc
        s = "#" + "".join(ch * 2 for ch in s[1:])
    if len(s) != 7:
        return fallback
    return s


def _ensure_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    # normalize config
    if not isinstance(cfg, dict):
        cfg = {}
    themes = cfg.get("themes")
    if not isinstance(themes, dict):
        themes = {}
    cfg["themes"] = themes

    if not themes:
        # load_theme_config normally returns defaults already, but keep safe
        cfg = load_theme_config()
        themes = cfg.get("themes", {})
        if not isinstance(themes, dict):
            themes = {}
        cfg["themes"] = themes

    # normalize themes
    for k, v in list(themes.items()):
        if not isinstance(v, dict):
            themes[k] = {"icon": "🎨", "label": k, "vars": {}}
            v = themes[k]
        if "icon" not in v:
            v["icon"] = "🎨"
        if "label" not in v:
            v["label"] = k
        if "vars" not in v or not isinstance(v["vars"], dict):
            v["vars"] = {}

    active = str(cfg.get("active") or "").strip()
    if not active or active not in themes:
        active = next(iter(themes.keys())) if themes else "dark"
        cfg["active"] = active

    return cfg


def _save_cfg(cfg: Dict[str, Any]) -> None:
    # main_layout.py exposes _save_theme_config (internal)
    from beheer.main_layout import _save_theme_config  # type: ignore

    _save_theme_config(cfg)


def _pick_theme(cfg: Dict[str, Any], key: str) -> Tuple[str, Dict[str, Any]]:
    cfg = _ensure_cfg(cfg)
    themes = cfg["themes"]
    key = (key or "").strip()
    if key in themes:
        return key, themes[key]
    active = str(cfg.get("active") or "")
    if active in themes:
        return active, themes[active]
    if themes:
        k0 = next(iter(themes.keys()))
        cfg["active"] = k0
        return k0, themes[k0]
    # fallback
    return "dark", {"icon": "🌙", "label": "Dark", "vars": {}}


def _get_vars(theme: Dict[str, Any]) -> Dict[str, Any]:
    v = theme.get("vars", {})
    return v if isinstance(v, dict) else {}


# =========================
# Main handler
# =========================
def handle_theme_editor() -> str:
    cfg = _ensure_cfg(load_theme_config())
    themes: Dict[str, Any] = cfg.get("themes", {}) if isinstance(cfg.get("themes"), dict) else {}
    active = str(cfg.get("active") or "")

    # UI state
    view = (request.args.get("view") or request.form.get("view") or "wysiwyg").strip().lower()
    if view not in ("wysiwyg", "advanced"):
        view = "wysiwyg"

    selected = (request.args.get("t") or request.form.get("t") or active).strip()
    selected, theme = _pick_theme(cfg, selected)
    vars_map = _get_vars(theme)

    # Defaults for WYSIWYG fields
    defv = {
        "--bg": "#000000",
        "--text": "#e8f2f2",
        "--muted": "#9fb3b3",
        "--border": "rgba(255,255,255,.10)",
        "--shadow": "0 12px 40px rgba(0,0,0,.55)",
        "--accent": "#35e6df",
        "--grad_top": "#08121a",
        "--grad_bottom": "#000000",
        "--panel_bg": "rgba(10,15,18,.75)",
        "--card_bg": "rgba(10,15,18,.68)",
    }
    # merge theme vars over defaults
    merged_vars = dict(defv)
    for k, v in vars_map.items():
        if isinstance(k, str) and k.startswith("--"):
            merged_vars[k] = v

    msg = ""

    # =========================
    # POST actions
    # =========================
    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        selected = (request.form.get("t") or selected).strip()
        cfg = _ensure_cfg(load_theme_config())
        themes = cfg["themes"]

        # ---------- Create new ----------
        if action == "new":
            new_key = (request.form.get("new_key") or "").strip()
            new_icon = (request.form.get("new_icon") or "🎨").strip() or "🎨"
            new_label = (request.form.get("new_label") or "").strip() or new_key or "Theme"

            # sanitize key: keep simple
            safe = "".join(ch for ch in new_key if ch.isalnum() or ch in ("_", "-", ".")).strip()
            if not safe:
                msg = "❌ Geef een geldige theme-naam (letters/cijfers/_-.)"
            elif safe in themes:
                msg = "❌ Theme bestaat al"
            else:
                themes[safe] = {
                    "icon": new_icon,
                    "label": new_label,
                    "vars": dict(defv),
                }
                cfg["active"] = safe
                _save_cfg(cfg)
                msg = "✅ Nieuwe theme aangemaakt"
                selected = safe
                theme = themes[safe]

        # ---------- Delete ----------
        elif action == "delete":
            del_key = (request.form.get("del_key") or "").strip()
            if del_key in themes:
                if len(themes) <= 1:
                    msg = "❌ Je kan de laatste theme niet verwijderen"
                else:
                    themes.pop(del_key, None)
                    if cfg.get("active") == del_key:
                        cfg["active"] = next(iter(themes.keys()))
                    _save_cfg(cfg)
                    msg = f"🗑️ Theme verwijderd: {del_key}"
                    selected = str(cfg.get("active") or next(iter(themes.keys())))
                    theme = themes[selected]
            else:
                msg = "❌ Theme niet gevonden"

        # ---------- Set active ----------
        elif action == "set_active":
            set_key = (request.form.get("set_key") or "").strip()
            if set_key in themes:
                cfg["active"] = set_key
                _save_cfg(cfg)
                msg = f"✅ Actieve theme: {set_key}"
                selected = set_key
                theme = themes[set_key]
            else:
                msg = "❌ Theme niet gevonden"

        # ---------- Save (wysiwyg) ----------
        elif action == "save_wysiwyg":
            if selected not in themes:
                msg = "❌ Theme niet gevonden"
            else:
                t = themes[selected]
                t["icon"] = (request.form.get("icon") or t.get("icon") or "🎨").strip() or "🎨"
                t["label"] = (request.form.get("label") or t.get("label") or selected).strip() or selected

                v = t.get("vars", {})
                if not isinstance(v, dict):
                    v = {}
                # color-ish
                v["--bg"] = _hex_norm(request.form.get("bg", ""), str(v.get("--bg", defv["--bg"])))
                v["--text"] = _hex_norm(request.form.get("text", ""), str(v.get("--text", defv["--text"])))
                v["--muted"] = _hex_norm(request.form.get("muted", ""), str(v.get("--muted", defv["--muted"])))
                v["--accent"] = _hex_norm(request.form.get("accent", ""), str(v.get("--accent", defv["--accent"])))

                v["--grad_top"] = _hex_norm(request.form.get("grad_top", ""), str(v.get("--grad_top", defv["--grad_top"])))
                v["--grad_bottom"] = _hex_norm(request.form.get("grad_bottom", ""), str(v.get("--grad_bottom", defv["--grad_bottom"])))

                # free text fields (rgba / box-shadow)
                v["--border"] = (request.form.get("border", "") or v.get("--border", defv["--border"])).strip()
                v["--panel_bg"] = (request.form.get("panel_bg", "") or v.get("--panel_bg", defv["--panel_bg"])).strip()
                v["--card_bg"] = (request.form.get("card_bg", "") or v.get("--card_bg", defv["--card_bg"])).strip()
                v["--shadow"] = (request.form.get("shadow", "") or v.get("--shadow", defv["--shadow"])).strip()

                t["vars"] = v
                themes[selected] = t
                cfg["themes"] = themes

                # optional: keep active
                if request.form.get("make_active") == "1":
                    cfg["active"] = selected

                _save_cfg(cfg)
                msg = "💾 Opgeslagen (WYSIWYG)"

        # ---------- Save (advanced) ----------
        elif action == "save_advanced":
            if selected not in themes:
                msg = "❌ Theme niet gevonden"
            else:
                t = themes[selected]
                t["icon"] = (request.form.get("icon") or t.get("icon") or "🎨").strip() or "🎨"
                t["label"] = (request.form.get("label") or t.get("label") or selected).strip() or selected

                raw_vars = (request.form.get("vars_json") or "").strip()
                parsed = _safe_json_load(raw_vars, None)
                if not isinstance(parsed, dict):
                    msg = "❌ JSON is ongeldig (verwacht een object/dict)"
                else:
                    # keep only --* keys (and allow user to store extras if you want; for now: only css vars)
                    v: Dict[str, Any] = {}
                    for k, val in parsed.items():
                        if isinstance(k, str) and k.startswith("--"):
                            v[k] = val
                    if not v:
                        msg = "❌ Geen CSS variabelen gevonden (keys moeten starten met --)"
                    else:
                        t["vars"] = v
                        themes[selected] = t
                        cfg["themes"] = themes

                        if request.form.get("make_active") == "1":
                            cfg["active"] = selected

                        _save_cfg(cfg)
                        msg = "💾 Opgeslagen (Advanced)"

        else:
            msg = "⚠️ Onbekende actie"

        # reload after any POST
        cfg = _ensure_cfg(load_theme_config())
        themes = cfg["themes"]
        selected, theme = _pick_theme(cfg, selected)
        vars_map = _get_vars(theme)

        merged_vars = dict(defv)
        for k, v in vars_map.items():
            if isinstance(k, str) and k.startswith("--"):
                merged_vars[k] = v

        active = str(cfg.get("active") or "")

    # =========================
    # Render UI
    # =========================
    # Sidebar list
    theme_rows: List[str] = []
    for k in themes.keys():
        tv = themes.get(k, {})
        if not isinstance(tv, dict):
            tv = {}
        icon = str(tv.get("icon") or "🎨")
        label = str(tv.get("label") or k)
        is_sel = "sel" if k == selected else ""
        is_active = "active" if k == active else ""
        theme_rows.append(
            f"""
            <a class="titem {is_sel} {is_active}" href="/beheer/theme?t={_html(k)}&view={_html(view)}">
              <div class="ticon">{_html(icon)}</div>
              <div class="ttext">
                <div class="tname">{_html(label)}</div>
                <div class="tsub">{_html(k)}{' • actief' if k==active else ''}</div>
              </div>
            </a>
            """
        )
    theme_list_html = "\n".join(theme_rows) or "<div class='muted'>Geen themes</div>"

    # Vars for WYSIWYG fields
    f_bg = str(merged_vars.get("--bg", defv["--bg"]))
    f_text = str(merged_vars.get("--text", defv["--text"]))
    f_muted = str(merged_vars.get("--muted", defv["--muted"]))
    f_accent = str(merged_vars.get("--accent", defv["--accent"]))

    f_border = str(merged_vars.get("--border", defv["--border"]))
    f_shadow = str(merged_vars.get("--shadow", defv["--shadow"]))
    f_grad_top = str(merged_vars.get("--grad_top", defv["--grad_top"]))
    f_grad_bottom = str(merged_vars.get("--grad_bottom", defv["--grad_bottom"]))
    f_panel_bg = str(merged_vars.get("--panel_bg", defv["--panel_bg"]))
    f_card_bg = str(merged_vars.get("--card_bg", defv["--card_bg"]))

    t_icon = str(theme.get("icon") or "🎨")
    t_label = str(theme.get("label") or selected)

    # Advanced JSON
    adv_json = json.dumps(vars_map if isinstance(vars_map, dict) else {}, indent=2, ensure_ascii=False)

    # Live preview CSS vars inline
    preview_style = "\n".join([f"{k}:{merged_vars[k]};" for k in merged_vars.keys() if k.startswith("--")])

    css = """
<style>
.theme-grid{
  display:grid;
  grid-template-columns: 360px 1fr;
  gap: 14px;
}
@media (max-width: 980px){
  .theme-grid{ grid-template-columns: 1fr; }
}

.side{
  border: 1px solid rgba(255,255,255,.10);
  border-radius: 18px;
  background: rgba(10,15,18,.65);
  box-shadow: 0 12px 40px rgba(0,0,0,.35);
  padding: 14px;
}
.mainp{
  border: 1px solid rgba(255,255,255,.10);
  border-radius: 18px;
  background: rgba(10,15,18,.65);
  box-shadow: 0 12px 40px rgba(0,0,0,.35);
  padding: 14px;
}

.topactions{
  display:flex;
  gap:10px;
  flex-wrap:wrap;
  align-items:center;
  justify-content:space-between;
  margin-bottom: 12px;
}
.topactions .left, .topactions .right{
  display:flex;
  gap:10px;
  flex-wrap:wrap;
  align-items:center;
}

.tabs{ display:flex; gap:10px; flex-wrap:wrap; margin: 10px 0 12px 0; }
.tab{
  user-select:none;
}
.tab input{ display:none; }
.tab span{
  display:inline-flex; align-items:center; gap:8px;
  padding: 10px 14px; border-radius: 999px;
  border: 1px solid rgba(255,255,255,.14);
  background: rgba(255,255,255,.03);
  cursor:pointer;
}
.tab input:checked + span{
  border-color: rgba(53,230,223,.55);
  box-shadow: 0 0 0 2px rgba(53,230,223,.10);
  background: rgba(255,255,255,.05);
}

.tlist{ display:flex; flex-direction:column; gap:10px; margin-top: 10px; }
.titem{
  display:flex; gap:10px; align-items:center;
  padding: 10px 12px;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,.10);
  background: rgba(255,255,255,.03);
  color: #e8f2f2;
  text-decoration:none;
}
.titem:hover{ background: rgba(255,255,255,.06); }
.titem.sel{ border-color: rgba(53,230,223,.45); box-shadow: 0 0 0 2px rgba(53,230,223,.10); }
.titem.active{ outline: 2px solid rgba(255,255,255,.10); outline-offset: 2px; }

.ticon{ font-size: 20px; width: 34px; text-align:center; }
.tname{ font-weight: 800; }
.tsub{ font-size: 12px; color: rgba(255,255,255,.55); }

.hr{ height:1px; background: rgba(255,255,255,.08); margin: 12px 0; }

.row{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top: 10px; }
.row .inp{ flex: 1; min-width: 180px; }
.row .short{ width: 140px; min-width: 140px; }

.inp, select.inp, textarea.inp{
  background: rgba(0,0,0,.65) !important;
  color: #e8f2f2 !important;
  border: 1px solid rgba(255,255,255,.22) !important;
  border-radius: 12px !important;
  padding: 10px 12px !important;
  outline: none !important;
}
.inp:focus{
  border-color: rgba(53,230,223,.55) !important;
  box-shadow: 0 0 0 2px rgba(53,230,223,.12) !important;
}

.mini{
  padding: 8px 10px;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,.10);
  background: rgba(255,255,255,.03);
  color: #e8f2f2;
  cursor:pointer;
}
.mini:hover{ background: rgba(255,255,255,.06); }
.mini.danger{ border-color: rgba(255,80,80,.35); }
.mini.primary{
  border-color: rgba(53,230,223,.35);
}

.notice{
  padding: 10px 12px;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,.10);
  background: rgba(255,255,255,.03);
  color: rgba(255,255,255,.85);
}

.preview{
  border: 1px solid rgba(255,255,255,.10);
  border-radius: 18px;
  background: rgba(0,0,0,.35);
  padding: 14px;
  margin-top: 14px;
}
.pwrap{
  border-radius: 16px;
  overflow:hidden;
  border: 1px solid rgba(255,255,255,.08);
}
.phead{
  display:flex; align-items:center; justify-content:space-between;
  padding: 10px 12px;
  background: linear-gradient(180deg, rgba(0,0,0,.75), rgba(0,0,0,.35));
  border-bottom: 1px solid rgba(255,255,255,.10);
}
.pbrand{
  display:flex; gap:10px; align-items:center; font-weight: 900;
  color: var(--text);
}
.plogo{
  width: 34px; height: 34px; border-radius: 10px;
  border: 1px solid rgba(255,255,255,.12);
  background: rgba(255,255,255,.04);
  display:flex; align-items:center; justify-content:center;
}
.pbody{
  padding: 14px;
  background: radial-gradient(1200px 700px at 50% 0%, var(--grad_top) 0%, var(--grad_bottom) 60%);
  color: var(--text);
}
.ppanel{
  background: var(--panel_bg);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 14px;
  box-shadow: var(--shadow);
}
.ptool{
  margin-top: 12px;
  background: var(--card_bg);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 14px;
  box-shadow: var(--shadow);
  border-left: 5px solid var(--accent);
}
.ptitle{ font-weight: 900; }
.pdesc{ color: var(--muted); margin-top: 6px; }

.colorrow{
  display:flex; gap:10px; align-items:center;
  flex-wrap:wrap;
}
.colorpick{
  width: 44px; height: 36px;
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 12px;
  background: transparent;
  padding: 0;
}

textarea.big{
  width: 100%;
  min-height: 360px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  line-height: 1.35;
}
.muted{ color: rgba(255,255,255,.55); font-size: 12px; }
</style>
"""

    js = """
<script>
(function(){
  function qs(sel){ return document.querySelector(sel); }
  function qsa(sel){ return Array.from(document.querySelectorAll(sel)); }

  // confirm delete
  const delBtn = qs("#btnDeleteTheme");
  if(delBtn){
    delBtn.addEventListener("click", function(e){
      const key = delBtn.getAttribute("data-key") || "";
      if(!key) return;
      const ok = confirm("Theme verwijderen: " + key + " ?\\n\\nDit kan je niet undo'en.");
      if(!ok){
        e.preventDefault();
        e.stopPropagation();
        return false;
      }
      // submit hidden form
      const f = qs("#formDelete");
      if(f) f.submit();
    });
  }

  // live preview updates (wysiwyg)
  function setVar(name, value){
    const pv = qs("#livePreview");
    if(pv) pv.style.setProperty(name, value);
  }

  function bindColorPair(txtId, colId, varName){
    const txt = qs(txtId);
    const col = qs(colId);
    if(!txt || !col) return;

    function syncFromColor(){
      txt.value = col.value;
      setVar(varName, col.value);
    }
    function syncFromText(){
      const v = (txt.value || "").trim();
      // best effort: if hex -> sync picker
      if(/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(v)){
        let hv = v;
        if(hv.length === 4){
          hv = "#" + hv.slice(1).split("").map(c=>c+c).join("");
        }
        col.value = hv;
        setVar(varName, hv);
      }else{
        // allow rgb/rgba or invalid text; preview still applies
        setVar(varName, v);
      }
    }

    col.addEventListener("input", syncFromColor);
    txt.addEventListener("input", syncFromText);

    // init
    syncFromText();
  }

  bindColorPair("#bg","#bgc","--bg");
  bindColorPair("#text","#textc","--text");
  bindColorPair("#muted","#mutedc","--muted");
  bindColorPair("#accent","#accentc","--accent");
  bindColorPair("#grad_top","#grad_topc","--grad_top");
  bindColorPair("#grad_bottom","#grad_bottomc","--grad_bottom");

  // free text vars
  const free = [
    ["#border","--border"],
    ["#panel_bg","--panel_bg"],
    ["#card_bg","--card_bg"],
    ["#shadow","--shadow"],
  ];
  free.forEach(([id,varName])=>{
    const el = qs(id);
    if(!el) return;
    el.addEventListener("input", ()=> setVar(varName, el.value));
    setVar(varName, el.value);
  });

  // icon/label preview in header
  const icon = qs("#icon");
  const label = qs("#label");
  const pvIcon = qs("#pvIcon");
  const pvLabel = qs("#pvLabel");
  function syncHead(){
    if(pvIcon && icon) pvIcon.textContent = icon.value || "🎨";
    if(pvLabel && label) pvLabel.textContent = label.value || "Theme";
  }
  if(icon) icon.addEventListener("input", syncHead);
  if(label) label.addEventListener("input", syncHead);
  syncHead();
})();
</script>
"""

    # Tabs (view)
    tab_w = "checked" if view == "wysiwyg" else ""
    tab_a = "checked" if view == "advanced" else ""

    # Header buttons / forms
    header_actions = f"""
<div class="topactions">
  <div class="left">
    <div class="notice"><b>Theme editor</b> • kies links een theme • pas aan • <b>Opslaan</b></div>
    {"<div class='notice'>"+_html(msg)+"</div>" if msg else ""}
  </div>
  <div class="right">
    <form method="post" style="margin:0; display:flex; gap:10px; align-items:center;">
      <input type="hidden" name="t" value="{_html(selected)}">
      <input type="hidden" name="view" value="{_html(view)}">
      <input type="hidden" name="action" value="set_active">
      <input type="hidden" name="set_key" value="{_html(selected)}">
      <button class="mini" type="submit" title="Maak actief">✅ Maak actief</button>
    </form>

    <button id="btnDeleteTheme" class="mini danger" type="button" data-key="{_html(selected)}" title="Verwijder theme">🗑️ Verwijder</button>

    <form method="post" style="margin:0;">
      <input type="hidden" name="t" value="{_html(selected)}">
      <input type="hidden" name="view" value="{_html(view)}">
      <input type="hidden" name="action" value="save_{_html(view)}">
      <button class="mini primary" type="submit" title="Opslaan">💾 Opslaan</button>
    </form>
  </div>
</div>

<form id="formDelete" method="post" style="display:none;">
  <input type="hidden" name="action" value="delete">
  <input type="hidden" name="del_key" value="{_html(selected)}">
</form>
"""

    # Create new theme
    new_theme_block = """
<div class="hr"></div>
<form method="post" style="margin:0;">
  <input type="hidden" name="action" value="new">
  <div class="row">
    <input class="inp" name="new_key" placeholder="Nieuwe theme key (bv dark2)" required>
  </div>
  <div class="row">
    <input class="inp short" name="new_icon" placeholder="Icon (emoji)" value="🎨">
    <input class="inp" name="new_label" placeholder="Label (bv 'Dark 2')" >
  </div>
  <div class="row">
    <button class="mini primary" type="submit">➕ Theme aanmaken</button>
  </div>
  <div class="muted">Tip: key mag letters/cijfers/._-</div>
</form>
"""

    # Tabs UI
    tabs = f"""
<div class="tabs">
  <label class="tab">
    <input type="radio" name="vtab" {tab_w} onclick="window.location.href='/beheer/theme?t={_html(selected)}&view=wysiwyg'">
    <span>🪄 WYSIWYG</span>
  </label>
  <label class="tab">
    <input type="radio" name="vtab" {tab_a} onclick="window.location.href='/beheer/theme?t={_html(selected)}&view=advanced'">
    <span>🧠 Advanced</span>
  </label>
</div>
"""

    # Shared meta fields
    meta_fields = f"""
<div class="row">
  <input id="icon" class="inp short" name="icon" value="{_html(t_icon)}" placeholder="Icon (emoji)">
  <input id="label" class="inp" name="label" value="{_html(t_label)}" placeholder="Label">
  <label class="mini" style="display:flex; align-items:center; gap:8px;">
    <input type="checkbox" name="make_active" value="1"> Actief zetten bij opslaan
  </label>
</div>
"""

    # WYSIWYG panel
    wysiwyg_form = f"""
<form method="post" style="margin:0;">
  <input type="hidden" name="action" value="save_wysiwyg">
  <input type="hidden" name="t" value="{_html(selected)}">
  <input type="hidden" name="view" value="wysiwyg">

  {meta_fields}

  <div class="hr"></div>

  <div class="row colorrow">
    <div style="min-width:180px;">
      <div class="muted">Background</div>
      <div class="row" style="margin-top:6px;">
        <input id="bg" class="inp" name="bg" value="{_html(f_bg)}">
        <input id="bgc" class="colorpick" type="color" value="{_html(_hex_norm(f_bg, '#000000'))}">
      </div>
    </div>

    <div style="min-width:180px;">
      <div class="muted">Text</div>
      <div class="row" style="margin-top:6px;">
        <input id="text" class="inp" name="text" value="{_html(f_text)}">
        <input id="textc" class="colorpick" type="color" value="{_html(_hex_norm(f_text, '#e8f2f2'))}">
      </div>
    </div>

    <div style="min-width:180px;">
      <div class="muted">Muted</div>
      <div class="row" style="margin-top:6px;">
        <input id="muted" class="inp" name="muted" value="{_html(f_muted)}">
        <input id="mutedc" class="colorpick" type="color" value="{_html(_hex_norm(f_muted, '#9fb3b3'))}">
      </div>
    </div>

    <div style="min-width:180px;">
      <div class="muted">Accent</div>
      <div class="row" style="margin-top:6px;">
        <input id="accent" class="inp" name="accent" value="{_html(f_accent)}">
        <input id="accentc" class="colorpick" type="color" value="{_html(_hex_norm(f_accent, '#35e6df'))}">
      </div>
    </div>
  </div>

  <div class="row colorrow">
    <div style="min-width:220px;">
      <div class="muted">Gradient top</div>
      <div class="row" style="margin-top:6px;">
        <input id="grad_top" class="inp" name="grad_top" value="{_html(f_grad_top)}">
        <input id="grad_topc" class="colorpick" type="color" value="{_html(_hex_norm(f_grad_top, '#08121a'))}">
      </div>
    </div>

    <div style="min-width:220px;">
      <div class="muted">Gradient bottom</div>
      <div class="row" style="margin-top:6px;">
        <input id="grad_bottom" class="inp" name="grad_bottom" value="{_html(f_grad_bottom)}">
        <input id="grad_bottomc" class="colorpick" type="color" value="{_html(_hex_norm(f_grad_bottom, '#000000'))}">
      </div>
    </div>
  </div>

  <div class="hr"></div>

  <div class="row">
    <div style="flex:1; min-width:260px;">
      <div class="muted">Border (rgba / color)</div>
      <input id="border" class="inp" name="border" value="{_html(f_border)}">
    </div>
    <div style="flex:1; min-width:260px;">
      <div class="muted">Panel background (rgba)</div>
      <input id="panel_bg" class="inp" name="panel_bg" value="{_html(f_panel_bg)}">
    </div>
  </div>

  <div class="row">
    <div style="flex:1; min-width:260px;">
      <div class="muted">Card background (rgba)</div>
      <input id="card_bg" class="inp" name="card_bg" value="{_html(f_card_bg)}">
    </div>
    <div style="flex:1; min-width:260px;">
      <div class="muted">Shadow (box-shadow)</div>
      <input id="shadow" class="inp" name="shadow" value="{_html(f_shadow)}">
    </div>
  </div>

  <div class="row" style="margin-top:14px;">
    <button class="mini primary" type="submit">💾 Opslaan</button>
  </div>
</form>

<div class="preview">
  <div class="muted">Live preview (niet klikbaar)</div>
  <div id="livePreview" class="pwrap" style="{_html(preview_style)}">
    <div class="phead">
      <div class="pbrand">
        <div class="plogo" id="pvIcon">{_html(t_icon)}</div>
        <div id="pvLabel">{_html(t_label)}</div>
      </div>
      <div class="muted">header</div>
    </div>
    <div class="pbody">
      <div class="ppanel">
        <div class="ptitle">Panel title</div>
        <div class="pdesc">Dit is een panel volgens jouw theme.</div>
      </div>
      <div class="ptool">
        <div class="ptitle">Toolcard</div>
        <div class="pdesc">Accent stripe + kleuren + shadow</div>
      </div>
    </div>
  </div>
</div>
"""

    # Advanced panel
    advanced_form = f"""
<form method="post" style="margin:0;">
  <input type="hidden" name="action" value="save_advanced">
  <input type="hidden" name="t" value="{_html(selected)}">
  <input type="hidden" name="view" value="advanced">

  {meta_fields}

  <div class="hr"></div>

  <div class="muted">Plak hier een JSON object met CSS variabelen (keys moeten starten met <code>--</code>).</div>
  <textarea class="inp big" name="vars_json">{_html(adv_json)}</textarea>

  <div class="row" style="margin-top:14px;">
    <button class="mini primary" type="submit">💾 Opslaan</button>
  </div>
</form>

<div class="preview">
  <div class="muted">Preview gebruikt de huidige theme (van de geselecteerde theme)</div>
  <div class="pwrap" style="{_html(preview_style)}">
    <div class="phead">
      <div class="pbrand">
        <div class="plogo">{_html(t_icon)}</div>
        <div>{_html(t_label)}</div>
      </div>
      <div class="muted">advanced</div>
    </div>
    <div class="pbody">
      <div class="ppanel">
        <div class="ptitle">Panel title</div>
        <div class="pdesc">Dit is een panel volgens jouw theme.</div>
      </div>
      <div class="ptool">
        <div class="ptitle">Toolcard</div>
        <div class="pdesc">Accent stripe + kleuren + shadow</div>
      </div>
    </div>
  </div>
</div>
"""

    # Decide which body to show
    editor_body = wysiwyg_form if view == "wysiwyg" else advanced_form

    content = f"""
{css}

<div class="panel">
  <h2 style="margin:0 0 6px 0;">Theme Config</h2>
  <div class="muted">
    Bestandsopslag: <code>config/theme.json</code> • actief: <b>{_html(active)}</b> • geselecteerd: <b>{_html(selected)}</b>
  </div>
</div>

<div class="theme-grid" style="margin-top:14px;">
  <div class="side">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <div style="font-weight:900;">Themes</div>
      <span class="pill">{_html(len(themes))} items</span>
    </div>
    <div class="tlist">
      {theme_list_html}
    </div>
    {new_theme_block}
  </div>

  <div class="mainp">
    {header_actions}
    {tabs}
    {editor_body}
  </div>
</div>

{js}
"""
    return render_page(title="Theme", content_html=content)
