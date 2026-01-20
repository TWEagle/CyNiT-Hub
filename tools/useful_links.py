
# tools/useful_links.py
# -*- coding: utf-8 -*-
"""
Useful Links (Hub) — versie zonder settings.json
- Import/Export voor useful_links.json (merge/replace, dedup, backup)
- Cards/Lijst weergave
- Inline edits (naam/URL/categorie/info) zonder reload
- Drag & drop reorder per categorie (persist)
- Categoriebeheer (kleur/hernoem/delete)
- Voorkeuren in useful_links.json (view_mode, links_layout, default_category, hide_default_category)
- Geen afhankelijkheid van settings.json (grid gebruikt vaste defaults)
- Debug/health endpoints
- Hybride: werkt in Hub én standalone (fallback layout wanneer beheer.main_layout ontbreekt)
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from flask import Flask, request, render_template_string, redirect, url_for, jsonify, Response

# --- Hub layout (optioneel, met fallback voor standalone) ---
try:
    from beheer.main_layout import render_page as hub_render_page  # type: ignore
except Exception:
    hub_render_page = None  # fallback gebruiken

def _render_layout(title: str, content_html: str) -> str:
    """
    Gebruik de Hub-layout wanneer beschikbaar; anders een compacte, donkere fallback (standalone).
    """
    if hub_render_page is not None:
        try:
            return hub_render_page(title=title, content_html=content_html)
        except Exception:
            pass  # val terug op fallback
    # Minimal fallback layout (zwarte achtergrond, witte tekst, panel/in/btn)
    return (
        "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
        f"<title>{title}</title>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<style>"
        "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:2rem;background:#000;color:#e8f2f2}"
        ".card{background:rgba(10,15,18,.85);border:1px solid rgba(255,255,255,.10);border-radius:12px;padding:16px 20px;margin-bottom:18px}"
        ".in{width:100%;padding:7px 10px;border:1px solid #333;background:#0b0b0b;color:#e8f2f2;border-radius:8px}"
        ".iconbtn,.tabbtn{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:10px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.06);color:#fff;cursor:pointer;text-decoration:none}"
        ".iconbtn:hover,.tabbtn:hover{background:rgba(255,255,255,.10)}"
        ".tabbtn.active{background:rgba(255,255,255,.14)}"
        ".links-wrap{max-width:1100px;margin:0 auto}"
        ".ok{color:#88ff88;font-weight:bold;margin:8px 0 10px 0}"
        ".err{color:#ff4d4d;font-weight:bold;margin:8px 0 10px 0}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;margin-bottom:18px}"
        ".cardlink{padding:10px 12px;border:1px solid rgba(255,255,255,.12);border-radius:10px;background:#0b0b0b}"
        ".cardhead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px}"
        ".badge{display:inline-block;padding:2px 8px;border-radius:999px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12)}"
        ".hidden{display:none}"
        "table.links-list{width:100%;border-collapse:collapse}"
        "table.links-list th,table.links-list td{border-bottom:1px solid rgba(255,255,255,.10);padding:8px 8px;text-align:left}"
        "a{color:#35e6df;text-decoration:none}a:hover{text-decoration:underline}"
        "</style></head><body>"
        + content_html +
        "</body></html>"
    )

# ---------- Paden ----------
BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = BASE_DIR / "config"
DATA_PATH = CONFIG_DIR / "useful_links.json"

# ---------- Defaults ----------
FALLBACK_CATEGORY = "Algemeen"
DEFAULT_COLOR = "#35e6df"
DEFAULT_VIEW_MODE = "comfortable"  # of "compact"
DEFAULT_LAYOUT = "cards"           # of "list"

# ---------- Helpers ----------
def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _normalize(s: str | None) -> str:
    return (s or "").strip()

def _hex(s: str | None, default: str = DEFAULT_COLOR) -> str:
    s = (s or "").strip()
    return s if len(s) == 7 and s.startswith("#") else default

def _default_db() -> Dict[str, Any]:
    return {
        "version": 2,
        "prefs": {
            "default_category": FALLBACK_CATEGORY,
            "hide_default_category": False,
            "view_mode": DEFAULT_VIEW_MODE,
            "links_layout": DEFAULT_LAYOUT,
        },
        "categories": {FALLBACK_CATEGORY: {"color": DEFAULT_COLOR}},
        "links": [],
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
    """Laadt/normaliseert useful_links.json en vult ontbrekende defaults/order aan."""
    db = _load_json(DATA_PATH, _default_db())
    changed = False

    if not isinstance(db.get("links"), list):
        db["links"] = []
        changed = True
    if not isinstance(db.get("categories"), dict):
        db["categories"] = {FALLBACK_CATEGORY: {"color": DEFAULT_COLOR}}
        changed = True
    if not isinstance(db.get("prefs"), dict):
        db["prefs"] = _default_db()["prefs"]
        changed = True

    # prefs
    prefs = db["prefs"]
    prefs["default_category"] = _normalize(prefs.get("default_category")) or FALLBACK_CATEGORY
    prefs["hide_default_category"] = bool(prefs.get("hide_default_category", False))
    vm = _normalize(prefs.get("view_mode")) or DEFAULT_VIEW_MODE
    prefs["view_mode"] = vm if vm in ("comfortable", "compact") else DEFAULT_VIEW_MODE
    layout = _normalize(prefs.get("links_layout")) or DEFAULT_LAYOUT
    prefs["links_layout"] = layout if layout in ("cards", "list") else DEFAULT_LAYOUT
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

    # links normaliseren (incl. order per categorie)
    per_cat_counter: Dict[str, int] = {}
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
        r["category"] = cat
        r.setdefault("info", "")
        r.setdefault("created", _now_iso())
        r.setdefault("updated", r.get("created", _now_iso()))
        if "order" not in r or not isinstance(r.get("order"), int):
            per_cat_counter[cat] = per_cat_counter.get(cat, 0) + 1
            r["order"] = per_cat_counter[cat]
            changed = True
        else:
            per_cat_counter[cat] = max(per_cat_counter.get(cat, 0), int(r["order"]))
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

# ---------- Import/Export helpers ----------
def _backup_file(path: Path) -> Path:
    """Maak een timestamped backup van een JSON-bestand."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = CONFIG_DIR / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    bpath = bdir / f"{path.stem}_{ts}.json"
    try:
        if path.exists():
            bpath.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        pass
    return bpath

def _normalize_incoming_db(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliseer een ingelezen JSON naar v2‑vorm (zonder side effects op disk).
    - vult defaults
    - migreert v1 (bv. hide_general) → v2
    - valideert kleuren en verplichte velden
    """
    data = raw if isinstance(raw, dict) else {}
    out = {
        "version": 2,
        "links": [],
        "categories": {},
        "prefs": {
            "default_category": FALLBACK_CATEGORY,
            "hide_default_category": False,
            "view_mode": DEFAULT_VIEW_MODE,
            "links_layout": DEFAULT_LAYOUT,
        },
    }

    # prefs
    prefs = data.get("prefs") or {}
    if isinstance(prefs, dict):
        dc = _normalize(prefs.get("default_category")) or FALLBACK_CATEGORY
        out["prefs"]["default_category"] = dc
        out["prefs"]["hide_default_category"] = bool(
            prefs.get("hide_default_category", prefs.get("hide_general", False))
        )
        vm = (_normalize(prefs.get("view_mode")) or DEFAULT_VIEW_MODE).lower()
        out["prefs"]["view_mode"] = vm if vm in ("comfortable", "compact") else DEFAULT_VIEW_MODE
        ll = (_normalize(prefs.get("links_layout")) or DEFAULT_LAYOUT).lower()
        out["prefs"]["links_layout"] = ll if ll in ("cards", "list") else DEFAULT_LAYOUT

    # categories
    cats = data.get("categories") or {}
    if isinstance(cats, dict):
        for k, meta in cats.items():
            if not isinstance(meta, dict):
                out["categories"][k] = {"color": DEFAULT_COLOR}
            else:
                out["categories"][k] = {"color": _hex(meta.get("color"), DEFAULT_COLOR)}

    # links
    links = data.get("links") or []
    if isinstance(links, list):
        per_cat_counter: Dict[str, int] = {}
        for r in links:
            if not isinstance(r, dict):
                continue
            name = _normalize(r.get("name"))
            url = _normalize(r.get("url"))
            if not name or not url:
                continue
            rid = _normalize(r.get("id")) or str(uuid.uuid4())
            cat = _normalize(r.get("category")) or out["prefs"]["default_category"]
            info = _normalize(r.get("info"))
            try:
                order = int(r.get("order", 0))
            except Exception:
                order = 0
            if order <= 0:
                per_cat_counter[cat] = per_cat_counter.get(cat, 0) + 1
                order = per_cat_counter[cat]
            out["links"].append({
                "id": rid,
                "name": name,
                "url": url,
                "category": cat,
                "info": info,
                "order": order,
                "created": _normalize(r.get("created")) or _now_iso(),
                "updated": _normalize(r.get("updated")) or _now_iso(),
            })
            out["categories"].setdefault(cat, {"color": DEFAULT_COLOR})
    dc = out["prefs"]["default_category"]
    out["categories"].setdefault(dc, {"color": DEFAULT_COLOR})
    return out

def _merge_useful_links(current: Dict[str, Any],
                        incoming: Dict[str, Any],
                        *, mode: str = "merge",
                        dedup: str = "by_id") -> Dict[str, Any]:
    """
    Merge of vervang DB's.
    mode: 'merge' (default) of 'replace'
    dedup: 'by_id' of 'by_name_url'
    """
    cur = _normalize_incoming_db(current)
    inc = _normalize_incoming_db(incoming)
    if mode == "replace":
        return _normalize_incoming_db(inc)

    # MERGE
    # categories
    for c, meta in (inc.get("categories") or {}).items():
        if not isinstance(meta, dict):
            continue
        if c not in cur["categories"]:
            cur["categories"][c] = {"color": _hex(meta.get("color"), DEFAULT_COLOR)}
        else:
            if meta.get("color"):
                cur["categories"][c]["color"] = _hex(meta.get("color"), cur["categories"][c]["color"])
    # links
    existing_ids = {r.get("id") for r in cur.get("links", []) if isinstance(r, dict)}
    existing_key = set()
    if dedup == "by_name_url":
        for r in cur.get("links", []):
            if isinstance(r, dict):
                existing_key.add((r.get("name"), r.get("url")))
    per_cat_max: Dict[str, int] = {}
    for r in cur.get("links", []):
        if isinstance(r, dict):
            cat = r.get("category") or cur["prefs"]["default_category"]
            try:
                per_cat_max[cat] = max(per_cat_max.get(cat, 0), int(r.get("order", 0)))
            except Exception:
                pass
    for r in inc.get("links", []):
        if not isinstance(r, dict):
            continue
        rid = r.get("id") or str(uuid.uuid4())
        key = (r.get("name"), r.get("url"))
        if dedup == "by_id":
            if rid in existing_ids:
                continue
        else:
            if key in existing_key:
                continue
        cat = r.get("category") or cur["prefs"]["default_category"]
        per_cat_max[cat] = per_cat_max.get(cat, 0) + 1
        row = {
            "id": rid if dedup == "by_id" else str(uuid.uuid4()),
            "name": r.get("name"),
            "url": r.get("url"),
            "category": cat,
            "info": r.get("info") or "",
            "order": per_cat_max[cat],
            "created": r.get("created") or _now_iso(),
            "updated": _now_iso(),
        }
        cur["links"].append(row)
        cur["categories"].setdefault(cat, {"color": DEFAULT_COLOR})
        existing_ids.add(row["id"])
        existing_key.add((row["name"], row["url"]))
    dc = cur["prefs"]["default_category"]
    cur["categories"].setdefault(dc, {"color": DEFAULT_COLOR})
    return cur

# ---------- Grid CSS (vaste defaults, geen settings.json) ----------
DEFAULT_MODES = {
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
}

def _grid_css_from_modes(modes: Dict[str, Any]) -> str:
    css_parts: List[str] = []
    for mode_name in ("comfortable", "compact"):
        m = modes.get(mode_name, {})
        minw = int(m.get("min_width", 280 if mode_name == "comfortable" else 240))
        gap = int(m.get("gap", 14 if mode_name == "comfortable" else 10))
        py = int(m.get("card_padding_y", 10 if mode_name == "comfortable" else 8))
        px = int(m.get("card_padding_x", 12 if mode_name == "comfortable" else 10))
        bps = m.get("breakpoints", [])
        maxc = int(m.get("max_columns", 6 if mode_name == "comfortable" else 7))
        scope = f".links-wrap.mode-{mode_name}"
        css_parts.append(f"""
/* {mode_name} basis */
{scope} .grid {{
  display:grid;
  grid-template-columns: repeat(auto-fill, minmax({minw}px, 1fr)) !important;
  gap:{gap}px;
}}
{scope} .cardlink {{
  padding:{py}px {px}px;
}}
""")
        last_width = 0
        for bp in sorted(bps, key=lambda x: int(x[0])):
            try:
                w, cols = int(bp[0]), int(bp[1])
                cols = min(cols, maxc)
                if cols > 0:
                    css_parts.append(f"""
@media (min-width:{w}px) {{
  {scope} .grid {{ grid-template-columns: repeat({cols}, 1fr) !important; }}
}}
""")
                last_width = w
            except Exception:
                continue
        cap_from = (last_width or 1600)
        css_parts.append(f"""
@media (min-width:{cap_from}px) {{
  {scope} .grid {{ grid-template-columns: repeat({maxc}, 1fr) !important; }}
}}
""")
    return "\n".join(css_parts)

# ---------- HTML-template ----------
CONTENT_TEMPLATE = r"""
<! -- CSS: eerst main.css (globaal), dan useful_links.css (override), met cache-buster -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/main.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/useful_links.css') }}?v={{ css_version }}">
<style id="gridStatic">
/* Grid CSS vanuit vaste defaults (scoped per mode) */
{{ grid_css | safe }}
/* Page layout */
.links-wrap { max-width: 1100px; margin: 0 auto; }
.grid { margin-bottom:18px; }
/* Modals */
.modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.6); z-index:1000; }
.modal.open { display:flex; align-items:center; justify-content:center; }
.modalbox { background:#0b0b0b; border:1px solid #2a2a2a; border-radius:12px; padding:16px 20px; width:min(680px, 96vw); }
.sep { border:0; border-top:1px solid #222; }
/* Forms */
.form-row { display:grid; grid-template-columns:160px 1fr; gap:10px; margin:8px 0; }
.in { width:100%; padding:7px 10px; border:1px solid #333; background:#0b0b0b; color:#e8f2f2; }
/* Status */
.err { color:#ff4d4d; font-weight:bold; margin:8px 0 10px 0; }
.ok { color:#88ff88; font-weight:bold; margin:8px 0 10px 0; }
</style>

<div class="links-wrap mode-{{ view_mode }}">
  <h1>Nuttige links</h1>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  {% if msg %}<div class="ok">{{ msg }}</div>{% endif %}

  <div class="topbar" style="display:flex; justify-content:space-between; gap:12px; align-items:center; margin-bottom:14px;">
    <div class="tabs" style="display:flex; gap:8px;">
      <button id="tab-links" class="tabbtn {% if active_tab=='links' %}active{% endif %}">Links</button>
      <button id="tab-manage" class="tabbtn {% if active_tab=='manage' %}active{% endif %}">Beheer</button>
    </div>
    <!-- Quick layout toggle -->
    <div style="display:flex; gap:6px;">
      <form action="{{ url_for('links_prefs') }}" method="post">
        <input type="hidden" name="action" value="set_links_layout">
        <input type="hidden" name="links_layout" value="cards">
        <input type="hidden" name="cat" value="{{ active_cat }}">
        <button type="submit" class="tabbtn {% if links_layout=='cards' %}active{% endif %}">Cards</button>
      </form>
      <form action="{{ url_for('links_prefs') }}" method="post">
        <input type="hidden" name="action" value="set_links_layout">
        <input type="hidden" name="links_layout" value="list">
        <input type="hidden" name="cat" value="{{ active_cat }}">
        <button type="submit" class="tabbtn {% if links_layout=='list' %}active{% endif %}">Lijst</button>
      </form>
    </div>
  </div>

  <div class="card">
    <h2>Categorieën</h2>
    <div class="catbar">
      {% for c in categories %}
      {% set ccol = cat_colors.get(c, '#35e6df') %}
      <a class="catblock {% if active_cat==c %}active{% endif %}" href="{{ url_for('links_index') }}?cat={{ c | urlencode }}"
         style="--catcolor: {{ ccol }};">
        <div class="catname">{{ c }}</div>
        <div class="catcount">{{ counts.get(c,0) }} link(s)</div>
      </a>
      {% endfor %}
      <a class="catblock {% if active_cat=='__ALL__' %}active{% endif %}" href="{{ url_for('links_index') }}?cat=__ALL__"
         style="--catcolor: #35e6df;">
        <div class="catname">Alle</div>
        <div class="catcount">{{ total }} link(s)</div>
      </a>
    </div>
  </div>

  <!-- PANEL: LINKS -->
  <div id="panel-links" class="card" {% if active_tab!='links' %}style="display:none;"{% endif %}>
    <h2>Links</h2>
    {% if links_layout == 'cards' %}
      {% if filtered %}
      <div class="grid" id="cardsGrid">
        {% for r in filtered %}
        {% set cc = cat_colors.get(r.category, '#35e6df') %}
        <div class="cardlink"
             draggable="true"
             data-id="{{ r.id }}"
             style="--catcolor: {{ cc }};">
          <div class="cardhead">
            <div class="linkname" data-editable="name" contenteditable="false">{{ r.name }}</div>
            <div class="actions">
              <button type="button" class="iconbtn" title="Bewerk inline" data-inline-edit="1">✏️</button>
              <button type="button" class="iconbtn" title="Opslaan" data-inline-save="1" style="display:none;">💾</button>
              <button type="button" class="iconbtn" title="Annuleer" data-inline-cancel="1" style="display:none;">↩</button>
              <button type="button" class="iconbtn" title="Copy URL" data-copy-btn="1" data-copy="{{ r.url }}">📋</button>
              <span class="drag-handle" title="Sleep om te verplaatsen">⠿</span>
              <form action="{{ url_for('links_delete', rid=r.id) }}" method="post" style="display:inline;">
                <input type="hidden" name="cat" value="{{ active_cat }}">
                <button type="submit" class="iconbtn" title="Verwijder" onclick="return confirm('Verwijderen?');">🗑️</button>
              </form>
            </div>
          </div>
          <div>
            <a class="url" href="{{ r.url }}" target="_blank" rel="noopener">{{ r.url }}</a>
            <div class="inline-edit-url" data-editable="url" contenteditable="false" style="display:none;">{{ r.url }}</div>
          </div>
          <div class="meta" data-editable="info" contenteditable="false">{{ r.info }}</div>
          <div class="hint" style="margin-top:6px;">Categorie:
            <span class="badge">{{ r.category }}</span>
            <span class="cat-inline" data-editable="category" contenteditable="false" style="display:none;">{{ r.category }}</span>
          </div>
        </div>
        {% endfor %}
      </div>
      {% else %}
        <p class="hint">Geen links in deze categorie.</p>
      {% endif %}
    {% else %}
      {% if filtered %}
      <div class="listwrap">
        <table class="links-list">
          <thead>
            <tr>
              <th style="width:32px;"></th>
              <th>Naam</th>
              <th>URL</th>
              <th>Categorie</th>
              <th>Info</th>
              <th style="width:180px;">Acties</th>
            </tr>
          </thead>
          <tbody id="links_tbody">
            {% for r in filtered %}
            <tr draggable="true" data-id="{{ r.id }}">
              <td class="drag-cell"><span class="drag-handle" title="Sleep om te verplaatsen">⠿</span></td>
              <td data-editable="name" contenteditable="false">{{ r.name }}</td>
              <td>
                <a class="url" href="{{ r.url }}" target="_blank" rel="noopener">{{ r.url }}</a>
                <div class="inline-edit-url" data-editable="url" contenteditable="false" style="display:none;">{{ r.url }}</div>
              </td>
              <td data-editable="category" contenteditable="false">{{ r.category }}</td>
              <td data-editable="info" contenteditable="false">{{ r.info }}</td>
              <td class="actions">
                <button type="button" class="iconbtn" title="Bewerk inline" data-inline-edit="1">✏️</button>
                <button type="button" class="iconbtn" title="Opslaan" data-inline-save="1" style="display:none;">💾</button>
                <button type="button" class="iconbtn" title="Annuleer" data-inline-cancel="1" style="display:none;">↩</button>
                <form action="{{ url_for('links_delete', rid=r.id) }}" method="post" style="display:inline;">
                  <input type="hidden" name="cat" value="{{ active_cat }}">
                  <button type="submit" class="iconbtn" title="Verwijder" onclick="return confirm('Verwijderen?');">🗑️</button>
                </form>
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% else %}
        <p class="hint">Geen links in deze categorie.</p>
      {% endif %}
    {% endif %}
  </div>

  <!-- PANEL: BEHEER -->
  <div id="panel-manage" class="card" {% if active_tab!='manage' %}style="display:none;"{% endif %}>
    <h2>Beheer</h2>

    <!-- Nieuwe link -->
    <div class="card">
      <h3>Nieuwe link toevoegen</h3>
      <form action="{{ url_for('links_add') }}" method="post">
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
      <div style="margin-bottom:10px; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
        <!-- View mode -->
        <form action="{{ url_for('links_prefs') }}" method="post">
          <input type="hidden" name="action" value="set_view_mode">
          <input type="hidden" name="view_mode" value="comfortable">
          <input type="hidden" name="cat" value="{{ active_cat }}">
          <button type="submit" class="tabbtn {% if view_mode=='comfortable' %}active{% endif %}">Comfortabel</button>
        </form>
        <form action="{{ url_for('links_prefs') }}" method="post">
          <input type="hidden" name="action" value="set_view_mode">
          <input type="hidden" name="view_mode" value="compact">
          <input type="hidden" name="cat" value="{{ active_cat }}">
          <button type="submit" class="tabbtn {% if view_mode=='compact' %}active{% endif %}">Compact</button>
        </form>
        <!-- Layout -->
        <form action="{{ url_for('links_prefs') }}" method="post">
          <input type="hidden" name="action" value="set_links_layout">
          <input type="hidden" name="links_layout" value="cards">
          <input type="hidden" name="cat" value="{{ active_cat }}">
          <button type="submit" class="tabbtn {% if links_layout=='cards' %}active{% endif %}">Cards</button>
        </form>
        <form action="{{ url_for('links_prefs') }}" method="post">
          <input type="hidden" name="action" value="set_links_layout">
          <input type="hidden" name="links_layout" value="list">
          <input type="hidden" name="cat" value="{{ active_cat }}">
          <button type="submit" class="tabbtn {% if links_layout=='list' %}active{% endif %}">Lijst</button>
        </form>
      </div>

      <!-- Default category -->
      <form action="{{ url_for('links_prefs') }}" method="post">
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
      <form action="{{ url_for('links_prefs') }}" method="post">
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

    <!-- Import / Export -->
    <div class="card">
      <h3>Import / Export</h3>
      <p class="hint">
        Exporteer de huidige database of importeer een JSON (merge of replace). Bij import kan je deduplicatie kiezen en optioneel eerst een backup laten maken.
      </p>
      <div style="display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin-bottom:10px;">
        <a class="iconbtn" href="{{ url_for('links_export') }}">⬇️ Exporteren (JSON)</a>
        <a class="iconbtn" href="{{ url_for('links_export', pretty=1) }}">⬇️ Exporteren (pretty)</a>
      </div>
      <form action="{{ url_for('links_import') }}" method="post" enctype="multipart/form-data">
        <div class="form-row">
          <div>Bestand</div>
          <div><input class="in" type="file" name="file" accept=".json,application/json" required></div>
        </div>
        <div class="form-row">
          <div>Mode</div>
          <div>
            <label style="margin-right:12px;">
              <input type="radio" name="mode" value="merge" checked> Merge (voeg toe, behoud bestaande)
            </label>
            <label>
              <input type="radio" name="mode" value="replace"> Replace (volledig vervangen)
            </label>
          </div>
        </div>
        <div class="form-row">
          <div>Dedup (bij merge)</div>
          <div>
            <select class="in" name="dedup">
              <option value="by_id" selected>by_id (zelfde id → overslaan)</option>
              <option value="by_name_url">by_name_url (zelfde naam+URL → overslaan)</option>
            </select>
          </div>
        </div>
        <div class="form-row">
          <div>Backup</div>
          <div>
            <label style="display:flex; gap:10px; align-items:center; cursor:pointer;">
              <input type="checkbox" name="backup" value="1" checked> Maak eerst een backup in <code>config/backups/</code>
            </label>
          </div>
        </div>
        <div>
          <button type="submit" class="iconbtn">⬆️ Importeren</button>
        </div>
      </form>
    </div>

    <!-- Categoriebeheer -->
    <div class="card">
      <h3>Categoriebeheer</h3>
      <p class="hint">Kleur instellen, hernoemen (met live preview), of (indien leeg en niet‑default) verwijderen.</p>
      {% for c in all_categories %}
      <div style="display:flex; align-items:center; gap:12px; margin:8px 0; flex-wrap:wrap;">
        <form action="{{ url_for('links_category_color') }}" method="post">
          <input type="hidden" name="category" value="{{ c }}">
          <input type="color" name="color" value="{{ cat_colors.get(c, '#35e6df') }}" title="Kleur">
          <button type="submit" class="iconbtn">💾 Kleur opslaan</button>
        </form>
        <form action="{{ url_for('links_category_rename') }}" method="post">
          <input type="hidden" name="old_category" value="{{ c }}">
          <label>Nieuwe naam <input class="in" type="text" name="new_category" placeholder="Nieuwe categorienaam"></label>
          <label>Kleur <input type="color" name="color" value="{{ cat_colors.get(c, '#35e6df') }}"></label>
          <label style="display:flex; gap:8px; align-items:center;">
            <input type="checkbox" name="move_links" value="1" checked> Verplaats links
          </label>
          <button type="submit" class="iconbtn">✏️ Hernoem</button>
        </form>
        <form action="{{ url_for('links_category_delete') }}" method="post">
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
    <form action="{{ url_for('links_update') }}" method="post">
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
      <div class="modalactions" style="display:flex; gap:8px;">
        <button type="submit" class="iconbtn">💾 Opslaan</button>
        <button type="button" class="iconbtn" data-close-edit="1">Annuleren</button>
      </div>
    </form>
  </div>
</div>

<div id="rename_modal" class="modal" aria-hidden="true">
  <div class="modalbox" role="dialog" aria-modal="true" aria-label="Categorie hernoemen">
    <div class="rename-preview" style="display:flex; gap:12px; align-items:center;">
      <div id="rename_preview_bar" style="height:8px; width:48px; border-radius:6px; background:#35e6df;"></div>
      <div class="rename-preview-text">
        <div class="rename-preview-title" style="font-weight:800;">
          <span id="rename_preview_name"></span>
          <span id="rename_preview_tag" class="badge" style="display:none;">DEFAULT</span>
        </div>
        <div class="hint">Live preview</div>
      </div>
    </div>
    <h2 style="margin-top:12px;">Categorie hernoemen</h2>
    <form action="{{ url_for('links_category_rename') }}" method="post">
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
      <div class="modalactions" style="display:flex; gap:8px;">
        <button type="submit" class="iconbtn">✅ Hernoem</button>
        <button type="button" class="iconbtn" data-close-rename="1">Annuleren</button>
      </div>
    </form>
  </div>
</div>

<script>
(function(){
  function qs(s){return document.querySelector(s);}
  function qsa(s){return Array.from(document.querySelectorAll(s));}

  /* Tabs */
  const tLinks = qs('#tab-links');
  const tManage = qs('#tab-manage');
  const show = (panel) => {
    qs('#panel-links').style.display = panel==='links' ? 'block' : 'none';
    qs('#panel-manage').style.display = panel==='manage' ? 'block' : 'none';
    if(tLinks) tLinks.classList.toggle('active', panel==='links');
    if(tManage) tManage.classList.toggle('active', panel==='manage');
  };
  if(tLinks) tLinks.addEventListener('click', ()=>show('links'));
  if(tManage) tManage.addEventListener('click', ()=>show('manage'));
  if((location.hash||'').toLowerCase().includes('manage')) show('manage');

  /* Copy knoppen */
  qsa('[data-copy-btn="1"]').forEach(btn=>{
    btn.addEventListener('click', async (ev)=>{
      ev.preventDefault(); ev.stopPropagation();
      const val = btn.dataset.copy || '';
      if(val){ try{ await navigator.clipboard.writeText(val); }catch(_){} }
    });
  });

  /* Modals sluiten */
  qsa('[data-close-edit="1"]').forEach(btn=>btn.addEventListener('click', ()=>qs('#edit_modal').classList.remove('open')));
  qsa('[data-close-rename="1"]').forEach(btn=>btn.addEventListener('click', ()=>qs('#rename_modal').classList.remove('open')));

  /* --- Inline edit helpers --- */
  function enableInline(container){
    container.classList.add('inline-mode');
    container.querySelectorAll('[data-editable]').forEach(el=>{
      el.setAttribute('contenteditable','true');
      el.style.display = '';
    });
    const urlVis = container.querySelector('a.url');
    const urlEdit = container.querySelector('.inline-edit-url');
    if(urlVis && urlEdit){ urlVis.style.display='none'; urlEdit.style.display='block'; }
    const btnEdit = container.querySelector('[data-inline-edit="1"]');
    const btnSave = container.querySelector('[data-inline-save="1"]');
    const btnCancel = container.querySelector('[data-inline-cancel="1"]');
    if(btnEdit) btnEdit.style.display='none';
    if(btnSave) btnSave.style.display='inline-block';
    if(btnCancel) btnCancel.style.display='inline-block';
    container._original = {};
    container.querySelectorAll('[data-editable]').forEach(el=>{
      container._original[el.dataset.editable] = el.textContent || '';
    });
  }
  function disableInline(container, restore=false){
    container.classList.remove('inline-mode');
    const urlVis = container.querySelector('a.url');
    const urlEdit = container.querySelector('.inline-edit-url');
    if(restore && container._original){
      container.querySelectorAll('[data-editable]').forEach(el=>{
        const key = el.dataset.editable;
        if(container._original[key] !== undefined){
          el.textContent = container._original[key];
        }
      });
    }
    container.querySelectorAll('[data-editable]').forEach(el=>{
      el.setAttribute('contenteditable','false');
      if(el.classList.contains('inline-edit-url')) el.style.display='none';
    });
    if(urlVis) urlVis.style.display='inline';
    if(urlEdit) urlEdit.style.display='none';
    const btnEdit = container.querySelector('[data-inline-edit="1"]');
    const btnSave = container.querySelector('[data-inline-save="1"]');
    const btnCancel = container.querySelector('[data-inline-cancel="1"]');
    if(btnEdit) btnEdit.style.display='inline-block';
    if(btnSave) btnSave.style.display='none';
    if(btnCancel) btnCancel.style.display='none';
    delete container._original;
  }
  function collectInline(container){
    const data = { id: container.dataset.id || container.getAttribute('data-id'), name:'', url:'', category:'', info:'' };
    container.querySelectorAll('[data-editable]').forEach(el=>{
      const key = el.dataset.editable;
      if(key && Object.prototype.hasOwnProperty.call(data,key)){
        data[key] = (el.textContent || '').trim();
      }
    });
    if(!data.url){
      const urlEdit = container.querySelector('.inline-edit-url');
      if(urlEdit) data.url = (urlEdit.textContent || '').trim();
    }
    return data;
  }
  async function postJSON(url, payload){
    const r = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
    return r.json();
  }
  function bindInline(scope){
    scope.querySelectorAll('[data-inline-edit="1"]').forEach(btn=>{
      btn.addEventListener('click', (ev)=>{
        ev.preventDefault(); ev.stopPropagation();
        const container = btn.closest('.cardlink') || btn.closest('tr');
        if(container) enableInline(container);
      });
    });
    scope.querySelectorAll('[data-inline-cancel="1"]').forEach(btn=>{
      btn.addEventListener('click', (ev)=>{
        ev.preventDefault(); ev.stopPropagation();
        const container = btn.closest('.cardlink') || btn.closest('tr');
        if(container) disableInline(container, true);
      });
    });
    scope.querySelectorAll('[data-inline-save="1"]').forEach(btn=>{
      btn.addEventListener('click', async (ev)=>{
        ev.preventDefault(); ev.stopPropagation();
        const container = btn.closest('.cardlink') || btn.closest('tr');
        if(!container) return;
        const data = collectInline(container);
        if(!data.id || !data.name || !data.url){ alert('Naam en URL zijn verplicht.'); return; }
        try{
          const res = await postJSON('{{ url_for("links_update_json") }}', data);
          if(res && res.ok){
            const urlVis = container.querySelector('a.url');
            if(urlVis){ urlVis.textContent = data.url; urlVis.href = data.url; }
            const catBadge = container.querySelector('.badge');
            if(catBadge) catBadge.textContent = data.category;
            disableInline(container, false);
          }else{
            alert(res.message || 'Opslaan mislukt');
          }
        }catch(e){ alert('Netwerk- of serverfout bij opslaan.'); }
      });
    });
  }
  bindInline(document);

  /* --- Drag & Drop (cards + lijst) --- */
  function makeDraggable(containerSelector, itemSelector){
    const container = qs(containerSelector);
    if(!container) return;

    container.addEventListener('dragstart', (e)=>{
      const target = e.target.closest(itemSelector);
      if(!target) return;
      target.classList.add('is-dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', target.dataset.id || '');
    });
    container.addEventListener('dragover', (e)=>{
      e.preventDefault();
      const afterEl = getDragAfterElement(container, e.clientY, itemSelector);
      const dragging = container.querySelector('.is-dragging');
      if(!dragging) return;
      if(afterEl == null){ container.appendChild(dragging); }
      else { container.insertBefore(dragging, afterEl); }
    });
    container.addEventListener('drop', async (e)=>{
      e.preventDefault();
      const dragging = container.querySelector('.is-dragging');
      if(dragging) dragging.classList.remove('is-dragging');
      const ids = Array.from(container.querySelectorAll(itemSelector)).map(el=>el.dataset.id);
      const cat = "{{ active_cat }}";
      if(!cat || cat === "__ALL__"){ alert("Reorder kan enkel per categorie, niet op 'Alle'."); return; }
      try{
        const res = await postJSON('{{ url_for("links_reorder") }}', { category: cat, ordered_ids: ids });
        if(!res || !res.ok){ alert(res.message || 'Reorder mislukt'); }
      }catch(_){ alert('Netwerk- of serverfout bij reorder.'); }
    });
    container.addEventListener('dragend', ()=>{
      const dragging = container.querySelector('.is-dragging');
      if(dragging) dragging.classList.remove('is-dragging');
    });
    function getDragAfterElement(container, y, selector){
      const els = [...container.querySelectorAll(selector+':not(.is-dragging)')];
      return els.reduce((closest, child)=>{
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height/2;
        if(offset < 0 && offset > closest.offset){ return { offset, element: child }; }
        else { return closest; }
      }, {offset: Number.NEGATIVE_INFINITY}).element;
    }
  }
  makeDraggable('#cardsGrid', '.cardlink');
  makeDraggable('#links_tbody', 'tr');
})();
</script>
"""

# ---------- Query helpers ----------
def _grid_css() -> str:
    return _grid_css_from_modes(DEFAULT_MODES)

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
    default_cat = db.get("prefs", {}).get("default_category") or FALLBACK_CATEGORY
    for r in db.get("links", []):
        if isinstance(r, dict):
            cats.add(_normalize(r.get("category")) or default_cat)
    if isinstance(db.get("categories"), dict):
        cats.update(db["categories"].keys())
    out = sorted(cats, key=lambda x: x.lower())
    if hide_default and default_cat in out:
        out.remove(default_cat)
    return out

def _sort_key(r: Dict[str, Any]) -> Tuple[int, str]:
    try:
        return (int(r.get("order", 0)), (r.get("name") or "").lower())
    except Exception:
        return (0, (r.get("name") or "").lower())

def _render_page(*, active_tab: str, active_cat: str, error: str = "", msg: str = ""):
    db = load_db()
    prefs = db["prefs"]
    default_cat = prefs["default_category"]
    hide_default = bool(prefs["hide_default_category"])
    view_mode = prefs["view_mode"]
    links_layout = prefs.get("links_layout", DEFAULT_LAYOUT)

    counts = _counts_by_cat(db)
    categories = _categories(db, hide_default)
    all_categories = _categories(db, False)

    # kleurmap
    cat_colors: Dict[str, str] = {}
    for k, v in (db.get("categories") or {}).items():
        if isinstance(v, dict):
            cat_colors[k] = _hex(v.get("color"), DEFAULT_COLOR)

    # filter & sort
    rows = list(db.get("links", []))
    rows.sort(key=_sort_key)
    if active_cat == "__ALL__":
        filtered = rows if not hide_default else [r for r in rows if (r.get("category") or "") != default_cat]
    else:
        filtered = [r for r in rows if (r.get("category") or "") == active_cat]

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
        links_layout=links_layout,
        cat_colors=cat_colors,
        grid_css=_grid_css(),
        css_version=int(datetime.now().timestamp()),
    )
    return _render_layout(title="Nuttige links", content_html=html)

# ---------- Routes ----------
def register_web_routes(app: Flask):
    # ------------- DEBUG ROUTES -------------
    @app.get("/links/_routes")
    def _links_routes():
        routes = []
        for r in app.url_map.iter_rules():
            if str(r.rule).startswith("/links"):
                routes.append({
                    "rule": str(r.rule),
                    "endpoint": r.endpoint,
                    "methods": sorted(m for m in r.methods if m not in {"HEAD", "OPTIONS"}),
                })
        return {"routes": routes}

    @app.get("/links/_debug_state")
    def links_debug_state():
        db = load_db()
        return {
            "prefs": db.get("prefs"),
            "categories": db.get("categories"),
            "links_count": len(db.get("links", [])),
        }

    # Index
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

    # Create
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

        max_order = 0
        for r in db["links"]:
            if (r.get("category") or "") == cat:
                try:
                    max_order = max(max_order, int(r.get("order", 0)))
                except Exception:
                    pass

        db["links"].append({
            "id": str(uuid.uuid4()),
            "name": name,
            "url": url,
            "category": cat,
            "info": info,
            "order": max_order + 1,
            "created": _now_iso(),
            "updated": _now_iso(),
        })
        save_db(db)
        return redirect(url_for("links_index", cat=cat, msg="Link toegevoegd!", tab="links") + "#links")

    # Delete
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

    # Update (form)
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

    # Update (JSON) voor inline editing
    @app.post("/links/update_json")
    def links_update_json():
        try:
            payload = request.get_json(force=True) or {}
        except Exception:
            return jsonify({"ok": False, "message": "Ongeldige JSON"}), 400

        rid = _normalize(payload.get("id"))
        name = _normalize(payload.get("name"))
        urlv = _normalize(payload.get("url"))
        info = _normalize(payload.get("info"))
        cat = _normalize(payload.get("category"))

        if not rid or not name or not urlv:
            return jsonify({"ok": False, "message": "ID, Naam en URL zijn verplicht."}), 400

        db = load_db()
        default_cat = db["prefs"]["default_category"]
        if not cat:
            cat = default_cat
        db["categories"].setdefault(cat, {"color": DEFAULT_COLOR})

        for r in db.get("links", []):
            if r.get("id") == rid:
                r["name"] = name
                r["url"] = urlv
                r["category"] = cat
                r["info"] = info
                r["updated"] = _now_iso()
                save_db(db)
                return jsonify({"ok": True, "row": r})
        return jsonify({"ok": False, "message": "Link niet gevonden."}), 404

    # Preferences
    @app.post("/links/prefs")
    def links_prefs():
        db = load_db()
        action = _normalize(request.form.get("action"))
        if action == "toggle_hide_default":
            db["prefs"]["hide_default_category"] = bool(request.form.get("hide_default_category"))
            save_db(db)
            return redirect(url_for("links_index", cat="__ALL__", msg="Voorkeuren opgeslagen!", tab="manage") + "#manage")

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

        if action == "set_view_mode":
            vm = (_normalize(request.form.get("view_mode")) or "").lower()
            if vm not in ("comfortable", "compact"):
                return redirect(url_for("links_index", cat="__ALL__", error="Onbekende view mode.", tab="links") + "#links")
            db["prefs"]["view_mode"] = vm
            save_db(db)
            cat_back = _normalize(request.form.get("cat") or "__ALL__") or "__ALL__"
            return redirect(url_for("links_index", cat=cat_back, msg="Weergave aangepast!", tab="links") + "#links")

        if action == "set_links_layout":
            layout = (_normalize(request.form.get("links_layout")) or "").lower()
            if layout not in ("cards", "list"):
                return redirect(url_for("links_index", cat="__ALL__", error="Onbekende layout.", tab="links") + "#links")
            db["prefs"]["links_layout"] = layout
            save_db(db)
            cat_back = _normalize(request.form.get("cat") or "__ALL__") or "__ALL__"
            return redirect(url_for("links_index", cat=cat_back, msg="Layout aangepast!", tab="links") + "#links")

        return redirect(url_for("links_index", cat="__ALL__", error="Onbekende actie.", tab="manage") + "#manage")

    # Category kleur/rename/delete
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

    # Reorder (JSON)
    @app.post("/links/reorder")
    def links_reorder():
        try:
            payload = request.get_json(force=True) or {}
        except Exception:
            return jsonify({"ok": False, "message": "Ongeldige JSON"}), 400
        cat = _normalize(payload.get("category"))
        ids = payload.get("ordered_ids")
        if not isinstance(ids, list) or not ids:
            return jsonify({"ok": False, "message": "ordered_ids vereist"}), 400
        if not cat or cat == "__ALL__":
            return jsonify({"ok": False, "message": "Reorder kan enkel per categorie (niet op Alle)."}), 400

        db = load_db()
        order_map = {rid: i + 1 for i, rid in enumerate(ids)}
        for r in db.get("links", []):
            if (r.get("category") or "") == cat:
                rid = r.get("id")
                if rid in order_map:
                    r["order"] = order_map[rid]
        save_db(db)
        return jsonify({"ok": True})

    # ---------- Import / Export ----------
    @app.get("/links/export")
    def links_export():
        """Download de actuele useful_links.json (versie 2, als JSON)."""
        db = load_db()
        pretty = bool(request.args.get("pretty"))
        try:
            text = json.dumps(db, indent=2 if pretty else None, ensure_ascii=False)
        except Exception:
            return jsonify({"ok": False, "message": "Kon DB niet serialiseren"}), 500
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"useful_links_{ts}.json"
        return Response(
            text,
            mimetype="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    @app.post("/links/import")
    def links_import():
        """
        Upload van useful_links.json:
        - mode: merge (default) of replace
        - dedup: by_id (default) of by_name_url
        - backup: '1' om eerst een backup te maken
        """
        f = request.files.get("file")
        if not f:
            return redirect(url_for("links_index", cat="__ALL__", error="Geen bestand geselecteerd.", tab="manage") + "#manage")
        mode = (_normalize(request.form.get("mode")) or "merge").lower()
        if mode not in ("merge", "replace"):
            mode = "merge"
        dedup = (_normalize(request.form.get("dedup")) or "by_id").lower()
        if dedup not in ("by_id", "by_name_url"):
            dedup = "by_id"
        do_backup = bool(request.form.get("backup", "1"))

        # lees incoming JSON
        try:
            raw_text = f.read().decode("utf-8")
            incoming = json.loads(raw_text)
        except Exception:
            return redirect(url_for("links_index", cat="__ALL__", error="Ongeldige of niet-UTF8 JSON.", tab="manage") + "#manage")

        # backup
        if do_backup:
            _backup_file(DATA_PATH)

        # merge/replace
        current = load_db()
        try:
            merged = _merge_useful_links(current, incoming, mode=mode, dedup=dedup)
        except Exception:
            return redirect(url_for("links_index", cat="__ALL__", error="Import mislukt tijdens merge/validatie.", tab="manage") + "#manage")

        save_db(merged)
        return redirect(url_for("links_index", cat="__ALL__", msg=f"Import succesvol ({mode}, {dedup}).", tab="manage") + "#manage")

# ---------- Bootstrap / health ----------
def ensure_bootstrap_files() -> None:
    """Zorgt dat de noodzakelijke configbestanden bestaan met minimum defaults."""
    if not DATA_PATH.exists():
        _save_json(DATA_PATH, _default_db())

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

# ---------- Standalone runner ----------
if __name__ == "__main__":
    # Alleen voor lokale tests; in de Hub wordt dit module geïmporteerd
    app = Flask(__name__)
    ensure_bootstrap_files()
    register_web_routes(app)
    register_health_routes(app)
    # Run een mini server op localhost:5008 zodat je standalone kan testen
    app.run(host="127.0.0.1", port=5008, debug=True)
