
# tools/i18n_builder.py
#!/usr/bin/env python3
# -------------------------------------------------------------------------------------------------
# i18n_builder.py — CyNiT-Hub module (GLOBAL SHIMS + Hub Layout w/ Standalone Fallback)
# Hybride: werkt in de Hub (met beheer.main_layout) én standalone (fallback-layout + static).
# -------------------------------------------------------------------------------------------------
from __future__ import annotations
import os
import io
import re
import json
import shutil
import zipfile
from datetime import datetime
from typing import Dict, Any

from flask import (
    Blueprint, request, jsonify, send_file, render_template_string,
    current_app, redirect, url_for, send_from_directory, Response, Flask
)

# ---- Hub layout (optioneel) -------------------------------------------------
try:
    from beheer.main_layout import render_page as hub_render_page  # type: ignore
except Exception:
    hub_render_page = None  # fallback gebruiken in standalone

# ---- Optional deps ----------------------------------------------------------
try:
    import yaml
except Exception:
    yaml = None
try:
    import pdfkit
except Exception:
    pdfkit = None
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
except Exception:
    A4 = None
    canvas = None
try:
    import markdown
except Exception:
    markdown = None

from jinja2 import Environment, FileSystemLoader, select_autoescape

# -------------------------------------------------------------------------------------------------
# App paths
# -------------------------------------------------------------------------------------------------
bp = Blueprint("i18n_builder", __name__, url_prefix="/i18n")
shim_bp = Blueprint("i18n_shims", __name__)  # root-level shims

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BASE_PATH, ".."))
CONFIG_DIR = os.path.join(ROOT_DIR, "config")
STATIC_DIR = os.path.join(ROOT_DIR, "static")
USERDATA_DIR = os.path.join(ROOT_DIR, "userdata")
DATA_DIR = os.path.join(USERDATA_DIR, "i18n_builder")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
PUBLISH_DIR = os.path.join(DATA_DIR, "published")
TEMPLATES_DIR = os.path.join(DATA_DIR, "templates")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(PUBLISH_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(CONFIG_DIR, "i18n_builder.json")
MODES_FILE = os.path.join(CONFIG_DIR, "i18n_modes.json")
BACKUP_MAX_VERSIONS = 10

# -------------------------------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------------------------------
def load_json(path: str):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def safe_name(name: str) -> str:
    if not name:
        return ""
    name = os.path.basename(name.strip())
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    return name

def file_path_in_data(filename: str) -> str:
    return os.path.join(DATA_DIR, safe_name(filename))

def backup_file_path(filename: str, ts: str) -> str:
    name = safe_name(filename)
    stem, ext = os.path.splitext(name)
    bdir = os.path.join(BACKUP_DIR, stem)
    os.makedirs(bdir, exist_ok=True)
    return os.path.join(bdir, f"{stem}__{ts}{ext or '.txt'}")

def list_backups(filename: str):
    name = safe_name(filename)
    stem, _ = os.path.splitext(name)
    bdir = os.path.join(BACKUP_DIR, stem)
    if not os.path.isdir(bdir):
        return []
    files = []
    for f in sorted(os.listdir(bdir)):
        full = os.path.join(bdir, f)
        if os.path.isfile(full):
            files.append({"name": f, "path": full, "size": os.path.getsize(full), "mtime": os.path.getmtime(full)})
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return files

def rotate_backups(filename: str, keep: int = BACKUP_MAX_VERSIONS):
    backups = list_backups(filename)
    for b in backups[keep:]:
        try:
            os.remove(b["path"])
        except Exception:
            pass

def split_frontmatter(text: str):
    if not text:
        return {}, ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            yaml_block = parts[1].strip()
            body = parts[2].lstrip()
            meta = {}
            if yaml:
                try:
                    meta = yaml.safe_load(yaml_block) or {}
                except Exception:
                    meta = {}
            return meta, body
    return {}, text

def assemble_frontmatter(meta: dict, body: str):
    if not meta:
        return body or ""
    if yaml:
        yaml_part = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
    else:
        yaml_part = json.dumps(meta, indent=2, ensure_ascii=False)
    return f"---\n{yaml_part}---\n\n{body or ''}"

def sanitize_html(html: str):
    if not html:
        return ""
    clean = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
    clean = re.sub(r"\son\w+\s*=\s*\".*?\"", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\son\w+\s*=\s*\'.*?\'", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\son\w+\s*=\s*[^ >]+", "", clean, flags=re.IGNORECASE)
    return clean

def ensure_default_templates():
    base_html = os.path.join(TEMPLATES_DIR, "base.html")
    page_html = os.path.join(TEMPLATES_DIR, "page.html")
    if not os.path.exists(base_html):
        with open(base_html, "w", encoding="utf-8") as f:
            f.write("""<!DOCTYPE html>
<html lang="{{ meta.lang or 'nl' }}">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark light">
  <title>{{ meta.title or title or 'Document' }}</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif;
           margin: 0; padding: 2rem; line-height: 1.55; }
    .container { max-width: 980px; margin: 0 auto; }
    body.dark { background: #121212; color: #e6e6e6; }
    {% block styles %}{% endblock %}
  </style>
  {% if inline_css %}<style id="builder-inline-styles">{{ inline_css | safe }}</style>{% endif %}
  {% block head_extra %}{% endblock %}
</head>
<body class="{{ 'dark' if (meta.theme=='dark') else '' }}">
  <div class="container">{% block content %}{% endblock %}</div>
  {% block scripts %}{% endblock %}
</body></html>
""")
    if not os.path.exists(page_html):
        with open(page_html, "w", encoding="utf-8") as f:
            f.write("""{% extends "base.html" %}
{% block content %}
{{ body | safe }}
{% endblock %}
""")

def jinja_env() -> Environment:
    ensure_default_templates()
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(['html', 'xml'])
    )
    return env

def render_template_to_html(template_name: str, context: dict) -> str:
    env = jinja_env()
    tpl = env.get_template(template_name)
    return tpl.render(**context)

def _cfg_wkhtml_path_from_json():
    cfg = load_json(CONFIG_FILE)
    p = (cfg.get("wkhtmltopdf") or {}).get("portable_path")
    if p:
        return p
    return None

def detect_wkhtmltopdf_path() -> str:
    p = _cfg_wkhtml_path_from_json()
    if p and os.path.exists(p):
        return p
    env_p = os.environ.get("WKHTMLTOPDF_PATH")
    if env_p and os.path.exists(env_p):
        return env_p
    user_path_dir = r"C:\gh\CyNiT-Hub\static\vendor\wkhtmltox\bin"
    user_path = os.path.join(user_path_dir, "wkhtmltopdf.exe")
    if os.path.exists(user_path):
        return user_path
    cand = os.path.join(
        STATIC_DIR, "vendor", "wkhtmltox", "bin",
        "wkhtmltopdf.exe" if os.name == "nt" else "wkhtmltopdf"
    )
    if os.path.exists(cand):
        return cand
    try:
        from shutil import which
        found = which("wkhtmltopdf")
        if found:
            return found
    except Exception:
        pass
    for g in ["/usr/bin/wkhtmltopdf", "/usr/local/bin/wkhtmltopdf",
              "C:\\\\Program Files\\\\wkhtmltopdf\\\\bin\\\\wkhtmltopdf.exe",
              "C:\\\\Program Files (x86)\\\\wkhtmltopdf\\\\bin\\\\wkhtmltopdf.exe"]:
        if os.path.exists(g):
            return g
    return ""

def html_to_pdf_bytes(html: str) -> bytes:
    html = html or ""
    if pdfkit:
        try:
            exe = detect_wkhtmltopdf_path()
            config = pdfkit.configuration(wkhtmltopdf=exe) if exe else None
            options = {"quiet": None, "enable-local-file-access": None, "page-size": "A4", "print-media-type": None}
            pdf_bytes = pdfkit.from_string(html, False, configuration=config, options=options)
            if pdf_bytes:
                return pdf_bytes
        except Exception:
            pass
    if canvas and A4:
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        width, height = A4
        text = re.sub(r"<[^>]+>", "", html)
        y = height - 40
        for line in text.splitlines():
            c.drawString(40, y, line[:2000])
            y -= 14
            if y < 40:
                c.showPage()
                y = height - 40
        c.save()
        buf.seek(0)
        return buf.read()
    raise RuntimeError("Geen PDF engine beschikbaar (wkhtmltopdf/pdfkit of reportlab vereist).")

# -------------------------------------------------------------------------------------------------
# UI (CONTENT-ONLY) — hub layout + CSS inject
# -------------------------------------------------------------------------------------------------
BASE_STYLE = r"""
<style>
.i18n-wrap { max-width: 1100px; margin: 0 auto; }
.card {
  background: rgba(10,15,18,.85); border-radius: 12px; padding: 16px 20px; margin-bottom: 20px;
  border: 1px solid var(--border, rgba(255,255,255,.10));
}
.card h2 { margin: 0 0 8px 0; }
.card small { color: var(--muted, #9fb3b3); }
.field-row { margin-bottom: 10px; }
.field-row label { display: block; margin-bottom: 3px; }
.in {
  width: 100%; box-sizing: border-box; padding: 10px 12px;
  border-radius: 10px; background: #111; color: #fff;
  border: 1px solid var(--border, rgba(255,255,255,.18));
}
.row-inline { display: flex; gap: 12px; }
.row-inline > div { flex: 1; }
.error-box {
  background: #330000; border: 1px solid #aa3333; color: #ffaaaa; padding: 8px 10px;
  border-radius: 8px; margin-bottom: 12px; font-size: 0.9rem; white-space: pre-wrap;
}
.i18n-btn { padding:8px 16px; border-radius:6px; background:#4285f4; color:#fff; border:0; cursor:pointer; }
/* Fallback styling voor mode-tabs (ook zonder i18n_builder.css) */
.i18n-mode-switcher { display:flex; gap:8px; margin-left:auto; }
.i18n-mode-tab {
  padding: 8px 14px; border-radius: 6px; background: #2c2c2c; border: 1px solid #444;
  cursor: pointer; user-select: none; font-weight: 500; font-size:13px; color:#ddd;
}
.i18n-mode-tab:hover { background:#4285f4; color:#fff; border-color:#4285f4; }
.i18n-mode-tab.active { background:#3a3a3a; border-color:#82b1ff; color:#eee; }
</style>
"""

CSS_INJECT_SNIPPET = r"""
<script>
(function(){
  var id='i18n-builder-css';
  if(!document.getElementById(id)){
    var l=document.createElement('link');
    l.id=id; l.rel='stylesheet'; l.href='/static/css/i18n_builder.css';
    document.head.appendChild(l);
  }
})();
</script>
"""

EDITOR_CONTENT = r"""
{{ base_style | safe }}
{{ css_inject | safe }}
<div class="i18n-wrap">
  <h1>I18N Builder</h1>
  <p class="muted">Beheer en bouw vertalings-/publicatiebundels (import, merge, export, preview, PDF).</p>
  {% if err %}<div class="error-box">{{ err }}</div>{% endif %}

  <div class="card">
    <h2>Editor</h2>
    <small>De interactieve editor wordt door <code>/static/js/i18n_builder.js</code> geïnitialiseerd.</small>
    <div class="field-row">
      <button class="i18n-btn" onclick="document.body.classList.toggle('dark')">Toggle Dark/Light</button>
    </div>
    <div class="field-row">
      <div class="i18n-builder-container">Loading i18n Builder…</div>
    </div>
  </div>

  <div class="card">
    <h2>Snelle acties</h2>
        <div class="row-inline">
            <div><a class="btn" href="/i18n/test_pdf?template=page.html">PDF-detectie (JSON)</a></div>
            <div><a class="btn" href="/i18n/test_pdf?download=1&template=page.html">Download test-PDF</a></div>
            <div><a class="btn" href="/i18n/languages">Taalbeheer / Templates</a></div>
            <div><a class="btn" href="/i18n/_vendor_check" target="_blank">Vendor Check</a></div>
        </div>
  </div>
</div>
<script src="/static/js/i18n_builder.js"></script>
"""

LANG_CONTENT = r"""
{{ base_style | safe }}
{{ css_inject | safe }}
<div class="i18n-wrap">
  <h1>I18N Builder — Taalbeheer</h1>
  <p class="muted">Beheer Jinja-templates en publicatiebestandsnamen.</p>
    <p>
    <a class="i18n-btn" href="/i18n/_vendor_check" target="_blank">
        Vendor Check
    </a>
    </p>
  <div class="card">
    <h2>Templates</h2>
    <div class="row-inline">
      <div>
        <label>Jinja template</label>
        <select id="templateSelect" class="in"></select>
      </div>
      <div style="flex:0 0 auto; display:flex; gap:8px; align-items:flex-end;">
        <button class="i18n-btn" id="newTplBtn">Nieuwe template</button>
        <button class="i18n-btn" id="delTplBtn">Verwijder template</button>
      </div>
    </div>

    <div class="row-inline" style="margin-top:10px;">
      <div>
        <label>Publicatie-bestandsnaam</label>
        <input id="pubFile" class="in" type="text" placeholder="index.html"/>
      </div>
    </div>

    <div class="field-row" style="margin-top:12px;">
      <label>Inhoud (HTML of Markdown)</label>
      <textarea id="contentArea" class="in" style="height:220px;"></textarea>
    </div>

    <div class="field-row">
      <label>Front-matter YAML</label>
      <textarea id="metaArea" class="in" style="height:160px;">title: Nieuw document
lang: nl
theme: dark
description: Demo publicatie</textarea>
    </div>

    <div class="field-row">
      <label>Inline CSS</label>
      <textarea id="cssArea" class="in" style="height:120px;">/* optionele inline styles */</textarea>
    </div>

    <div class="row-inline" style="margin-top:10px;">
      <div><button class="i18n-btn" id="savePub">Publiceer naar HTML</button></div>
      <div><button class="i18n-btn" id="exportPdf">Exporteer naar PDF</button></div>
      <div><button class="i18n-btn" onclick="document.body.classList.toggle('dark')">Toggle Dark/Light</button></div>
    </div>
  </div>
</div>
<script src="/static/js/i18n_builder.js"></script>
"""

# ---- Hybride _render: hub-layout wanneer beschikbaar, anders fallback -------------
def _render(content_html: str, title: str = "I18N Builder"):
    if hub_render_page:
        try:
            return hub_render_page(title=title, content_html=content_html)
        except Exception:
            pass  # val terug op fallback
    # Fallback layout (standalone)
    return (
        "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
        f"<title>{title}</title>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='color-scheme' content='dark light'>"
        "<style>"
        "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,'Helvetica Neue',Arial,'Noto Sans',sans-serif;"
        "margin:0;background:#121212;color:#e6e6e6;}"
        ".container{max-width:1100px;margin:0 auto;padding:2rem;}"
        "a{color:#35e6df;text-decoration:none}a:hover{text-decoration:underline}"
        "</style>"
        # optioneel: main.css laden indien aanwezig
        "<link rel='preload' as='style' href='/static/css/main.css' onload=\"this.rel='stylesheet'\">"
        "</head><body><div class='container'>"
        + content_html +
        "</div></body></html>"
    )

# -------------------------------------------------------------------------------------------------
# GLOBAL SHIMS (root-level) – met dubbele check voor Tiptap extensions
# -------------------------------------------------------------------------------------------------
@shim_bp.route("/@tiptap/<path:req>")
def tiptap_shim_global(req: str):
    """
    Voorbeelden:
    /@tiptap/core@2.6.6/es2022/core.mjs
    /@tiptap/starter-kit@^2.6.6?target=es2022
    /@tiptap/extension-bold@^2.6.6?target=es2022
    /@tiptap/pm@^2.6.6/state?target=es2022
    """
    req = req.split("?", 1)[0]
    first = req.split("/", 1)[0]  # bv. "extension-bold@^2.6.6" of "pm@^2.6.6"
    name = first.split("@", 1)[0]  # "extension-bold" | "core" | "starter-kit" | "pm"
    rest = req[len(first):].lstrip("/")
    base_dir = os.path.join(STATIC_DIR, "vendor", "tiptap")

    def try_send(relpath: str):
        if not relpath:
            return None
        abspath = os.path.join(base_dir, relpath)
        if os.path.isfile(abspath):
            return send_file(abspath, mimetype="application/javascript")
        return None

    if name == "pm":
        mapping = {
            "commands": "prosemirror/commands.js",
            "history": "prosemirror/history.js",
            "model": "prosemirror/model.js",
            "schema-basic": "prosemirror/schema-basic.js",
            "schema-list": "prosemirror/schema-list.js",
            "state": "prosemirror/state.js",
            "transform": "prosemirror/transform.js",
            "view": "prosemirror/view.js",
            "keymap": "prosemirror/keymap.js",
            "gapcursor": "prosemirror/gapcursor.js",
            "dropcursor": "prosemirror/dropcursor.js",
        }
        key = rest.split("/", 1)[0] if rest else ""
        resp = try_send(mapping.get(key, ""))
        return resp if resp else Response("unknown pm module", 404)

    if name == "core":
        resp = try_send("core/index.js")
        return resp if resp else Response("core not found", 404)

    if name == "starter-kit":
        resp = try_send("starter-kit/index.js")
        return resp if resp else Response("starter-kit not found", 404)

    if name.startswith("extension-"):
        # dubbele check: eerst ext-<name>/index.js, dan extensions/<name>/index.js
        ext_name = name.replace("extension-", "")
        resp = try_send(f"ext-{ext_name}/index.js")
        if resp:
            return resp
        resp = try_send(f"extensions/{ext_name}/index.js")
        if resp:
            return resp
        return Response("extension not found", 404)

    return Response("unknown tiptap path", 404)

@shim_bp.route("/@codemirror/<path:req>")
def codemirror_shim_global(req: str):
    req = req.split("?", 1)[0]
    first = req.split("/", 1)[0]  # "state@..." of "view@..."
    name = first.split("@", 1)[0]  # "state" | "view"
    base_dir = os.path.join(STATIC_DIR, "vendor", "codemirror")
    if name == "state":
        p = os.path.join(base_dir, "state", "index.js")
        if os.path.isfile(p): return send_file(p, mimetype="application/javascript")
    if name == "view":
        p = os.path.join(base_dir, "view", "index.js")
        if os.path.isfile(p): return send_file(p, mimetype="application/javascript")
    return Response("unknown codemirror module", 404)

@shim_bp.route("/crelt@<path:rest>")
def crelt_shim(rest: str):
    p = os.path.join(STATIC_DIR, "vendor", "codemirror", "deps", "crelt.js")
    if not os.path.isfile(p): return Response("crelt not found", 404)
    return send_file(p, mimetype="application/javascript")

@shim_bp.route("/style-mod@<path:rest>")
def stylemod_shim(rest: str):
    p = os.path.join(STATIC_DIR, "vendor", "codemirror", "deps", "style-mod.js")
    if not os.path.isfile(p): return Response("style-mod not found", 404)
    return send_file(p, mimetype="application/javascript")

@shim_bp.route("/w3c-keyname@<path:rest>")
def keyname_shim(rest: str):
    p = os.path.join(STATIC_DIR, "vendor", "codemirror", "deps", "w3c-keyname.js")
    if not os.path.isfile(p): return Response("w3c-keyname not found", 404)
    return send_file(p, mimetype="application/javascript")

@shim_bp.route("/@marijn/find-cluster-break@<path:rest>")
def find_cluster_break_shim(rest: str):
    p = os.path.join(STATIC_DIR, "vendor", "codemirror", "deps", "find-cluster-break.js")
    if not os.path.isfile(p): return Response("find-cluster-break not found", 404)
    return send_file(p, mimetype="application/javascript")

# orderedmap losse alias (zekerheid)
@shim_bp.route("/orderedmap@<path:rest>")
def orderedmap_shim(rest: str):
    p = os.path.join(STATIC_DIR, "vendor", "tiptap", "prosemirror", "orderedmap.js")
    if not os.path.isfile(p): return Response("orderedmap not found", 404)
    return send_file(p, mimetype="application/javascript")

# Directe prosemirror-* CDN paden -> lokale prosemirror/*.js
@shim_bp.route("/prosemirror-<path:req>")
def prosemirror_pkg_shim(req: str):
    pkg = req.split("@", 1)[0] if "@" in req else req.split("/", 1)[0]
    mapping = {
        "prosemirror-model": "model.js",
        "prosemirror-transform": "transform.js",
        "prosemirror-state": "state.js",
        "prosemirror-view": "view.js",
        "prosemirror-commands": "commands.js",
        "prosemirror-history": "history.js",
        "prosemirror-schema-basic": "schema-basic.js",
        "prosemirror-schema-list": "schema-list.js",
        "prosemirror-keymap": "keymap.js",
        "prosemirror-gapcursor": "gapcursor.js",
        "prosemirror-dropcursor": "dropcursor.js",
    }
    rel = mapping.get(pkg)
    if not rel:
        return Response("unknown prosemirror package", 404)
    abspath = os.path.join(STATIC_DIR, "vendor", "tiptap", "prosemirror", rel)
    if not os.path.isfile(abspath):
        return Response("prosemirror module not found", 404)
    return send_file(abspath, mimetype="application/javascript")

# Linkify CDN alias -> lokale bundel
@shim_bp.route("/linkifyjs@<path:rest>")
def linkify_shim_global(rest: str):
    p = os.path.join(STATIC_DIR, "vendor", "tiptap", "ext-link", "linkify.js")
    if not os.path.isfile(p): return Response("linkify stub not found", 404)
    return send_file(p, mimetype="application/javascript")

# -------------------------------------------------------------------------------------------------
# /i18n routes (UI + API)
# -------------------------------------------------------------------------------------------------
@bp.route("/i18n_builder.json", methods=["GET"])
def serve_i18n_builder_json():
    if not os.path.isfile(CONFIG_FILE):
        return jsonify({"error": f"not found: {CONFIG_FILE}"}), 404
    return send_from_directory(CONFIG_DIR, "i18n_builder.json", mimetype="application/json")

@bp.route("/i18n_modes.json", methods=["GET"])
def serve_i18n_modes_json():
    if not os.path.isfile(MODES_FILE):
        return jsonify({"error": f"not found: {MODES_FILE}"}), 404
    return send_from_directory(CONFIG_DIR, "i18n_modes.json", mimetype="application/json")

# -- UI (content-only via layout)
@bp.route("/")
def ui():
    html = render_template_string(EDITOR_CONTENT, base_style=BASE_STYLE, css_inject=CSS_INJECT_SNIPPET, err=None)
    return _render(html, title="I18N Builder")

@bp.route("", methods=["GET"])
def ui_redirect_no_slash():
    return redirect(url_for("i18n_builder.ui"), code=302)

@bp.route("/languages")
def languages_page():
    html = render_template_string(LANG_CONTENT, base_style=BASE_STYLE, css_inject=CSS_INJECT_SNIPPET)
    return _render(html, title="I18N Builder — Taalbeheer")

# -- Load/Save
@bp.route("/load", methods=["POST"])
def load_file_api():
    req = request.get_json(force=True, silent=True) or {}
    filename = safe_name(req.get("filename", ""))
    if not filename:
        return jsonify({"error": "No filename"}), 400
    full = file_path_in_data(filename)
    if not os.path.exists(full):
        return jsonify({"error": "File not found"}), 404
    with open(full, "r", encoding="utf-8") as f:
        content = f.read()
    meta, body = split_frontmatter(content)
    return jsonify({"filename": filename, "meta": meta, "body": body, "raw": content})

# -- Save + backups
@bp.route("/save", methods=["POST"])
def save_file_api():
    req = request.get_json(force=True, silent=True) or {}
    filename = safe_name(req.get("filename", ""))
    meta = req.get("meta") or {}
    body = req.get("body") or ""
    if not filename:
        return jsonify({"error": "No filename"}), 400
    full = file_path_in_data(filename)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    if os.path.exists(full):
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        bfull = backup_file_path(filename, ts)
        try:
            shutil.copy2(full, bfull)
            rotate_backups(filename, BACKUP_MAX_VERSIONS)
        except Exception:
            pass
    text = assemble_frontmatter(meta, body)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)
    return jsonify({"status": "ok"})

# -- Snapshot
@bp.route("/snapshot", methods=["POST"])
def snapshot():
    req = request.get_json(force=True, silent=True) or {}
    filename = safe_name(req.get("filename", "autosave.md"))
    content = req.get("content", "")
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    bfull = backup_file_path(filename, f"SNAP_{ts}")
    os.makedirs(os.path.dirname(bfull), exist_ok=True)
    with open(bfull, "w", encoding="utf-8") as f:
        f.write(content)
    rotate_backups(filename, BACKUP_MAX_VERSIONS)
    return jsonify({"status": "ok", "snapshot": os.path.basename(bfull)})

@bp.route("/backups", methods=["GET"])
def backups_list():
    filename = safe_name(request.args.get("filename", ""))
    if not filename:
        return jsonify({"error": "No filename"}), 400
    backups = list_backups(filename)
    return jsonify({
        "filename": filename,
        "backups": [{"name": b["name"], "size": b["size"], "mtime": b["mtime"]} for b in backups]
    })

@bp.route("/restore_backup", methods=["POST"])
def restore_backup():
    req = request.get_json(force=True, silent=True) or {}
    filename = safe_name(req.get("filename", ""))
    backup_name = safe_name(req.get("backup_name", ""))
    if not filename or not backup_name:
        return jsonify({"error": "Missing filename/backup_name"}), 400
    stem, _ = os.path.splitext(filename)
    bdir = os.path.join(BACKUP_DIR, stem)
    bfull = os.path.join(bdir, backup_name)
    if not os.path.exists(bfull):
        return jsonify({"error": "Backup not found"}), 404
    full = file_path_in_data(filename)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    shutil.copy2(bfull, full)
    return jsonify({"status": "ok"})

# -- Preview (sanitize)
@bp.route("/preview", methods=["POST"])
def preview():
    content = (request.get_json(force=True, silent=True) or {}).get("html", "")
    safe = sanitize_html(content)
    return jsonify({"safe_html": safe})

# -- Upload
@bp.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    name = safe_name(f.filename or "")
    if not name:
        return jsonify({"error": "Invalid filename"}), 400
    full = file_path_in_data(name)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    f.save(full)
    try:
        with open(full, "r", encoding="utf-8", errors="ignore") as h:
            content = h.read()
    except Exception:
        content = ""
    return jsonify({"filename": name, "content": content})

# -- Publish HTML
@bp.route("/publish", methods=["POST"])
def publish():
    req = request.get_json(force=True, silent=True) or {}
    template = (req.get("template") or "page.html").strip()
    output_name = safe_name(req.get("filename") or "index.html")
    raw_body = req.get("body", "") or ""
    meta_yaml = req.get("meta_yaml", "") or ""
    inline_css = req.get("inline_css", "") or ""
    sanitize = bool(req.get("sanitize", True))

    meta: Dict[str, Any] = {}
    if meta_yaml and yaml:
        try:
            meta = yaml.safe_load(meta_yaml) or {}
        except Exception:
            meta = {}

    body_html = raw_body
    if not re.search(r"</\w+>", raw_body) and re.search(r"(^# |\n# )", raw_body):
        if markdown:
            try:
                body_html = markdown.markdown(raw_body, extensions=["extra", "toc", "tables"])
            except Exception:
                body_html = raw_body
        else:
            body_html = re.sub(r"^# (.*)$", r"<h1>\1</h1>", raw_body, flags=re.MULTILINE)
            body_html = re.sub(r"^## (.*)$", r"<h2>\1</h2>", body_html, flags=re.MULTILINE)
            body_html = re.sub(r"^### (.*)$", r"<h3>\1</h3>", body_html, flags=re.MULTILINE)
            body_html = "<p>" + body_html.replace("\n\n", "</p><p>") + "</p>"

    if sanitize:
        body_html = sanitize_html(body_html)

    meta = meta or {}
    if "theme" not in meta:
        meta["theme"] = "dark"
    context = {"meta": meta, "title": meta.get("title") or "Document", "body": body_html, "inline_css": inline_css}
    html = render_template_to_html(template, context)

    if inline_css:
        if "</style>" in html:
            html = html.replace("</style>", f"\n{inline_css}\n</style>")
        else:
            html = html.replace("</head>", f"<style>\n{inline_css}\n</style>\n</head>")

    out_path = os.path.join(PUBLISH_DIR, output_name)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return jsonify({"status": "ok", "output_path": out_path})

# -- Export PDF
@bp.route("/export_pdf", methods=["POST"])
def export_pdf():
    req = request.get_json(force=True, silent=True) or {}
    template = (req.get("template") or "page.html").strip()
    raw_body = req.get("body", "") or ""
    meta_yaml = req.get("meta_yaml", "") or ""
    inline_css = req.get("inline_css", "") or ""
    sanitize = bool(req.get("sanitize", True))

    meta: Dict[str, Any] = {}
    if meta_yaml and yaml:
        try:
            meta = yaml.safe_load(meta_yaml) or {}
        except Exception:
            meta = {}

    body_html = raw_body
    if not re.search(r"</\w+>", raw_body) and re.search(r"(^# |\n# )", raw_body):
        if markdown:
            try:
                body_html = markdown.markdown(raw_body, extensions=["extra", "toc", "tables"])
            except Exception:
                body_html = raw_body
        else:
            body_html = re.sub(r"^# (.*)$", r"<h1>\1</h1>", raw_body, flags=re.MULTILINE)
            body_html = re.sub(r"^## (.*)$", r"<h2>\1</h2>", body_html, flags=re.MULTILINE)
            body_html = re.sub(r"^### (.*)$", r"<h3>\1</h3>", body_html, flags=re.MULTILINE)
            body_html = "<p>" + body_html.replace("\n\n", "</p><p>") + "</p>"

    if sanitize:
        body_html = sanitize_html(body_html)

    if "theme" not in meta:
        meta["theme"] = "dark"

    context = {"meta": meta, "title": meta.get("title") or "Document", "body": body_html, "inline_css": inline_css}
    html = render_template_to_html(template, context)

    if inline_css:
        if "</style>" in html:
            html = html.replace("</style>", f"\n{inline_css}\n</style>")
        else:
            html = html.replace("</head>", f"<style>\n{inline_css}\n</style>\n</head>")

    try:
        pdf_bytes = html_to_pdf_bytes(html)
    except Exception as e:
        return ("PDF export faalde: " + str(e), 500, {"Content-Type": "text/plain; charset=utf-8"})
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True, download_name="export.pdf")

# -- Test PDF
@bp.route("/test_pdf", methods=["GET"])
def test_pdf():
    download = (request.args.get("download", "").lower() in ("1", "true", "yes"))
    template = (request.args.get("template") or "page.html").strip()
    detected_path = detect_wkhtmltopdf_path()
    info = {
        "wkhtmltopdf_path": detected_path or "",
        "pdfkit_available": bool(pdfkit),
        "reportlab_available": bool(canvas and A4),
        "template": template,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    meta = {"title": "Test PDF", "lang": "nl", "theme": "dark"}
    sample_css = "h1{color:#4285f4;} .muted{color:#777; font-size:12px}"
    sample_body = f"""
<h1>PDF Test OK</h1>
<p class="muted">Gegenereerd op {info['timestamp']}</p>
<p>Dit is een testdocument om wkhtmltopdf detectie en rendering te valideren.</p>
"""
    context = {"meta": meta, "title": meta["title"], "body": sample_body, "inline_css": sample_css}
    html = render_template_to_html(template, context)

    if download:
        try:
            pdf_bytes = html_to_pdf_bytes(html)
            return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True, download_name="test.pdf")
        except Exception as e:
            return ("PDF generatie faalde: " + str(e), 500, {"Content-Type": "text/plain; charset=utf-8"})

    try:
        _ = html_to_pdf_bytes(html)
        info["can_render_pdf"] = True
    except Exception as e:
        info["can_render_pdf"] = False
        info["error"] = str(e)
    return jsonify(info)

# -- Template management
@bp.route("/list_templates", methods=["GET"])
def list_templates():
    ensure_default_templates()
    items = []
    for f in os.listdir(TEMPLATES_DIR):
        if f.lower().endswith(".html") and os.path.isfile(os.path.join(TEMPLATES_DIR, f)):
            items.append(f)
    items.sort()
    return jsonify({"templates": items})

@bp.route("/new_template", methods=["POST"])
def new_template():
    req = request.get_json(force=True, silent=True) or {}
    name = safe_name(req.get("name", "page.html"))
    content = req.get("content", "{% extends 'base.html' %}\n{% block content %}\n{{ body | safe }}\n{% endblock %}\n")
    if not name.endswith(".html"):
        name += ".html"
    path = os.path.join(TEMPLATES_DIR, name)
    if os.path.exists(path):
        return jsonify({"error": "Template bestaat al"}), 400
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return jsonify({"status": "ok"})

# --- Vendor check (web) ---
@bp.route("/_vendor_check", methods=["GET"])
def vendor_check():
    """
    Controleer vendor-modules (Tiptap, TinyMCE, CodeMirror 6) en wkhtmltopdf.
    Retourneert JSON met status, ok/warnings/errors.
    """
    # Config laden (zelfde files als door de editor gebruikt)
    cfg = load_json(CONFIG_FILE)
    modes = load_json(MODES_FILE)
    if not isinstance(cfg, dict) or not isinstance(modes, dict):
        return jsonify({"status": "ERROR", "message": "Kon config/modes niet laden"}), 500

    def norm_base(p: str) -> str:
        p = (p or "").strip().lstrip("/")
        return os.path.join(ROOT_DIR, p.replace("/", os.sep))

    results = []

    def add(cat: str, name: str, path: str, ok: bool, msg: str = ""):
        results.append({
            "category": cat,
            "name": name,
            "path": path,
            "exists": bool(ok),
            "message": msg
        })

    # ---- Tiptap ----
    ui = (cfg.get("ui") or {}).get("editors", {})
    tiptap = (ui.get("tiptap") or {})
    t_base = norm_base(tiptap.get("path") or "static/vendor/tiptap")
    add("tiptap", "base-dir", t_base, os.path.isdir(t_base))
    tiptap_required = [
        ("core/index.js",          os.path.join(t_base, "core", "index.js")),
        ("starter-kit/index.js",   os.path.join(t_base, "starter-kit", "index.js")),
        ("ext-link/index.js",      os.path.join(t_base, "ext-link", "index.js")),
        ("ext-image/index.js",     os.path.join(t_base, "ext-image", "index.js")),
        ("ext-placeholder/index.js", os.path.join(t_base, "ext-placeholder", "index.js")),
    ]
    for label, p in tiptap_required:
        ok = os.path.isfile(p)
        add("tiptap", label, p, ok, "" if ok else "Ontbreekt: Tiptap module")

    # ---- TinyMCE ----
    tcfg = (ui.get("tinymce") or {})
    m_base = norm_base(tcfg.get("path") or "static/vendor/tinymce")
    add("tinymce", "base-dir", m_base, os.path.isdir(m_base))
    m_core = os.path.join(m_base, "tinymce.min.js")
    add("tinymce", "tinymce.min.js", m_core, os.path.isfile(m_core), "" if os.path.isfile(m_core) else "Ontbreekt: core")
    m_skins = os.path.join(m_base, "skins")
    m_plugins = os.path.join(m_base, "plugins")
    add("tinymce", "skins/", m_skins, os.path.isdir(m_skins), "" if os.path.isdir(m_skins) else "Ontbreekt: skins-map")
    add("tinymce", "plugins/", m_plugins, os.path.isdir(m_plugins), "" if os.path.isdir(m_plugins) else "Ontbreekt: plugins-map")

    # ---- CodeMirror 6 ----
    ccfg = (ui.get("codemirror") or {})
    c_base = norm_base(ccfg.get("path") or "static/vendor/codemirror")
    for rel in [os.path.join("view", "index.js"), os.path.join("state", "index.js")]:
        p = os.path.join(c_base, rel)
        add("codemirror", rel.replace("\\", "/"), p, os.path.isfile(p), "" if os.path.isfile(p) else "Ontbreekt: CM6 core module")

    expected_langs = set(["html", "css", "json", "xml", "markdown"])
    for mkey, mdef in (modes.get("modes") or {}).items():
        if (mdef or {}).get("wysiwyg") == "codemirror":
            syn = (mdef or {}).get("syntax")
            if syn:
                expected_langs.add(syn)

    lang_map = {
        "markdown": os.path.join(c_base, "lang-markdown", "index.js"),
        "html":     os.path.join(c_base, "lang-html", "index.js"),
        "css":      os.path.join(c_base, "lang-css", "index.js"),
        "json":     os.path.join(c_base, "lang-json", "index.js"),
        "xml":      os.path.join(c_base, "lang-xml", "index.js"),
    }
    for lang, p in lang_map.items():
        if lang in expected_langs:
            ok = os.path.isfile(p)
            add("codemirror", f"lang-{lang}/index.js", p, ok, "" if ok else "Ontbreekt: CM6 language module")

    # ---- wkhtmltopdf ----
    wk = (cfg.get("wkhtmltopdf") or {}).get("portable_path") or ""
    candidates = []
    if wk:
        candidates.append(norm_base(wk))
    candidates.extend([
        os.path.join(STATIC_DIR, "vendor", "wkhtmltox", "bin", "wkhtmltopdf.exe"),
        os.path.join(STATIC_DIR, "vendor", "wkhtmltox", "bin", "wkhtmltopdf"),
    ])
    found = None
    for c in candidates:
        if os.path.isfile(c):
            found = c
            break
    add("wkhtmltopdf", "binary", found or (candidates[0] if candidates else ""), bool(found),
        "" if found else "Niet gevonden. Pas 'wkhtmltopdf.portable_path' aan of plaats binary in static/vendor/wkhtmltox/bin")

    # ---- Samenvatting ----
    missing = [r for r in results if not r["exists"]]
    warnings = [r for r in results if (r["category"] == "tinymce" and r["name"] in ("skins/", "plugins/") and not r["exists"])]
    errors = [r for r in missing if r not in warnings]
    status = "OK"; code = 200
    if errors and warnings:
        status, code = "ERROR+WARN", 206
    elif errors:
        status, code = "ERROR", 206
    elif warnings:
        status, code = "WARN", 206

    return jsonify({
        "status": status,
        "total_checks": len(results),
        "errors": errors,
        "warnings": warnings,
        "ok": [r for r in results if r["exists"]],
    }), code

@bp.route("/delete_template", methods=["POST"])
def delete_template():
    req = request.get_json(force=True, silent=True) or {}
    name = safe_name(req.get("name", ""))
    if not name:
        return jsonify({"error": "No name"}), 400
    path = os.path.join(TEMPLATES_DIR, name)
    if not os.path.exists(path):
        return jsonify({"error": "Template niet gevonden"}), 404
    os.remove(path)
    return jsonify({"status": "ok"})

# -- Server-side ZIP export
@bp.route("/export", methods=["POST"])
def export_zip():
    req = request.get_json(force=True, silent=True) or {}
    files = req.get("files") or {}  # dict { "name.ext": "content" }
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(safe_name(name), content or "")
    mem.seek(0)
    return send_file(mem, mimetype="application/zip", as_attachment=True, download_name="i18n_export.zip")

# -- Live preview van een template (voor thumbnail-index)
@bp.route("/preview_template")
def preview_template():
    name = safe_name(request.args.get("name",""))
    if not name:
        return "Missing template name", 400
    html = render_template_to_html(name, {
        "meta": {"title":"Preview","theme":"dark"},
        "title": "Preview van " + name,
        "body": "<p>Dit is een voorbeeld van template <strong>"+name+"</strong>.</p>",
        "inline_css": ""
    })
    return html

# -------------------------------------------------------------------------------------------------
# Tool registration
# -------------------------------------------------------------------------------------------------
def register_tool(app):
    app.register_blueprint(bp)      # /i18n/*
    app.register_blueprint(shim_bp) # /* (root-level shims)
    current_app_logger = getattr(app, "logger", None)
    if current_app_logger:
        current_app_logger.info("[i18n_builder] registered (hybrid layout, css-inject, auto-backup, publish, pdf autodetect, test_pdf)")
    print("[i18n_builder] registered (hybrid layout, css-inject, auto-backup, publish, pdf autodetect, test_pdf)")

def register_web_routes(app):
    register_tool(app)

# -------------------------------------------------------------------------------------------------
# Standalone runner (hybride modus)
# -------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    # In Hub-modus wordt dit module geïmporteerd en roept master.register_tools()
    # onze register_web_routes(app) aan. In standalone maken we zélf een app.
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    register_tool(app)
    print("i18n_builder standalone op http://127.0.0.1:5004/i18n")
    app.run("127.0.0.1", 5004, debug=True)
