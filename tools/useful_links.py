
# tools/useful_links.py
# !/usr/bin/env python3
"""
Nuttige links (CyNiT Hub, feature-parity port).
- Route: /links (+ subroutes voor CRUD, prefs, categoriebeheer, grid-settings)
- Opslag: config/useful_links.json  (data)
- Grid-instellingen: config/settings.json (modes.comfortable/compact.max_columns)
- UI/UX:
  * Tabs (Links / Beheer) met sticky topbar
  * Categorieblokken met kleuraccent + counts + "Alle"
  * Cards per link met bewerk-/verwijder-/copy-actie
  * Modals voor link edit en categorie-rename (incl. live preview)
  * ESC sluit modals; Ctrl+Enter en Ctrl+S = opslaan; Ctrl+W = sluiten
  * Focus trap in modals (Tab/Shift+Tab)
  * View mode keuzeknop (comfortable/compact) + opslag in prefs
  * Hide default category toggle
  * Category color set / rename (met optie "move links")
  * Category delete (alleen indien leeg en niet-default)
  * Grid kolom-sliders voor beide modes -> schrijft naar config/settings.json
- Integratie:
  * Geen cynit_theme/ layout; gebruikt beheer.main_layout.render_page()
  * main_layout voegt header/topbar/footer + /static/main.css en /static/main.js toe
"""

from __future__ import annotations

import json
import uuid
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from flask import Flask, request, render_template_string, redirect, url_for

# Hub layout
from beheer.main_layout import render_page as hub_render_page  # type: ignore

# ===== Paden =====
BASE_DIR = Path(__file__).resolve().parents[1]  # CyNiT-Hub/
CONFIG_DIR = BASE_DIR / "config"
DATA_PATH = CONFIG_DIR / "useful_links.json"
SETTINGS_PATH = CONFIG_DIR / "settings.json"    # optioneel; grid-sliders schrijven hiernaar

# ===== Defaults =====
FALLBACK_CATEGORY = "Algemeen"
DEFAULT_COLOR = "#35e6df"  # accentkleur; per categorie overschrijfbaar
DEFAULT_VIEW_MODE = "comfortable"  # of "compact"

# ===== Helpers =====
def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _normalize_cat(name: str) -> str:
    return (name or "").strip()

def _safe_hex(color: str, default: str = DEFAULT_COLOR) -> str:
    c = (color or "").strip()
    return c if (len(c) == 7 and c.startswith("#")) else default

def _default_db() -> Dict[str, Any]:
    return {
        "version": 1,
        "prefs": {
            "default_category": FALLBACK_CATEGORY,
            "hide_default_category": False,
            "view_mode": DEFAULT_VIEW_MODE,
        },
        "categories": {
            FALLBACK_CATEGORY: {"color": DEFAULT_COLOR},
        },
        "links": [],
    }

def _default_settings() -> Dict[str, Any]:
    # Alleen wat we nodig hebben voor de grid, rest laat je main_layout beheren
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

def _merge_settings(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    # shallow-deep merge only for parts we use
    out = dict(base)
    u = out.setdefault("useful_links", {})
    e = (extra.get("useful_links") or {})
    if isinstance(e, dict):
        # default_mode
        dm = (e.get("default_mode") or u.get("default_mode") or DEFAULT_VIEW_MODE).strip().lower()
        u["default_mode"] = dm if dm in ("comfortable", "compact") else DEFAULT_VIEW_MODE
        # modes
        um = u.setdefault("modes", {})
        em = e.get("modes") or {}
        for mode_name in ("comfortable", "compact"):
            src = em.get(mode_name) or {}
            dst = um.setdefault(mode_name, {})
            for key, dv in _default_settings()["useful_links"]["modes"][mode_name].items():
                val = src.get(key, dst.get(key, dv))
                dst[key] = val
    return out

def _load_settings_live() -> Dict[str, Any]:
    # settings.json is optioneel; als hij er niet is, gebruiken we _default_settings()
    current = _load_json(SETTINGS_PATH, _default_settings())
    return _merge_settings(_default_settings(), current)

def _write_grid_settings(comfort_max_cols: int, compact_max_cols: int) -> bool:
    settings = _load_settings_live()
    ul = settings.setdefault("useful_links", {})
    modes = ul.setdefault("modes", {})
    modes.setdefault("comfortable", {})
    modes.setdefault("compact", {})
    modes["comfortable"]["max_columns"] = max(1, min(12, int(comfort_max_cols)))
    modes["compact"]["max_columns"] = max(1, min(12, int(compact_max_cols)))
    return _save_json(SETTINGS_PATH, settings)

def save_db(db: Dict[str, Any]) -> None:
    _save_json(DATA_PATH, db)

def load_db() -> Dict[str, Any]:
    """
    Robuust laden + normaliseren van useful_links.json,
    en defaults toevoegen indien nodig.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    db = _load_json(DATA_PATH, _default_db())
    changed = False

    # Basissecties
    if not isinstance(db.get("links"), list):
        db["links"] = []
        changed = True

    if not isinstance(db.get("categories"), dict):
        db["categories"] = {FALLBACK_CATEGORY: {"color": DEFAULT_COLOR}}
        changed = True

    if not isinstance(db.get("prefs"), dict):
        db["prefs"] = {"default_category": FALLBACK_CATEGORY, "hide_default_category": False, "view_mode": DEFAULT_VIEW_MODE}
        changed = True

    # Versie & prefs defaults
    db.setdefault("version", 1)
    prefs = db["prefs"]
    prefs["default_category"] = _normalize_cat(prefs.get("default_category") or FALLBACK_CATEGORY) or FALLBACK_CATEGORY
    prefs["hide_default_category"] = bool(prefs.get("hide_default_category", False))
    vm = (prefs.get("view_mode") or DEFAULT_VIEW_MODE).strip().lower()
    prefs["view_mode"] = vm if vm in ("comfortable", "compact") else DEFAULT_VIEW_MODE

    if prefs["default_category"] not in db["categories"]:
        db["categories"][prefs["default_category"]] = {"color": DEFAULT_COLOR}
        changed = True

    # Categorie kleuren normaliseren
    for cat, meta in list(db["categories"].items()):
        if not isinstance(meta, dict):
            db["categories"][cat] = {"color": DEFAULT_COLOR}
            changed = True
        else:
            color = _safe_hex(meta.get("color"))
            if meta.get("color") != color:
                meta["color"] = color
                changed = True

    # Links normaliseren
    normalized: List[Dict[str, Any]] = []
    default_cat = prefs["default_category"]
    for row in db["links"]:
        if not isinstance(row, dict):
            changed = True
            continue

        name = (row.get("name") or "").strip()
        url = (row.get("url") or "").strip()
        if not name or not url:
            changed = True
            continue

        row.setdefault("id", str(uuid.uuid4()))
        cat = _normalize_cat(row.get("category") or "") or default_cat
        if row.get("category") != cat:
            row["category"] = cat
            changed = True

        row.setdefault("info", "")
        row.setdefault("created", _now_iso())
        row.setdefault("updated", row.get("created", _now_iso()))

        if cat not in db["categories"]:
            db["categories"][cat] = {"color": DEFAULT_COLOR}
            changed = True

        normalized.append(row)

    if normalized != db["links"]:
        db["links"] = normalized
        changed = True

    if changed:
        save_db(db)
    return db

def _counts_by_cat(db: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    default_cat = (db.get("prefs", {}).get("default_category") or FALLBACK_CATEGORY).strip() or FALLBACK_CATEGORY
    for r in db.get("links", []):
        if not isinstance(r, dict):
            continue
        c = _normalize_cat(r.get("category") or "") or default_cat
        counts[c] = counts.get(c, 0) + 1
    return counts

def _categories(db: Dict[str, Any], hide_default: bool) -> List[str]:
    cats = set()
    default_cat = (db.get("prefs", {}).get("default_category") or FALLBACK_CATEGORY).strip() or FALLBACK_CATEGORY

    for r in db.get("links", []):
        if isinstance(r, dict):
            c = _normalize_cat(r.get("category") or "") or default_cat
            cats.add(c)

    if isinstance(db.get("categories"), dict):
        cats.update(db["categories"].keys())

    out = sorted(cats, key=lambda x: x.lower())
    if hide_default and default_cat in out:
        out.remove(default_cat)
    return out

# ===== Template =====

CONTENT_TEMPLATE = r"""
<style>
/* Compacte stijlen voor deze module; algemene look & feel komt uit main.css */
.links-wrap { max-width: 1100px; margin: 0 auto; }
.card { background: rgba(10,15,18,.85); border:1px solid var(--border, rgba(255,255,255,.10)); border-radius: 12px; padding:16px 20px; margin-bottom: 20px; }
.hint { opacity:.85; font-size:.9em; }
.err { color:#ff4d4d; font-weight:bold; margin: 8px 0 10px 0; }
.ok  { color:#88ff88; font-weight:bold; margin: 8px 0 10px 0; }

/* Tabs + sticky topbar */
.topbar { display:flex; align-items:center; justify-content:space-between; gap:10px; margin: 8px 0 14px 0; }
.sticky-tabs { position: sticky; top: 0; z-index: 50; padding: 8px 0; background: #0b0b0b; border-bottom: 1px solid #222; }
.tabs { display:flex; gap:8px; }
.tabbtn { border:1px solid #333; background:#111; border-radius:0; padding:6px 12px; cursor:pointer; color: var(--text,#e8f2f2); }
.tabbtn.active { background: var(--accent,#35e6df); color:#000; border-color: var(--accent,#35e6df); font-weight: 800; }

/* Categorieblokken */
.catbar { display:flex; flex-wrap:wrap; gap:10px; margin:10px 0 16px 0; }
.catblock { display:flex; flex-direction:column; justify-content:center; gap:2px; width: 160px; min-height:58px; padding:10px 12px;
  border:1px solid #2a2a2a; background:#0b0b0b; text-decoration:none; color: var(--text,#e8f2f2); transition: background .15s, border-color .15s; }
.catblock:hover { background:#101010; }
.catblock:active { transform: translateY(1px); }
.catblock.active { background:#111; border-color:#ffffff55; }
.catname { font-weight:800; line-height:1.05; }
.catcount { opacity:.85; font-size:.9em; }

/* Grid */
.grid { display:grid; margin-bottom: 18px; }
.cardlink { border:1px solid #2a2a2a; border-radius: 0; background:#0b0b0b; display:flex; flex-direction:column; height: 100%; transition: background .15s, border-color .15s; padding:12px 12px; }
.cardlink:hover { background:#101010; border-color: var(--catcolor, rgba(255,255,255,.18)); }
.cardhead { display:flex; justify-content:space-between; align-items:center; gap:8px; margin:0 0 8px 0; padding-bottom:8px; border-bottom:1px solid #222; }
.linkname { font-weight:800; letter-spacing:.2px; color: var(--catcolor, var(--text,#e8f2f2)); }
.actions { display:inline-flex; gap:6px; align-items:center; }
.iconbtn { border:1px solid #333; background:#111; border-radius:0; padding:4px 8px; cursor:pointer; color: var(--text,#e8f2f2); }
.iconbtn:hover { background:#222; }
a.url { word-break: break-all; text-decoration: underline; color: var(--text,#e8f2f2); }
.meta { white-space: pre-wrap; margin-top:auto; opacity:.95; }

/* Inputs */
.form-row { display:grid; grid-template-columns: 160px 1fr; gap:10px; align-items:center; margin:8px 0; }
.in { width:100%; padding:7px 10px; border-radius:0; border:1px solid #333; background:#0b0b0b; color: var(--text,#e8f2f2); box-sizing:border-box; }
textarea.in { min-height: 90px; resize: vertical; }
.selectbox { border:1px solid #333; background:#0b0b0b; color: var(--text,#e8f2f2); border-radius:0; padding:6px 10px; min-width:240px; }
.smallbtn, .btn { border:1px solid #333; background:#111; border-radius:0; padding:6px 10px; cursor:pointer; color: var(--text,#e8f2f2); }
.smallbtn:hover, .btn:hover { background:#222; }
.sep { margin:18px 0; border:0; border-top:1px solid #222; }

/* Grid-mode CSS (uit settings.json) */
{{ grid_css | safe }}

/* Modals */
.modal { position:fixed; inset:0; background: rgba(0,0,0,0.75); display:none; align-items:flex-start; justify-content:center; padding:6vh 12px; z-index:9999; }
.modal.open { display:flex; }
.modalbox { width:min(880px, 100%); background:#0b0b0b; border:1px solid #333; border-radius:0; padding:14px 16px; }
.modalactions { margin-top:12px; display:flex; gap:10px; }
.rename-preview { display:flex; gap:12px; align-items:stretch; border:1px solid #222; background:#0b0b0b; }
.rename-preview-bar { width:10px; background: var(--catcolor, #35e6df); }
.rename-preview-text { padding:10px 12px; flex:1; }
.rename-preview-title { font-weight:800; display:flex; gap:10px; align-items:center; }
.badge { display:inline-block; padding:2px 6px; border:1px solid #333; background:#111; border-radius:0; font-size:.75em; opacity:.9; }
</style>

<div class="links-wrap">
  <h1>Nuttige links</h1>

  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  {% if msg %}<div class="ok">{{ msg }}</div>{% endif %}

  <!-- Sticky topbar met tabs + view toggle -->
  <div class="topbar sticky-tabs">
    <div class="tabs">
      <button id="tab-links" class="tabbtn {% if active_tab=='links' %}active{% endif %}" type="button">Links</button>
      <button id="tab-manage" class="tabbtn {% if active_tab=='manage' %}active{% endif %}" type="button">Beheer</button>
    </div>
    <div class="viewtoggle" role="group" aria-label="Weergave">
      <!-- comfortable -->
      <form method="post" action="/links/prefs" style="display:inline-flex; gap:8px; margin:0;">
        <input type="hidden" name="action" value="set_view_mode">
        <input type="hidden" name="view_mode" value="comfortable">
        <input type="hidden" name="cat" value="{{ active_cat }}">
        <button type="submit" class="smallbtn {% if view_mode=='comfortable' %}active{% endif %}">Comfortabel</button>
      </form>
      <!-- compact -->
      <form method="post" action="/links/prefs" style="display:inline-flex; gap:8px; margin:0;">
        <input type="hidden" name="action" value="set_view_mode">
        <input type="hidden" name="view_mode" value="compact">
        <input type="hidden" name="cat" value="{{ active_cat }}">
        <button type="submit" class="smallbtn {% if view_mode=='compact' %}active{% endif %}">Compact</button>
      </form>
    </div>
  </div>

  <!-- Categorieën -->
  <div class="card">
    <h2>Categorieën</h2>
    <div class="catbar" id="links">
      {% for c in categories %}
        <a class="catblock {% if c == active_cat %}active{% endif %}"
           href="/links?cat={{ c|urlencode }}#links"
           style="border-left:6px solid {{ cat_colors.get(c, '#35e6df') }};">
          <div class="catname">{{ c }}</div>
          <div class="catcount">{{ counts.get(c,0) }} link(s)</div>
        </a>
      {% endfor %}
      <a class="catblock {% if active_cat == '__ALL__' %}active{% endif %}"
         href="/links?cat=__ALL__#links"
         style="border-left:6px solid var(--accent,#35e6df);">
        <div class="catname">Alle</div>
        <div class="catcount">{{ total }} link(s)</div>
      </a>
    </div>
  </div>

  <!-- PANEL: LINKS -->
  <div id="panel-links" style="{% if active_tab!='links' %}display:none;{% endif %}">
    <div class="card">
      <h2>Links</h2>
      {% if filtered %}
        <div class="grid">
          {% for r in filtered %}
          {% set cc = cat_colors.get(r.category, '#35e6df') %}
            <div class="cardlink" data-link-card="1"
                 data-id="{{ r.id|e }}" data-name="{{ r.name|e }}"
                 data-url="{{ r.url|e }}" data-category="{{ r.category|e }}"
                 data-info="{{ (r.info or '')|e }}"
                 style="--catcolor: {{ cc }};">
              <div class="cardhead">
                <div class="linkname">{{ r.name }}</div>
                <div class="actions">
                  <button type="button" class="iconbtn" title="Bewerk" data-edit-btn="1">✏️</button>
                  <button type="button" class="iconbtn" title="Copy URL" data-copy-btn="1" data-copy="{{ r.url|e }}">📋</button>
                  <form method="post" action="/links/delete/{{ r.id }}" style="display:inline-block; margin:0;" onsubmit="return confirm('Verwijderen?');">
                    <input type="hidden" name="cat" value="{{ active_cat }}">
                    <button type="submit" class="iconbtn" title="Verwijder">🗑️</button>
                  </form>
                </div>
              </div>
              <div><a class="url" href="{{ r.url }}" target="_blank" rel="noopener noreferrer">{{ r.url }}</a></div>
              {% if r.info %}<div class="meta">{{ r.info }}</div>{% else %}<div class="meta">&nbsp;</div>{% endif %}
            </div>
          {% endfor %}
        </div>
      {% else %}
        <p class="hint">Geen links in deze categorie.</p>
      {% endif %}
    </div>
  </div>

  <!-- PANEL: BEHEER -->
  <div id="panel-manage" style="{% if active_tab!='manage' %}display:none;{% endif %}">
    <!-- Nieuwe link -->
    <div class="card">
      <h2>Nieuwe link toevoegen</h2>
      <p class="hint">Naam en URL zijn verplicht. Lege categorie = default categorie.</p>
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
        <button type="submit" class="btn">➕ Toevoegen</button>
      </form>
    </div>

    <!-- Voorkeuren -->
    <div class="card">
      <h2>Voorkeuren</h2>

      <!-- Default category -->
      <form method="post" action="/links/prefs" style="display:flex; gap:12px; align-items:center; flex-wrap:wrap;">
        <input type="hidden" name="action" value="set_default_category">
        <label>Default category
          <select class="selectbox" name="default_category">
            {% for c in all_categories %}
              <option value="{{ c }}" {% if c == prefs.default_category %}selected{% endif %}>{{ c }}</option>
            {% endfor %}
          </select>
        </label>
        <button type="submit" class="smallbtn">💾 Opslaan</button>
        <span class="hint">Lege categorie bij toevoegen/edit gaat naar deze default.</span>
      </form>

      <!-- Hide default -->
      <form method="post" action="/links/prefs" style="display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-top:8px;">
        <input type="hidden" name="action" value="toggle_hide_default">
        <label style="display:flex; gap:10px; align-items:center; cursor:pointer;">
          <input type="checkbox" name="hide_default_category" value="1" {% if prefs.hide_default_category %}checked{% endif %}>
          <span>Hide default category (“{{ prefs.default_category }}”)</span>
        </label>
        <button type="submit" class="smallbtn">💾 Opslaan</button>
      </form>
    </div>

    <!-- Grid kolommen -->
    <div class="card">
      <h2>Grid kolommen (settings.json)</h2>
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
        <button type="submit" class="smallbtn">💾 Opslaan in settings.json</button>
      </form>
    </div>

    <!-- Categoriebeheer -->
    <div class="card">
      <h2>Categoriebeheer</h2>
      <p class="hint">Kleur instellen, hernoemen (met live preview), of (indien leeg en niet‑default) verwijderen.</p>

      {% for c in all_categories %}
      <div style="display:flex; align-items:center; gap:12px; margin:8px 0;">
        <!-- kleur -->
        <form method="post" action="/links/category/color" style="display:flex; gap:8px; align-items:center; margin:0;">
          <input type="hidden" name="category" value="{{ c }}">
          <input type="color" name="color" value="{{ cat_colors.get(c, '#35e6df') }}" title="Kleur">
          <button type="submit" class="smallbtn">💾 Kleur opslaan</button>
        </form>

        <!-- rename -->
        <form method="post" action="/links/category/rename" style="display:flex; gap:8px; align-items:center; margin:0;">
          <input type="hidden" name="old_category" value="{{ c }}">
          <label>Nieuwe naam <input class="in" type="text" name="new_category" placeholder="Nieuwe categorienaam"></label>
          <label>Kleur <input type="color" name="color" value="{{ cat_colors.get(c, '#35e6df') }}"></label>
          <label style="display:flex; gap:8px; align-items:center;">
            <input type="checkbox" name="move_links" value="1" checked> Verplaats links
          </label>
          <button type="submit" class="smallbtn">✏️ Hernoem</button>
        </form>

        <!-- delete -->
        <form method="post" action="/links/category/delete" style="display:flex; gap:12px; align-items:center; margin:0;" onsubmit="return confirm('Categorie verwijderen?');">
          <input type="hidden" name="category" value="{{ c }}">
          <button type="submit" class="smallbtn">🗑️ Verwijder (indien leeg)</button>
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
        <button type="submit" class="smallbtn">💾 Opslaan</button>
        <button type="button" class="smallbtn" data-close-edit="1">Annuleren</button>
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
        <button type="submit" class="smallbtn">✅ Hernoem</button>
        <button type="button" class="smallbtn" data-close-rename="1">Annuleren</button>
      </div>
    </form>
  </div>
</div>

<script>
/* ===== Kleine JS helpers (copy, modals, focus trap, shortcuts) ===== */
function qs(sel){return document.querySelector(sel);}
function qsa(sel){return Array.from(document.querySelectorAll(sel));}
async function copyText(txt){
  try { await navigator.clipboard.writeText(txt); }
  catch(e){
    const ta=document.createElement('textarea'); ta.value=txt; document.body.appendChild(ta);
    ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
  }
}
function isVisible(el){ return el && el.style && el.style.display !== 'none' && el.classList.contains('open'); }
function getFocusable(container){
  if(!container) return [];
  const selectors=[
    'a[href]','button:not([disabled])','textarea:not([disabled])',
    'input:not([disabled])','select:not([disabled])','[tabindex]:not([tabindex="-1"])'
  ];
  return Array.from(container.querySelectorAll(selectors.join(','))).filter(el=>el.offsetParent!==null);
}
function trapTab(container, ev){
  if(ev.key !== 'Tab') return;
  const focusables = getFocusable(container);
  if(focusables.length === 0) return;
  const first = focusables[0], last = focusables[focusables.length - 1];
  if(ev.shiftKey){ if(document.activeElement === first){ ev.preventDefault(); last.focus(); } }
  else{ if(document.activeElement === last){ ev.preventDefault(); first.focus(); } }
}
/* Modals open/close */
function openEditFromCard(card){
  qs('#edit_id').value = card.dataset.id || '';
  qs('#edit_name').value = card.dataset.name || '';
  qs('#edit_url').value = card.dataset.url || '';
  qs('#edit_category').value = card.dataset.category || '';
  qs('#edit_info').value = card.dataset.info || '';
  const m = qs('#edit_modal'); m.classList.add('open'); setTimeout(()=>qs('#edit_name').focus(), 0);
}
function closeEdit(){ const m=qs('#edit_modal'); if(m) m.classList.remove('open'); }
function openRename(cat, color, isDefault){
  qs('#rename_old').value = cat;
  qs('#rename_new').value = cat;
  qs('#rename_color').value = color || '#35e6df';
  qs('#rename_move').checked = true;
  updateRenamePreview(cat, qs('#rename_color').value, isDefault);
  const m = qs('#rename_modal'); m.classList.add('open'); setTimeout(()=>qs('#rename_new').focus(),0);
}
function closeRename(){ const m=qs('#rename_modal'); if(m) m.classList.remove('open'); }
function closeAllModals(){ closeEdit(); closeRename(); }

/* Live preview rename */
function updateRenamePreview(name, color, isDefault){
  qs('#rename_preview_name').textContent = (name || '').toString();
  qs('#rename_preview_bar').style.background = color || '#35e6df';
  qs('#rename_preview_tag').style.display = isDefault ? 'inline-block' : 'none';
}

/* Global key handling */
function modalKeyHandler(ev){
  const editOpen = qs('#edit_modal').classList.contains('open');
  const renameOpen = qs('#rename_modal').classList.contains('open');
  const anyOpen = editOpen || renameOpen;

  if(ev.key === 'Escape' && anyOpen){ ev.preventDefault(); closeAllModals(); return; }
  if((ev.ctrlKey || ev.metaKey) && (ev.key === 'w' || ev.key === 'W') && anyOpen){ ev.preventDefault(); closeAllModals(); return; }
  if((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter'){
    if(editOpen){ const f = qs('#edit_modal form'); if(f){ ev.preventDefault(); f.requestSubmit ? f.requestSubmit() : f.submit(); } return; }
    if(renameOpen){ const f = qs('#rename_modal form'); if(f){ ev.preventDefault(); f.requestSubmit ? f.requestSubmit() : f.submit(); } return; }
  }
  if((ev.ctrlKey || ev.metaKey) && (ev.key === 's' || ev.key === 'S')){
    if(editOpen){ const f = qs('#edit_modal form'); if(f){ ev.preventDefault(); f.requestSubmit ? f.requestSubmit() : f.submit(); } return; }
    if(renameOpen){ const f = qs('#rename_modal form'); if(f){ ev.preventDefault(); f.requestSubmit ? f.requestSubmit() : f.submit(); } return; }
  }
  if(ev.key === 'Enter' && anyOpen){
    const tag = (ev.target && ev.target.tagName || '').toLowerCase();
    if(tag !== 'button'){ ev.preventDefault(); return; }
  }
  // focus trap
  if(editOpen) trapTab(qs('#edit_modal .modalbox'), ev);
  else if(renameOpen) trapTab(qs('#rename_modal .modalbox'), ev);
}

/* Bindings */
window.addEventListener('load', ()=>{
  // Tabs
  const tLinks = qs('#tab-links'); const tManage = qs('#tab-manage');
  if(tLinks)  tLinks.addEventListener('click', ()=>{ qs('#panel-links').style.display='block'; qs('#panel-manage').style.display='none'; tLinks.classList.add('active'); tManage.classList.remove('active'); location.hash='#links'; });
  if(tManage) tManage.addEventListener('click', ()=>{ qs('#panel-links').style.display='none'; qs('#panel-manage').style.display='block'; tManage.classList.add('active'); tLinks.classList.remove('active'); location.hash='#manage'; });
  if((location.hash||'').toLowerCase().includes('manage')){ if(tManage) tManage.click(); }

  // Link cards actions
  qsa('[data-link-card="1"]').forEach(card=>{
    card.addEventListener('dblclick',(ev)=>{
      const t = ev.target;
      if(t.closest('a') || t.closest('button') || t.closest('form')) return;
      openEditFromCard(card);
    });
    const editBtn = card.querySelector('[data-edit-btn="1"]');
    if(editBtn) editBtn.addEventListener('click',(ev)=>{ ev.preventDefault(); ev.stopPropagation(); openEditFromCard(card); });
    const copyBtn = card.querySelector('[data-copy-btn="1"]');
    if(copyBtn) copyBtn.addEventListener('click', async (ev)=>{ ev.preventDefault(); ev.stopPropagation(); await copyText(copyBtn.dataset.copy || card.dataset.url || ''); });
  });

  // Modal close buttons & overlay
  qsa('[data-close-edit="1"]').forEach(btn=>btn.addEventListener('click', closeEdit));
  qsa('[data-close-rename="1"]').forEach(btn=>btn.addEventListener('click', closeRename));
  qsa('.modal').forEach(m => m.addEventListener('mousedown', (ev)=>{ if(ev.target === m) closeAllModals(); }));

  // Rename modal live preview
  const rn = qs('#rename_new'); const rc = qs('#rename_color');
  if(rn && rc){
    const recompute = ()=>{
      const oldCat = qs('#rename_old').value || '';
      const isDefault = qs('#rename_preview_tag').style.display !== 'none';
      updateRenamePreview(rn.value || oldCat, rc.value || '#35e6df', isDefault);
    };
    rn.addEventListener('input', recompute);
    rc.addEventListener('input', recompute);
  }

  // Global keys
  document.addEventListener('keydown', modalKeyHandler);
});
</script>
"""

def _grid_css_from_settings(st: Dict[str, Any]) -> str:
    """
    Genereer CSS voor beide modes vanuit settings.json waardes:
    - min_width, gap, card_padding_y/x, breakpoints, max_columns
    """
    u = st.get("useful_links") or {}
    modes = u.get("modes") or {}
    css_parts: List[str] = []
    for mode_name in ("comfortable", "compact"):
        m = modes.get(mode_name) or {}
        minw = int(m.get("min_width", _default_settings()["useful_links"]["modes"][mode_name]["min_width"]))
        gap = int(m.get("gap", _default_settings()["useful_links"]["modes"][mode_name]["gap"]))
        p_y = int(m.get("card_padding_y", _default_settings()["useful_links"]["modes"][mode_name]["card_padding_y"]))
        p_x = int(m.get("card_padding_x", _default_settings()["useful_links"]["modes"][mode_name]["card_padding_x"]))
        bps = m.get("breakpoints", _default_settings()["useful_links"]["modes"][mode_name]["breakpoints"])
        max_cols = int(m.get("max_columns", _default_settings()["useful_links"]["modes"][mode_name]["max_columns"]))

        # basis
        css_parts.append(
            f"""
body.mode-{mode_name} .grid {{
  grid-template-columns: repeat(auto-fill, minmax({minw}px, 1fr));
  gap: {gap}px;
}}
body.mode-{mode_name} .cardlink {{
  padding: {p_y}px {p_x}px;
}}
"""
        )
        # breakpoints
        if isinstance(bps, list):
            for item in bps:
                try:
                    w, cols = int(item[0]), int(item[1])
                    cols_eff = min(cols, max_cols)
                    css_parts.append(
                        f"""
@media (min-width:{w}px){{
  body.mode-{mode_name} .grid{{ grid-template-columns: repeat({cols_eff}, 1fr); }}
}}
"""
                    )
                except Exception:
                    continue
    return "\n".join(css_parts)

def _render_page(
    *,
    active_tab: str,
    active_cat: str,
    error: str = "",
    msg: str = "",
    db: Optional[Dict[str, Any]] = None
):
    db = db or load_db()
    prefs = db.get("prefs", {})
    default_cat = (prefs.get("default_category") or FALLBACK_CATEGORY).strip() or FALLBACK_CATEGORY
    hide_default = bool(prefs.get("hide_default_category", False))
    view_mode = (prefs.get("view_mode") or DEFAULT_VIEW_MODE).strip().lower()
    if view_mode not in ("comfortable", "compact"):
        view_mode = DEFAULT_VIEW_MODE

    counts = _counts_by_cat(db)
    total = len(db.get("links", []))
    categories = _categories(db, hide_default=hide_default)
    all_categories = _categories(db, hide_default=False)

    # Kleurmap
    cat_colors = {}
    if isinstance(db.get("categories"), dict):
        for k, v in db["categories"].items():
            if isinstance(v, dict):
                cat_colors[k] = _safe_hex(v.get("color"))

    # Filter & sort
    rows = db.get("links", [])
    rows = sorted(rows, key=lambda r: (((r.get("category") or "")).lower(), (r.get("name") or "").lower()))
    if active_cat != "__ALL__":
        filtered = [r for r in rows if (r.get("category") or "") == active_cat]
    else:
        filtered = rows if not hide_default else [r for r in rows if (r.get("category") or "") != default_cat]

    # Grid CSS opbouwen vanuit settings
    grid_css = _grid_css_from_settings(_load_settings_live())

    # Body-class view mode doorgeven via main_layout body-classes? We renderen hier content;
    # main_layout zet body classes, dus we injecteren geen extra class—de CSS target 'body.mode-<mode>' wordt hier NIET gebruikt.
    # In deze content-template gebruiken we grid_css met selectors zonder dependency op body-mode toggles.

    content_html = render_template_string(
        CONTENT_TEMPLATE,
        error=error,
        msg=msg,
        categories=categories,
        all_categories=all_categories,
        counts=counts,
        total=total,
        active_cat=active_cat,
        active_tab=active_tab,
        filtered=filtered,
        prefs={"default_category": default_cat, "hide_default_category": hide_default},
        view_mode=view_mode,
        cat_colors=cat_colors,
        grid_css=grid_css,
    )
    # Laat hub layout header/menu/footer + main.css/js toevoegen
    return hub_render_page(title="Nuttige links", content_html=content_html)

# ===== Routes =====
def register_web_routes(app: Flask):
    @app.route("/links", methods=["GET"])
    def links_index():
        active_cat = (request.args.get("cat") or "__ALL__").strip() or "__ALL__"
        active_tab = "manage" if "manage" in ((request.args.get("tab") or "").lower()) else "links"
        if (request.args.get("error") or "") or (request.args.get("msg") or ""):
            # query feedback doorgeven (bij redirects)
            return _render_page(active_tab=active_tab, active_cat=active_cat,
                                error=request.args.get("error", ""), msg=request.args.get("msg", ""))
        return _render_page(active_tab=active_tab, active_cat=active_cat)

    # ---- Links CRUD ----
    @app.route("/links/add", methods=["POST"])
    def links_add():
        db = load_db()
        name = (request.form.get("name") or "").strip()
        url = (request.form.get("url") or "").strip()
        info = (request.form.get("info") or "").strip()
        cat = _normalize_cat(request.form.get("category") or "")
        default_cat = db["prefs"]["default_category"]

        if not name or not url:
            return redirect(url_for("links_index", cat="__ALL__", error="Naam en URL zijn verplicht.") + "#manage")

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

    @app.route("/links/delete/<rid>", methods=["POST"])
    def links_delete(rid: str):
        db = load_db()
        cat_back = (request.form.get("cat") or "__ALL__").strip() or "__ALL__"
        before = len(db.get("links", []))
        db["links"] = [r for r in db.get("links", []) if r.get("id") != rid]
        after = len(db["links"])
        save_db(db)
        msg = "Link verwijderd!" if after < before else "Link niet gevonden."
        return redirect(url_for("links_index", cat=cat_back, msg=msg, tab="links") + "#links")

    @app.route("/links/update", methods=["POST"])
    def links_update():
        db = load_db()
        rid = (request.form.get("id") or "").strip()
        name = (request.form.get("name") or "").strip()
        url_val = (request.form.get("url") or "").strip()
        info = (request.form.get("info") or "").strip()
        cat = _normalize_cat(request.form.get("category") or "")
        default_cat = db["prefs"]["default_category"]

        if not rid or not name or not url_val:
            return redirect(url_for("links_index", cat="__ALL__", error="ID, Naam en URL zijn verplicht.", tab="links") + "#links")
        if not cat:
            cat = default_cat

        db["categories"].setdefault(cat, {"color": DEFAULT_COLOR})
        found = False
        for r in db.get("links", []):
            if r.get("id") == rid:
                r["name"] = name
                r["url"] = url_val
                r["category"] = cat
                r["info"] = info
                r["updated"] = _now_iso()
                found = True
                break

        if not found:
            return redirect(url_for("links_index", cat="__ALL__", error="Link niet gevonden.", tab="links") + "#links")

        save_db(db)
        return redirect(url_for("links_index", cat=cat, msg="Link aangepast!", tab="links") + "#links")

    # ---- Voorkeuren ----
    @app.route("/links/prefs", methods=["POST"])
    def links_prefs():
        db = load_db()
        action = (request.form.get("action") or "").strip()

        if action == "toggle_hide_default":
            hide_default = bool(request.form.get("hide_default_category"))
            db["prefs"]["hide_default_category"] = hide_default
            save_db(db)
            return redirect(url_for("links_index", cat="__ALL__", msg="Voorkeuren opgeslagen!", tab="manage") + "#manage")

        if action == "set_default_category":
            new_default = _normalize_cat(request.form.get("default_category") or "")
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

        if action == "set_view_mode":
            vm = (request.form.get("view_mode") or "").strip().lower()
            if vm not in ("comfortable", "compact"):
                return redirect(url_for("links_index", cat="__ALL__", error="Onbekende view mode.", tab="links") + "#links")
            db["prefs"]["view_mode"] = vm
            save_db(db)
            cat_back = (request.form.get("cat") or "__ALL__").strip() or "__ALL__"
            return redirect(url_for("links_index", cat=cat_back, msg="Weergave aangepast!", tab="links") + "#links")

        return redirect(url_for("links_index", cat="__ALL__", error="Onbekende actie.", tab="manage") + "#manage")

    # ---- Grid sliders (settings.json) ----
    @app.route("/links/settings/grid", methods=["POST"])
    def links_settings_grid():
        try:
            mc_c = int(request.form.get("max_columns_comfortable", "6"))
            mc_k = int(request.form.get("max_columns_compact", "7"))
        except Exception:
            return redirect(url_for("links_index", cat="__ALL__", error="Ongeldige slider waarde.", tab="manage") + "#manage")
        ok = _write_grid_settings(mc_c, mc_k)
        if not ok:
            return redirect(url_for("links_index", cat="__ALL__", error="Kon settings.json niet schrijven.", tab="manage") + "#manage")
        return redirect(url_for("links_index", cat="__ALL__", msg="Grid-instelling opgeslagen in settings.json!", tab="manage") + "#manage")

    # ---- Category color/rename/delete ----
    @app.route("/links/category/color", methods=["POST"])
    def links_category_color():
        db = load_db()
        cat = _normalize_cat(request.form.get("category") or "")
        color = _safe_hex(request.form.get("color") or "")
        if not cat:
            return redirect(url_for("links_index", cat="__ALL__", error="Geen categorie meegegeven.", tab="manage") + "#manage")
        db["categories"].setdefault(cat, {"color": DEFAULT_COLOR})
        if not isinstance(db["categories"][cat], dict):
            db["categories"][cat] = {"color": DEFAULT_COLOR}
        db["categories"][cat]["color"] = color
        save_db(db)
        return redirect(url_for("links_index", cat=cat, msg="Kleur opgeslagen!", tab="manage") + "#manage")

    @app.route("/links/category/rename", methods=["POST"])
    def links_category_rename():
        db = load_db()
        old_cat = _normalize_cat(request.form.get("old_category") or "")
        new_cat = _normalize_cat(request.form.get("new_category") or "")
        color = request.form.get("color") or ""
        move_links = bool(request.form.get("move_links"))

        if not old_cat:
            return redirect(url_for("links_index", cat="__ALL__", error="Oude categorie ontbreekt.", tab="manage") + "#manage")
        if not new_cat:
            return redirect(url_for("links_index", cat="__ALL__", error="Nieuwe categorie is verplicht.", tab="manage") + "#manage")
        color_val = _safe_hex(color, "")

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

        if move_links:
            for r in db.get("links", []):
                if isinstance(r, dict) and (r.get("category") or "") == old_cat:
                    r["category"] = new_cat
                    r["updated"] = _now_iso()

        # default category updaten indien nodig
        if (db.get("prefs", {}).get("default_category") or "") == old_cat:
            db["prefs"]["default_category"] = new_cat

        # oude verwijderen als niet meer in gebruik
        if old_cat != new_cat:
            still_in_use = any(isinstance(r, dict) and (r.get("category") or "") == old_cat for r in db.get("links", []))
            if not still_in_use:
                db["categories"].pop(old_cat, None)

        # verzeker default bestaat
        default_cat = db["prefs"]["default_category"]
        db["categories"].setdefault(default_cat, {"color": DEFAULT_COLOR})
        if not isinstance(db["categories"][default_cat], dict):
            db["categories"][default_cat] = {"color": DEFAULT_COLOR}
        db["categories"][default_cat].setdefault("color", DEFAULT_COLOR)

        save_db(db)
        return redirect(url_for("links_index", cat="__ALL__", msg="Categorie hernoemd!", tab="manage") + "#manage")

    @app.route("/links/category/delete", methods=["POST"])
    def links_category_delete():
        db = load_db()
        cat = _normalize_cat(request.form.get("category") or "")
        if not cat:
            return redirect(url_for("links_index", cat="__ALL__", error="Geen categorie meegegeven.", tab="manage") + "#manage")

        # niet verwijderen als in gebruik of als default
        in_use = any(isinstance(r, dict) and (r.get("category") or "") == cat for r in db.get("links", []))
        if in_use:
            return redirect(url_for("links_index", cat=cat, error="Categorie heeft nog links. Verplaats die eerst.", tab="manage") + "#manage")

        if (db.get("prefs", {}).get("default_category") or "") == cat:
            return redirect(url_for("links_index", cat="__ALL__", error="Dit is je default category. Kies eerst een andere default.", tab="manage") + "#manage")

        if isinstance(db.get("categories"), dict) and cat in db["categories"]:
            db["categories"].pop(cat, None)
            save_db(db)
            return redirect(url_for("links_index", cat="__ALL__", msg="Categorie verwijderd!", tab="manage") + "#manage")

        return redirect(url_for("links_index", cat="__ALL__", error="Categorie niet gevonden.", tab="manage") + "#manage")

# Standalone test
if __name__ == "__main__":
    app = Flask(__name__)
    register_web_routes(app)
    app.run("127.0.0.1", 5460, debug=True)
