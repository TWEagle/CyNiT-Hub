
# tools/useful_links.py
# -*- coding: utf-8 -*-
"""
Nuttige links — volledige hub-versie (gefixte template en rendering).
- Opslag: config/useful_links.json
- Grid-settings: config/settings.json (useful_links.modes.<mode>.*)
- Integratie: beheer.main_layout.render_page()
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from flask import Flask, request, render_template_string, redirect, url_for
from beheer.main_layout import render_page as hub_render_page  # type: ignore

# Paden
BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = BASE_DIR / "config"
DATA_PATH = CONFIG_DIR / "useful_links.json"
SETTINGS_PATH = CONFIG_DIR / "settings.json"

# Defaults
FALLBACK_CATEGORY = "Algemeen"
DEFAULT_COLOR = "#35e6df"
DEFAULT_VIEW_MODE = "comfortable"  # of "compact"


# ---------- helpers ----------
def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _normalize(s: str | None) -> str:
    return (s or "").strip()


def _hex(s: str | None, default: str = DEFAULT_COLOR) -> str:
    s = (s or "").strip()
    return s if len(s) == 7 and s.startswith("#") else default


def _default_db() -> Dict[str, Any]:
    return {
        "version": 1,
        "prefs": {
            "default_category": FALLBACK_CATEGORY,
            "hide_default_category": False,
            "view_mode": DEFAULT_VIEW_MODE,
        },
        "categories": {FALLBACK_CATEGORY: {"color": DEFAULT_COLOR}},
        "links": [],
    }


def _default_settings() -> Dict[str, Any]:
    return {
        "useful_links": {
            "default_mode": DEFAULT_VIEW_MODE,
            "modes": {
                "comfortable": {
                    "min_width": 280,
                    "gap": 14,
                    "card_padding_y": 10,
                    "card_padding_x": 12,
                    "breakpoints": [[1400, 4], [1600, 5], [1900, 6]],
                    "max_columns": 6,
                },
                "compact": {
                    "min_width": 240,
                    "gap": 10,
                    "card_padding_y": 8,
                    "card_padding_x": 10,
                    "breakpoints": [[1400, 5], [1600, 6], [1900, 7]],
                    "max_columns": 7,
                },
                # Optioneel: safety_min_width om te voorkomen dat kaarten te smal worden
                # wordt alleen toegepast als > 0
            },
        }
    }


def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _save_json(path: Path, data: Dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


# ---------- DB normalisatie ----------
def load_db() -> Dict[str, Any]:
    """Laadt/normaliseert useful_links.json en vult ontbrekende defaults aan."""
    db = _load_json(DATA_PATH, _default_db())
    changed = False

    if not isinstance(db.get("links"), list):
        db["links"] = []
        changed = True

    if not isinstance(db.get("categories"), dict):
        db["categories"] = {FALLBACK_CATEGORY: {"color": DEFAULT_COLOR}}
        changed = True

    if not isinstance(db.get("prefs"), dict):
        db["prefs"] = {
            "default_category": FALLBACK_CATEGORY,
            "hide_default_category": False,
            "view_mode": DEFAULT_VIEW_MODE,
        }
        changed = True

    # prefs normaliseren
    prefs = db["prefs"]
    prefs["default_category"] = _normalize(prefs.get("default_category")) or FALLBACK_CATEGORY
    prefs["hide_default_category"] = bool(prefs.get("hide_default_category", False))
    vm = _normalize(prefs.get("view_mode")) or DEFAULT_VIEW_MODE
    prefs["view_mode"] = vm if vm in ("comfortable", "compact") else DEFAULT_VIEW_MODE

    if prefs["default_category"] not in db["categories"]:
        db["categories"][prefs["default_category"]] = {"color": DEFAULT_COLOR}
        changed = True

    # categorie-kleuren valideren
    for k, meta in list(db["categories"].items()):
        if not isinstance(meta, dict):
            db["categories"][k] = {"color": DEFAULT_COLOR}
            changed = True
        else:
            col = _hex(meta.get("color"), DEFAULT_COLOR)
            if meta.get("color") != col:
                meta["color"] = col
                changed = True

    # links normaliseren
    norm: List[Dict[str, Any]] = []
    default_cat = prefs["default_category"]
    for r in db["links"]:
        if not isinstance(r, dict):
            changed = True
            continue
        name = _normalize(r.get("name"))
        url = _normalize(r.get("url"))
        if not name or not url:
            changed = True
            continue
        r.setdefault("id", str(uuid.uuid4()))
        cat = _normalize(r.get("category")) or default_cat
        if r.get("category") != cat:
            r["category"] = cat
            changed = True
        r.setdefault("info", "")
        r.setdefault("created", _now_iso())
        r.setdefault("updated", r.get("created", _now_iso()))
        if cat not in db["categories"]:
            db["categories"][cat] = {"color": DEFAULT_COLOR}
            changed = True
        norm.append(r)

    if norm != db["links"]:
        db["links"] = norm
        changed = True

    if changed:
        _save_json(DATA_PATH, db)
    return db


def save_db(db: Dict[str, Any]) -> None:
    _save_json(DATA_PATH, db)


# ---------- CONTENT TEMPLATE (HTML/CSS/JS) ----------
def _grid_css_from_settings(st: Dict[str, Any]) -> str:
    """Genereer CSS voor beide modes op basis van settings.json"""
    u = st.get("useful_links") or {}
    modes = u.get("modes") or {}
    css_parts: List[str] = []

    for mode_name in ("comfortable", "compact"):
        m = modes.get(mode_name) or {}
        minw = int(m.get("min_width", 280 if mode_name == "comfortable" else 240))
        gap = int(m.get("gap", 14 if mode_name == "comfortable" else 10))
        py = int(m.get("card_padding_y", 10 if mode_name == "comfortable" else 8))
        px = int(m.get("card_padding_x", 12 if mode_name == "comfortable" else 10))
        bps = m.get("breakpoints", [])
        maxc = int(m.get("max_columns", 6 if mode_name == "comfortable" else 7))

        css_parts.append(f"""
/* {mode_name} basis */
.grid {{
  display:grid;
  grid-template-columns: repeat(auto-fill, minmax({minw}px, 1fr));
  gap:{gap}px;
}}
.cardlink {{
  padding:{py}px {px}px;
}}
""")

        for bp in bps:
            try:
                w, cols = int(bp[0]), int(bp[1])
                cols = min(cols, maxc)
                css_parts.append(f"""
@media (min-width:{w}px) {{
  .grid {{ grid-template-columns: repeat({cols}, 1fr); }}
}}
""")
            except Exception:
                pass

    return "\n".join(css_parts)


CONTENT_TEMPLATE = r"""
<style>
/* Basis layout */
.links-wrap { max-width: 1100px; margin: 0 auto; }
.card {
  background: rgba(10,15,18,.85);
  border:1px solid rgba(255,255,255,.10);
  border-radius: 12px;
  padding:16px 20px;
  margin-bottom: 20px;
}
.hint { opacity:.85; font-size:.9em; }
.err { color:#ff4d4d; font-weight:bold; margin:8px 0 10px 0; }
.ok  { color:#88ff88; font-weight:bold; margin:8px 0 10px 0; }

/* Tabs */
.topbar { display:flex; justify-content:space-between; margin-bottom:14px; }
.tabs { display:flex; gap:8px; }
.tabbtn {
  border:1px solid #333;
  background:#111;
  padding:6px 12px;
  cursor:pointer;
  color:#e8f2f2;
}
.tabbtn.active {
  background:#35e6df;
  color:#000;
  border-color:#35e6df;
  font-weight:800;
}

/* Categorieën */
.catbar { display:flex; flex-wrap:wrap; gap:10px; }
.catblock {
  display:flex; flex-direction:column;
  width:160px; min-height:58px; padding:10px 12px;
  background:#0b0b0b; border:1px solid #2a2a2a;
  text-decoration:none; color:#e8f2f2;
}
.catblock:hover { background:#101010; }
.catname { font-weight:800; }
.catcount { opacity:.85; font-size:.9em; }

/* Grid */
.grid { display:grid; margin-bottom:18px; }

/* Optionele veiligheidsminimum breedte (houd kaarten leesbaar) */
.cardlink { min-width: 220px; }

/* Kaarten */
.cardlink {
  border:1px solid #2a2a2a;
  background:#0b0b0b;
  display:flex;
  flex-direction:column;
}
.cardlink:hover { border-color:var(--catcolor,#35e6df); }
.cardhead {
  display:flex;
  justify-content:space-between;
  border-bottom:1px solid #222;
  padding-bottom:8px;
  margin-bottom:8px;
}
.actions { display:flex; gap:6px; }
.iconbtn {
  border:1px solid #333;
  background:#111;
  padding:4px 8px;
  cursor:pointer;
  color:#e8f2f2;
}
.linkname { font-weight:800; color:var(--catcolor,#35e6df); }
a.url { color:#e8f2f2; word-break: break-all; }

/* Forms */
.form-row {
  display:grid;
  grid-template-columns:160px 1fr;
  gap:10px;
  margin:8px 0;
}
.in {
  width:100%;
  padding:7px 10px;
  border:1px solid #333;
  background:#0b0b0b;
  color:#e8f2f2;
}

/* Grid CSS vanuit settings */
{{ grid_css | safe }}

/* Modals (basis) */
.modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.6); z-index:1000; }
.modal.open { display:flex; align-items:center; justify-content:center; }
.modalbox { background:#0b0b0b; border:1px solid #2a2a2a; border-radius:12px; padding:16px 20px; width:min(680px, 96vw); }
.badge { border:1px solid #2a2a2a; padding:2px 6px; border-radius:6px; font-size:.8em; }
.sep { border:0; border-top:1px solid #222; }
.rename-preview-bar { height:8px; border-radius:6px; background:#35e6df; }
.rename-preview-title { font-weight:800; }
</style>

<div class="links-wrap">
  <h1>Nuttige links</h1>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  {% if msg %}<div class="ok">{{ msg }}</div>{% endif %}

  <div class="topbar">
    <div class="tabs">
      <button id="tab-links"  class="tabbtn {% if active_tab=='links'  %}active{% endif %}">Links</button>
      <button id="tab-manage" class="tabbtn {% if active_tab=='manage' %}active{% endif %}">Beheer</button>
    </div>
  </div>

  <div class="card">
    <h2>Categorieën</h2>
    <div class="catbar">
      {% for c in categories %}
        <a class="catblock" href="/links?cat={{ c }}#links">
          <div class="catname">{{ c }}</div>
          <div class="catcount">{{ counts.get(c,0) }} link(s)</div>
        </a>
      {% endfor %}
      <a class="catblock" href="/links?cat=__ALL__#links">
        <div class="catname">Alle</div>
        <div class="catcount">{{ total }} link(s)</div>
      </a>
    </div>
  </div>

  <!-- PANEL: LINKS -->
  <div id="panel-links" class="card" {% if active_tab!='links' %}style="display:none;"{% endif %}>
    <h2>Links</h2>
    {% if filtered %}
      <div class="grid">
        {% for r in filtered %}
          {% set cc = cat_colors.get(r.category, '#35e6df') %}
          <div class="cardlink"
               data-link-card="1"
               data-id="{{ r.id }}"
               data-name="{{ r.name }}"
               data-url="{{ r.url }}"
               data-category="{{ r.category }}"
               data-info="{{ (r.info or '') }}"
               style="--catcolor: {{ cc }};">
            <div class="cardhead">
              <div class="linkname">{{ r.name }}</div>
              <div class="actions">
                 <button type="button" class="iconbtn" title="Bewerk" data-edit-btn="1">✏️</button>
                 <button type="button" class="iconbtn" title="Copy URL" data-copy-btn="1" data-copy="{{ r.url }}">📋</button>
                 <form method="post" action="/links/delete/{{ r.id }}" style="display:inline;">
                   <input type="hidden" name="cat" value="{{ active_cat }}">
                   <button type="submit" class="iconbtn" title="Verwijder" onclick="return confirm('Verwijderen?');">🗑️</button>
                 </form>
              </div>
            </div>
            <div><a class="url" href="{{ r.url }}" target="_blank" rel="noopener noreferrer">{{ r.url }}</a></div>
            {% if r.info %}<div class="meta">{{ r.info }}</div>{% else %}<div class="meta"></div>{% endif %}
          </div>
        {% endfor %}
      </div>
    {% else %}
      <p class="hint">Geen links in deze categorie.</p>
    {% endif %}
  </div>

  <!-- PANEL: BEHEER -->
  <div id="panel-manage" class="card" {% if active_tab!='manage' %}style="display:none;"{% endif %}>
    <h2>Beheer</h2>

    <!-- Nieuwe link -->
    <div class="card">
      <h3>Nieuwe link toevoegen</h3>
      <form method="post" action="/links/add">
        <div class="form-row"><div>Naam *</div><div><input class="in" type="text" name="name" required></div></div>
        <div class="form-row"><div>URL *</div><div><input class="in" type="text" name="url" placeholder="https://..." required></div></div>
        <datalist id="catlist">{% for c in all_categories %}<option value="{{ c }}"></option>{% endfor %}</datalist>
        <div class="form-row">
          <div>Categorie</div>
          <div>
            <input class="in" type="text" name="category" list="catlist" placeholder="(leeg = default)">
            <div class="hint">Default: <strong>{{ prefs.default_category }}</strong></div>
          </div>
        </div>
        <div class="form-row"><div>Info</div><div><textarea class="in" name="info" rows="3" placeholder="Extra uitleg (optioneel)"></textarea></div></div>
        <button type="submit" class="iconbtn">➕ Toevoegen</button>
      </form>
    </div>

    <!-- Voorkeuren -->
    <div class="card">
      <h3>Voorkeuren</h3>

      <!-- View toggle -->
      <div style="margin-bottom:10px; display:flex; gap:8px; align-items:center;">
        <form method="post" action="/links/prefs">
          <input type="hidden" name="action" value="set_view_mode">
          <input type="hidden" name="view_mode" value="comfortable">
          <input type="hidden" name="cat" value="{{ active_cat }}">
          <button type="submit" class="iconbtn {% if view_mode=='comfortable' %}active{% endif %}">Comfortabel</button>
        </form>
        <form method="post" action="/links/prefs">
          <input type="hidden" name="action" value="set_view_mode">
          <input type="hidden" name="view_mode" value="compact">
          <input type="hidden" name="cat" value="{{ active_cat }}">
          <button type="submit" class="iconbtn {% if view_mode=='compact' %}active{% endif %}">Compact</button>
        </form>
      </div>

      <!-- Default category -->
      <form method="post" action="/links/prefs">
        <input type="hidden" name="action" value="set_default_category">
        <div class="form-row">
          <div>Default category</div>
          <div>
            <select class="in" name="default_category">
              {% for c in all_categories %}
                <option value="{{ c }}" {% if c == prefs.default_category %}selected{% endif %}>{{ c }}</option>
              {% endfor %}
            </select>
            <button type="submit" class="iconbtn">💾 Opslaan</button>
          </div>
        </div>
      </form>

      <!-- Hide default -->
      <form method="post" action="/links/prefs">
        <input type="hidden" name="action" value="toggle_hide_default">
        <div class="form-row">
          <div>Categorieën</div>
          <div>
            <label style="display:flex; gap:10px; align-items:center; cursor:pointer;">
              <input type="checkbox" name="hide_default_category" value="1" {% if prefs.hide_default_category %}checked{% endif %}>
              <span>Hide default category (“{{ prefs.default_category }}”)</span>
            </label>
            <button type="submit" class="iconbtn">💾 Opslaan</button>
          </div>
        </div>
      </form>
    </div>

    <!-- Grid kolommen (settings.json) -->
    <div class="card">
      <h3>Grid kolommen (settings.json)</h3>
      <p class="hint">Schrijft naar <code>config/settings.json</code> → <code>useful_links.modes.&lt;mode&gt;.max_columns</code></p>
      <form method="post" action="/links/settings/grid">
        <input type="hidden" name="return_tab" value="manage">
        <div class="form-row">
          <div><strong>Comfortabel</strong></div>
          <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
            <input type="range" name="max_columns_comfortable" min="1" max="12" value="{{ max_cols_comfortable }}"
                   oninput="document.getElementById('mc_c').textContent=this.value;">
            <div class="hint"><span id="mc_c">{{ max_cols_comfortable }}</span> kolommen (max)</div>
          </div>
        </div>
        <div class="form-row">
          <div><strong>Compact</strong></div>
          <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
            <input type="range" name="max_columns_compact" min="1" max="12" value="{{ max_cols_compact }}"
                   oninput="document.getElementById('mc_k').textContent=this.value;">
            <div class="hint"><span id="mc_k">{{ max_cols_compact }}</span> kolommen (max)</div>
          </div>
        </div>
        <button type="submit" class="iconbtn">💾 Opslaan in settings.json</button>
      </form>
    </div>

    <!-- Categoriebeheer -->
    <div class="card">
      <h3>Categoriebeheer</h3>
      <p class="hint">Kleur instellen, hernoemen (met live preview), of (indien leeg en niet‑default) verwijderen.</p>
      {% for c in all_categories %}
        <div style="display:flex; align-items:center; gap:12px; margin:8px 0; flex-wrap:wrap;">
          <!-- kleur -->
          <form method="post" action="/links/category/color">
            <input type="hidden" name="category" value="{{ c }}">
            <input type="color" name="color" value="{{ cat_colors.get(c, '#35e6df') }}" title="Kleur">
            <button type="submit" class="iconbtn">💾 Kleur opslaan</button>
          </form>

          <!-- rename -->
          <form method="post" action="/links/category/rename">
            <input type="hidden" name="old_category" value="{{ c }}">
            <label>Nieuwe naam <input class="in" type="text" name="new_category" placeholder="Nieuwe categorienaam"></label>
            <label>Kleur <input type="color" name="color" value="{{ cat_colors.get(c, '#35e6df') }}"></label>
            <label style="display:flex; gap:8px; align-items:center;">
              <input type="checkbox" name="move_links" value="1" checked> Verplaats links
            </label>
            <button type="submit" class="iconbtn">✏️ Hernoem</button>
          </form>

          <!-- delete -->
          <form method="post" action="/links/category/delete">
            <input type="hidden" name="category" value="{{ c }}">
            <button type="submit" class="iconbtn" onclick="return confirm('Categorie verwijderen?');">🗑️ Verwijder (indien leeg)</button>
          </form>

          <div class="hint" style="margin-left:auto;">
            <strong>{{ c }}</strong>
            {% if c == prefs.default_category %}<span class="badge">DEFAULT</span>{% endif %}
          </div>
        </div>
        <hr class="sep">
      {% endfor %}
    </div>
  </div>
</div>

<!-- Modals -->
<div id="edit_modal" class="modal" aria-hidden="true">
  <div class="modalbox" role="dialog" aria-modal="true" aria-label="Link bewerken">
    <h2>Link bewerken</h2>
    <form method="post" action="/links/update">
      <input type="hidden" id="edit_id" name="id">
      <datalist id="catlist2">{% for c in all_categories %}<option value="{{ c }}"></option>{% endfor %}</datalist>
      <div class="form-row"><div>Naam *</div><div><input class="in" id="edit_name" name="name" required></div></div>
      <div class="form-row"><div>URL *</div><div><input class="in" id="edit_url" name="url" required></div></div>
      <div class="form-row">
        <div>Categorie</div>
        <div>
          <input class="in" id="edit_category" name="category" list="catlist2" placeholder="(leeg = default)">
          <div class="hint">Default: <strong>{{ prefs.default_category }}</strong></div>
        </div>
      </div>
      <div class="form-row"><div>Info</div><div><textarea class="in" id="edit_info" name="info" rows="3"></textarea></div></div>
      <div class="modalactions">
        <button type="submit" class="iconbtn">💾 Opslaan</button>
        <button type="button" class="iconbtn" data-close-edit="1">Annuleren</button>
      </div>
    </form>
  </div>
</div>

<div id="rename_modal" class="modal" aria-hidden="true">
  <div class="modalbox" role="dialog" aria-modal="true" aria-label="Categorie hernoemen">
    <div class="rename-preview">
      <div id="rename_preview_bar" class="rename-preview-bar"></div>
      <div class="rename-preview-text">
        <div class="rename-preview-title">
          <span id="rename_preview_name"></span>
          <span id="rename_preview_tag" class="badge" style="display:none;">DEFAULT</span>
        </div>
        <div class="hint">Live preview</div>
      </div>
    </div>
    <h2 style="margin-top:12px;">Categorie hernoemen</h2>
    <form method="post" action="/links/category/rename">
      <input type="hidden" id="rename_old" name="old_category">
      <div class="form-row"><div>Nieuwe naam *</div><div><input class="in" id="rename_new" name="new_category" required></div></div>
      <div class="form-row"><div>Kleur</div><div><input type="color" id="rename_color" name="color" value="#35e6df"></div></div>
      <div class="form-row"><div>Links</div>
        <div>
          <label style="display:flex; gap:10px; align-items:center; cursor:pointer;">
            <input type="checkbox" id="rename_move" name="move_links" value="1" checked>
            <span>Move links van oude categorie naar nieuwe categorie</span>
          </label>
        </div>
      </div>
      <div class="modalactions">
        <button type="submit" class="iconbtn">✅ Hernoem</button>
        <button type="button" class="iconbtn" data-close-rename="1">Annuleren</button>
      </div>
    </form>
  </div>
</div>

<script>
function qs(s){return document.querySelector(s);}
function qsa(s){return Array.from(document.querySelectorAll(s));}
async function copyText(txt){
  try { await navigator.clipboard.writeText(txt); }
  catch(e){
    const ta=document.createElement('textarea'); ta.value=txt;
    document.body.appendChild(ta); ta.select(); document.execCommand('copy');
    document.body.removeChild(ta);
  }
}
function getFocusable(c){
  if(!c) return [];
  const sel=['a[href]','button:not([disabled])','textarea:not([disabled])','input:not([disabled])','select:not([disabled])','[tabindex]:not([tabindex="-1"])'];
  return Array.from(c.querySelectorAll(sel.join(','))).filter(el=>el.offsetParent!==null);
}
function trapTab(c,ev){
  if(ev.key!=='Tab') return;
  const f=getFocusable(c); if(f.length===0) return;
  const first=f[0], last=f[f.length-1];
  if(ev.shiftKey){ if(document.activeElement===first){ ev.preventDefault(); last.focus(); } }
  else{ if(document.activeElement===last){ ev.preventDefault(); first.focus(); } }
}

/* Modal open/close */
function openEditFromCard(card){
  qs('#edit_id').value = card.dataset.id || '';
  qs('#edit_name').value = card.dataset.name || '';
  qs('#edit_url').value = card.dataset.url || '';
  qs('#edit_category').value = card.dataset.category || '';
  qs('#edit_info').value = card.dataset.info || '';
  qs('#edit_modal').classList.add('open');
  setTimeout(()=>qs('#edit_name').focus(),0);
}
function closeEdit(){ qs('#edit_modal').classList.remove('open'); }

function openRename(cat,color,isDefault){
  qs('#rename_old').value = cat;
  qs('#rename_new').value = cat;
  qs('#rename_color').value = color || '#35e6df';
  qs('#rename_move').checked = true;
  updateRenamePreview(cat, qs('#rename_color').value, isDefault);
  qs('#rename_modal').classList.add('open');
  setTimeout(()=>qs('#rename_new').focus(),0);
}
function closeRename(){ qs('#rename_modal').classList.remove('open'); }
function closeAllModals(){ closeEdit(); closeRename(); }

function updateRenamePreview(name, color, isDefault){
  qs('#rename_preview_name').textContent = (name || '').toString();
  qs('#rename_preview_bar').style.background = color || '#35e6df';
  qs('#rename_preview_tag').style.display = isDefault ? 'inline-block' : 'none';
}

/* Keys + focus trap */
function modalKeyHandler(ev){
  const editOpen = qs('#edit_modal').classList.contains('open');
  const renOpen  = qs('#rename_modal').classList.contains('open');
  const anyOpen  = editOpen || renOpen;

  if(ev.key==='Escape' && anyOpen){ ev.preventDefault(); closeAllModals(); return; }
  if((ev.ctrlKey || ev.metaKey) && (ev.key==='w' || ev.key==='W') && anyOpen){ ev.preventDefault(); closeAllModals(); return; }

  if((ev.ctrlKey || ev.metaKey) && (ev.key==='s' || ev.key==='S')){
    const f = editOpen ? qs('#edit_modal form') : (renOpen ? qs('#rename_modal form') : null);
    if(f){ ev.preventDefault(); (f.requestSubmit ? f.requestSubmit() : f.submit()); }
  }
  if((ev.ctrlKey || ev.metaKey) && ev.key==='Enter'){
    const f = editOpen ? qs('#edit_modal form') : (renOpen ? qs('#rename_modal form') : null);
    if(f){ ev.preventDefault(); (f.requestSubmit ? f.requestSubmit() : f.submit()); }
  }

  if(editOpen) trapTab(qs('#edit_modal .modalbox'), ev);
  if(renOpen)  trapTab(qs('#rename_modal .modalbox'), ev);
}

/* Tabs + bindings */
window.addEventListener('load', ()=>{
  const tLinks  = qs('#tab-links');
  const tManage = qs('#tab-manage');
  const show = (panel) => {
    qs('#panel-links').style.display  = panel==='links'  ? 'block' : 'none';
    qs('#panel-manage').style.display = panel==='manage' ? 'block' : 'none';
    tLinks.classList.toggle('active',  panel==='links');
    tManage.classList.toggle('active', panel==='manage');
  };
  if(tLinks)  tLinks.addEventListener('click', ()=>show('links'));
  if(tManage) tManage.addEventListener('click', ()=>show('manage'));
  if((location.hash||'').toLowerCase().includes('manage')) show('manage');

  // kaart acties
  qsa('[data-link-card="1"]').forEach(card=>{
    card.addEventListener('dblclick',(ev)=>{
      const t=ev.target;
      if(t.closest('a') || t.closest('button') || t.closest('form')) return;
      openEditFromCard(card);
    });
    const editBtn = card.querySelector('[data-edit-btn="1"]');
    if(editBtn) editBtn.addEventListener('click',(ev)=>{ ev.preventDefault(); ev.stopPropagation(); openEditFromCard(card); });
    const copyBtn = card.querySelector('[data-copy-btn="1"]');
    if(copyBtn) copyBtn.addEventListener('click', async (ev)=>{
      ev.preventDefault(); ev.stopPropagation();
      const val = copyBtn.dataset.copy || card.dataset.url || '';
      if(val) await copyText(val);
    });
  });

  // modal sluiters
  qsa('[data-close-edit="1"]').forEach(btn=>btn.addEventListener('click', closeEdit));
  qsa('[data-close-rename="1"]').forEach(btn=>btn.addEventListener('click', closeRename));
  qsa('.modal').forEach(m => m.addEventListener('mousedown', (ev)=>{ if(ev.target===m) closeAllModals(); }));
  document.addEventListener('keydown', modalKeyHandler);
});
</script>
"""

# ---------- SETTINGS MERGE + HELPERS + RENDERER ----------
def _merge_settings(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    e = extra.get("useful_links") or {}
    u = out.setdefault("useful_links", {})
    if isinstance(e, dict):
        dm = (e.get("default_mode") or u.get("default_mode") or DEFAULT_VIEW_MODE).strip().lower()
        u["default_mode"] = dm if dm in ("comfortable", "compact") else DEFAULT_VIEW_MODE
        um = u.setdefault("modes", {})
        em = e.get("modes") or {}
        for mode_name in ("comfortable", "compact"):
            dst = um.setdefault(mode_name, {})
            src = em.get(mode_name) or {}
            for key, dv in _default_settings()["useful_links"]["modes"][mode_name].items():
                dst[key] = src.get(key, dst.get(key, dv))
    return out


def _load_settings_live() -> Dict[str, Any]:
    current = _load_json(SETTINGS_PATH, _default_settings())
    return _merge_settings(_default_settings(), current)


def _counts_by_cat(db: Dict[str, Any]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    default_cat = db["prefs"]["default_category"]
    for r in db.get("links", []):
        if not isinstance(r, dict):
            continue
        c = _normalize(r.get("category")) or default_cat
        out[c] = out.get(c, 0) + 1
    return out


def _categories(db: Dict[str, Any], hide_default: bool) -> List[str]:
    """Alle categorieën (uit links + config), alfabetisch; optioneel default verbergen."""
    cats: set[str] = set()
    default_cat = db["prefs"]["default_category"]
    for r in db.get("links", []):
        if isinstance(r, dict):
            cats.add(_normalize(r.get("category")) or default_cat)
    if isinstance(db.get("categories"), dict):
        cats.update(db["categories"].keys())
    out = sorted(cats, key=lambda x: x.lower())
    if hide_default and default_cat in out:
        out.remove(default_cat)
    return out


def _grid_css(settings: Dict[str, Any]) -> str:
    return _grid_css_from_settings(settings)


def _render_page(*, active_tab: str, active_cat: str, error: str = "", msg: str = ""):
    db = load_db()
    prefs = db["prefs"]
    default_cat = prefs["default_category"]
    hide_default = bool(prefs["hide_default_category"])
    view_mode = prefs["view_mode"]

    counts = _counts_by_cat(db)
    categories = _categories(db, hide_default)
    all_categories = _categories(db, False)

    # kleurmap
    cat_colors: Dict[str, str] = {}
    for k, v in (db.get("categories") or {}).items():
        if isinstance(v, dict):
            cat_colors[k] = _hex(v.get("color"), DEFAULT_COLOR)

    # filter & sort
    rows = sorted(db.get("links", []), key=lambda r: (((r.get("category") or "").lower()), ((r.get("name") or "").lower())))
    if active_cat == "__ALL__":
        filtered = rows if not hide_default else [r for r in rows if (r.get("category") or "") != default_cat]
    else:
        filtered = [r for r in rows if (r.get("category") or "") == active_cat]

    st = _load_settings_live()
    grid_css = _grid_css(st)

    html = render_template_string(
        CONTENT_TEMPLATE,
        error=error,
        msg=msg,
        categories=categories,
        all_categories=all_categories,
        counts=counts,
        total=len(rows),
        active_cat=active_cat,
        active_tab=active_tab,
        filtered=filtered,
        prefs=prefs,
        view_mode=view_mode,
        cat_colors=cat_colors,
        grid_css=grid_css,
        max_cols_comfortable=st["useful_links"]["modes"]["comfortable"]["max_columns"],
        max_cols_compact=st["useful_links"]["modes"]["compact"]["max_columns"],
    )
    return hub_render_page(title="Nuttige links", content_html=html)


# ---------- ROUTES (INDEX, CRUD, PREFS, SETTINGS, CATEGORY MGMT) ----------
def _write_grid_settings(comfort_max_cols: int, compact_max_cols: int) -> bool:
    """Schrijf max_columns per mode naar config/settings.json (merge met bestaande waarden)."""
    try:
        current = _load_settings_live()
        ul = current.setdefault("useful_links", {})
        modes = ul.setdefault("modes", {})
        modes.setdefault("comfortable", {})
        modes.setdefault("compact", {})
        # clamp waardes
        cmf = max(1, min(12, int(comfort_max_cols)))
        cmc = max(1, min(12, int(compact_max_cols)))
        modes["comfortable"]["max_columns"] = cmf
        modes["compact"]["max_columns"] = cmc
        return _save_json(SETTINGS_PATH, current)
    except Exception:
        return False


def register_web_routes(app: Flask):
    # ----- Index (tabs/filters)
    @app.get("/links")
    def links_index():
        active_cat = _normalize(request.args.get("cat") or "__ALL__") or "__ALL__"
        active_tab = "manage" if "manage" in (request.args.get("tab") or "").lower() else "links"
        return _render_page(
            active_tab=active_tab,
            active_cat=active_cat,
            error=request.args.get("error", ""),
            msg=request.args.get("msg", "")
        )

    # ----- Links: Create
    @app.post("/links/add")
    def links_add():
        db = load_db()
        name = _normalize(request.form.get("name"))
        url = _normalize(request.form.get("url"))
        info = _normalize(request.form.get("info"))
        cat = _normalize(request.form.get("category"))
        default_cat = db["prefs"]["default_category"]

        if not name or not url:
            return redirect(url_for("links_index", cat="__ALL__", error="Naam en URL zijn verplicht.", tab="manage") + "#manage")

        if not cat:
            cat = default_cat

        db.setdefault("categories", {})
        db["categories"].setdefault(cat, {"color": DEFAULT_COLOR})
        if not isinstance(db["categories"][cat], dict):
            db["categories"][cat] = {"color": DEFAULT_COLOR}

        db["links"].append({
            "id": str(uuid.uuid4()),
            "name": name,
            "url": url,
            "category": cat,
            "info": info,
            "created": _now_iso(),
            "updated": _now_iso(),
        })
        save_db(db)
        return redirect(url_for("links_index", cat=cat, msg="Link toegevoegd!", tab="links") + "#links")

    # ----- Links: Delete
    @app.post("/links/delete/<rid>")
    def links_delete(rid: str):
        db = load_db()
        cat_back = _normalize(request.form.get("cat") or "__ALL__") or "__ALL__"
        before = len(db.get("links", []))
        db["links"] = [r for r in db.get("links", []) if r.get("id") != rid]
        after = len(db["links"])
        save_db(db)
        msg = "Link verwijderd!" if after < before else "Link niet gevonden."
        return redirect(url_for("links_index", cat=cat_back, msg=msg, tab="links") + "#links")

    # ----- Links: Update
    @app.post("/links/update")
    def links_update():
        db = load_db()
        rid = _normalize(request.form.get("id"))
        name = _normalize(request.form.get("name"))
        urlv = _normalize(request.form.get("url"))
        info = _normalize(request.form.get("info"))
        cat = _normalize(request.form.get("category"))
        default_cat = db["prefs"]["default_category"]

        if not rid or not name or not urlv:
            return redirect(url_for("links_index", cat="__ALL__", error="ID, Naam en URL zijn verplicht.", tab="links") + "#links")

        if not cat:
            cat = default_cat

        db["categories"].setdefault(cat, {"color": DEFAULT_COLOR})

        found = False
        for r in db.get("links", []):
            if r.get("id") == rid:
                r["name"] = name
                r["url"] = urlv
                r["category"] = cat
                r["info"] = info
                r["updated"] = _now_iso()
                found = True
                break

        if not found:
            return redirect(url_for("links_index", cat="__ALL__", error="Link niet gevonden.", tab="links") + "#links")

        save_db(db)
        return redirect(url_for("links_index", cat=cat, msg="Link aangepast!", tab="links") + "#links")

    # ----- Preferences
    @app.post("/links/prefs")
    def links_prefs():
        db = load_db()
        action = _normalize(request.form.get("action"))

        # Toggle hide default
        if action == "toggle_hide_default":
            db["prefs"]["hide_default_category"] = bool(request.form.get("hide_default_category"))
            save_db(db)
            return redirect(url_for("links_index", cat="__ALL__", msg="Voorkeuren opgeslagen!", tab="manage") + "#manage")

        # Default category
        if action == "set_default_category":
            new_default = _normalize(request.form.get("default_category"))
            if not new_default:
                return redirect(url_for("links_index", cat="__ALL__", error="Default category is verplicht.", tab="manage") + "#manage")
            db["prefs"]["default_category"] = new_default
            db.setdefault("categories", {})
            db["categories"].setdefault(new_default, {"color": DEFAULT_COLOR})
            if not isinstance(db["categories"][new_default], dict):
                db["categories"][new_default] = {"color": DEFAULT_COLOR}
            db["categories"][new_default].setdefault("color", DEFAULT_COLOR)
            save_db(db)
            return redirect(url_for("links_index", cat="__ALL__", msg="Default category opgeslagen!", tab="manage") + "#manage")

        # View mode switch
        if action == "set_view_mode":
            vm = (_normalize(request.form.get("view_mode")) or "").lower()
            if vm not in ("comfortable", "compact"):
                return redirect(url_for("links_index", cat="__ALL__", error="Onbekende view mode.", tab="links") + "#links")
            db["prefs"]["view_mode"] = vm
            save_db(db)
            cat_back = _normalize(request.form.get("cat") or "__ALL__") or "__ALL__"
            return redirect(url_for("links_index", cat=cat_back, msg="Weergave aangepast!", tab="links") + "#links")

        # Onbekend
        return redirect(url_for("links_index", cat="__ALL__", error="Onbekende actie.", tab="manage") + "#manage")

    # ----- Grid sliders (settings.json)
    @app.post("/links/settings/grid")
    def links_settings_grid():
        try:
            mc_c = int(request.form.get("max_columns_comfortable", "6"))
            mc_k = int(request.form.get("max_columns_compact", "7"))
        except Exception:
            return redirect(url_for("links_index", cat="__ALL__", error="Ongeldige slider waarde.", tab="manage") + "#manage")

        if not _write_grid_settings(mc_c, mc_k):
            return redirect(url_for("links_index", cat="__ALL__", error="Kon settings.json niet schrijven.", tab="manage") + "#manage")

        return redirect(url_for("links_index", cat="__ALL__", msg="Grid-instelling opgeslagen in settings.json!", tab="manage") + "#manage")

    # ----- Category kleur/rename/delete
    @app.post("/links/category/color")
    def links_category_color():
        db = load_db()
        cat = _normalize(request.form.get("category"))
        color = _hex(request.form.get("color"))
        if not cat:
            return redirect(url_for("links_index", cat="__ALL__", error="Geen categorie meegegeven.", tab="manage") + "#manage")
        db.setdefault("categories", {})
        db["categories"].setdefault(cat, {"color": DEFAULT_COLOR})
        if not isinstance(db["categories"][cat], dict):
            db["categories"][cat] = {"color": DEFAULT_COLOR}
        db["categories"][cat]["color"] = color
        save_db(db)
        return redirect(url_for("links_index", cat=cat, msg="Kleur opgeslagen!", tab="manage") + "#manage")

    @app.post("/links/category/rename")
    def links_category_rename():
        db = load_db()
        old_cat = _normalize(request.form.get("old_category"))
        new_cat = _normalize(request.form.get("new_category"))
        color = request.form.get("color")
        move = bool(request.form.get("move_links"))

        if not old_cat:
            return redirect(url_for("links_index", cat="__ALL__", error="Oude categorie ontbreekt.", tab="manage") + "#manage")
        if not new_cat:
            return redirect(url_for("links_index", cat="__ALL__", error="Nieuwe categorie is verplicht.", tab="manage") + "#manage")

        color_val = _hex(color, "")
        db.setdefault("categories", {})
        old_meta = db["categories"].get(old_cat, {"color": DEFAULT_COLOR})
        if not isinstance(old_meta, dict):
            old_meta = {"color": DEFAULT_COLOR}

        db["categories"].setdefault(new_cat, {})
        if not isinstance(db["categories"][new_cat], dict):
            db["categories"][new_cat] = {}
        db["categories"][new_cat].setdefault("color", old_meta.get("color") or DEFAULT_COLOR)
        if color_val:
            db["categories"][new_cat]["color"] = color_val

        if move:
            for r in db.get("links", []):
                if isinstance(r, dict) and (r.get("category") or "") == old_cat:
                    r["category"] = new_cat
                    r["updated"] = _now_iso()

        # default mee verhuizen indien nodig
        if (db.get("prefs", {}).get("default_category") or "") == old_cat:
            db["prefs"]["default_category"] = new_cat

        # oude categorie opruimen als niet meer in gebruik
        if old_cat != new_cat:
            still_in_use = any(
                isinstance(r, dict) and (r.get("category") or "") == old_cat
                for r in db.get("links", [])
            )
            if not still_in_use:
                db["categories"].pop(old_cat, None)

        # verzeker default category bestaat
        default_cat = db["prefs"]["default_category"]
        db["categories"].setdefault(default_cat, {"color": DEFAULT_COLOR})
        if not isinstance(db["categories"][default_cat], dict):
            db["categories"][default_cat] = {"color": DEFAULT_COLOR}
        db["categories"][default_cat].setdefault("color", DEFAULT_COLOR)

        save_db(db)
        return redirect(url_for("links_index", cat="__ALL__", msg="Categorie hernoemd!", tab="manage") + "#manage")

    @app.post("/links/category/delete")
    def links_category_delete():
        db = load_db()
        cat = _normalize(request.form.get("category"))
        if not cat:
            return redirect(url_for("links_index", cat="__ALL__", error="Geen categorie meegegeven.", tab="manage") + "#manage")

        # mag niet bij default of indien nog in gebruik
        if (db.get("prefs", {}).get("default_category") or "") == cat:
            return redirect(url_for("links_index", cat="__ALL__", error="Dit is je default category. Kies eerst een andere default.", tab="manage") + "#manage")

        in_use = any(isinstance(r, dict) and (r.get("category") or "") == cat for r in db.get("links", []))
        if in_use:
            return redirect(url_for("links_index", cat=cat, error="Categorie heeft nog links. Verplaats die eerst.", tab="manage") + "#manage")

        if isinstance(db.get("categories"), dict) and cat in db["categories"]:
            db["categories"].pop(cat, None)
            save_db(db)
            return redirect(url_for("links_index", cat="__ALL__", msg="Categorie verwijderd!", tab="manage") + "#manage")

        return redirect(url_for("links_index", cat="__ALL__", error="Categorie niet gevonden.", tab="manage") + "#manage")


# ---------- BOOTSTRAP / FIRST-RUN HELPERS ----------
def ensure_bootstrap_files() -> None:
    """
    Zorgt dat de noodzakelijke configbestanden bestaan met minimum defaults.
    - config/useful_links.json
    - config/settings.json (alleen de 'useful_links' sectie is relevant)
    """
    if not DATA_PATH.exists():
        _save_json(DATA_PATH, _default_db())
    if not SETTINGS_PATH.exists():
        _save_json(SETTINGS_PATH, _default_settings())


def register_health_routes(app: Flask) -> None:
    """Kleine health-check endpoints om snel te kunnen testen."""
    @app.get("/links/_health")
    def _links_health():
        db = load_db()
        return {
            "ok": True,
            "links": len(db.get("links", [])),
            "categories": len(db.get("categories", {}) or {}),
            "default_category": db.get("prefs", {}).get("default_category"),
        }


# ---------- STANDALONE RUNNER (optioneel) ----------
if __name__ == "__main__":
    app = Flask(__name__)
    ensure_bootstrap_files()
    register_health_routes(app)
    register_web_routes(app)
    # Gebruik 127.0.0.1 en vaste poort zodat je parallel met de Hub kan testen
    app.run("127.0.0.1", 5460, debug=True)
