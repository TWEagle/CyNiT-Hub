#!/usr/bin/env python3
# tools/tree_exporter.py

"""
Tree Exporter (CyNiT-Hub)
- Server-side folder browser (geen uploads => geen 413)
- Tree preview + export (MD/HTML/TXT) met vinkjes
- Opslaan in exports/tree + overzichtspagina met Open/Download
- Werkt in Hub via register_web_routes(app)
- Werkt standalone via: python tools\\tree_exporter.py

Routes:
- GET/POST  /tree
- GET       /tree/exports
- GET       /tree/exports/open/<fname>
- GET       /tree/exports/dl/<fname>
"""

from __future__ import annotations

import html
import io
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from flask import Flask, render_template_string, request, send_file, abort

# Hub layout (zoals je andere tools)
from beheer.main_layout import render_page as hub_render_page


# =============================================================================
# Config
# =============================================================================

EXCLUDE_EXACT_DIRS = {
    "venv",
    ".venv",
    "__pycache__",
    ".git",
    "node_modules",
    "dist",
    "build",
}
EXCLUDE_DIR_SUBSTR = ["pycache"]  # vangt __pycache__, _pycache_, ...

EXCLUDE_FILE_SUFFIXES = {".pyc"}
EXCLUDE_FILE_NAMES = {".DS_Store", "Thumbs.db"}

MAX_ITEMS = 250_000  # safety cap voor megamappen


def _is_excluded_dir_name(name: str) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return False
    if n in EXCLUDE_EXACT_DIRS:
        return True
    return any(sub in n for sub in EXCLUDE_DIR_SUBSTR)


def _is_excluded_file_name(name: str) -> bool:
    if not name:
        return False
    if name in EXCLUDE_FILE_NAMES:
        return True
    low = name.lower()
    return any(low.endswith(suf) for suf in EXCLUDE_FILE_SUFFIXES)


def _safe_stem(name: str) -> str:
    name = (name or "tree").strip()
    name = re.sub(r"[^\w\-\.]+", "_", name, flags=re.UNICODE)
    name = re.sub(r"_+", "_", name).strip("._-")
    return (name[:80] or "tree")


def _exports_dir() -> Path:
    # project root = parent of /tools
    p = Path(__file__).resolve().parents[1] / "exports" / "tree"
    p.mkdir(parents=True, exist_ok=True)
    return p


# =============================================================================
# Tree model + rendering
# =============================================================================

@dataclass
class Node:
    dirs: Dict[str, "Node"] = field(default_factory=dict)
    files: List[str] = field(default_factory=list)


def _sort_tree(node: Node) -> None:
    node.files = sorted(set(node.files), key=lambda s: s.lower())
    for k in sorted(list(node.dirs.keys()), key=lambda s: s.lower()):
        _sort_tree(node.dirs[k])


def _render_tree(root_name: str, root: Node, ascii_tree: bool, show_files: bool) -> str:
    if ascii_tree:
        TEE, ELBOW, PIPE, BLANK = "|-- ", "\\-- ", "|   ", "    "
    else:
        TEE, ELBOW, PIPE, BLANK = "├── ", "└── ", "│   ", "    "

    lines: List[str] = [f"{root_name}/"]

    def rec(node: Node, prefix: str) -> None:
        entries: List[Tuple[bool, str]] = []  # (is_dir, name)

        for d in sorted(node.dirs.keys(), key=lambda s: s.lower()):
            entries.append((True, d))
        if show_files:
            for f in node.files:
                entries.append((False, f))

        for idx, (is_dir, name) in enumerate(entries):
            last = (idx == len(entries) - 1)
            branch = ELBOW if last else TEE
            if is_dir:
                lines.append(f"{prefix}{branch}{name}/")
                next_prefix = prefix + (BLANK if last else PIPE)
                rec(node.dirs[name], next_prefix)
            else:
                lines.append(f"{prefix}{branch}{name}")

    rec(root, "")
    return "\n".join(lines) + "\n"


# =============================================================================
# Server-side scan
# =============================================================================

def _scan_folder_build_tree(folder: Path, include_files: bool) -> Tuple[Node, int]:
    """
    Build tree by scanning folder on local filesystem.
    Returns: (tree_root, item_count)
    """
    tree = Node()
    count = 0
    folder = folder.resolve()

    for root_dir, dirnames, filenames in os.walk(folder):
        root_path = Path(root_dir)

        # prune excluded dirs
        pruned = []
        for d in dirnames:
            if _is_excluded_dir_name(d):
                continue
            pruned.append(d)
        dirnames[:] = pruned

        # guard
        count += len(dirnames) + (len(filenames) if include_files else 0)
        if count > MAX_ITEMS:
            break

        # ensure directory nodes exist
        rel_dir = root_path.relative_to(folder).as_posix()
        cur = tree
        if rel_dir and rel_dir != ".":
            for seg in [p for p in rel_dir.split("/") if p]:
                if _is_excluded_dir_name(seg):
                    cur = None  # type: ignore
                    break
                cur = cur.dirs.setdefault(seg, Node())
            if cur is None:
                continue

        if not include_files:
            continue

        for fn in filenames:
            if _is_excluded_file_name(fn):
                continue
            full = root_path / fn
            try:
                rel = full.relative_to(folder).as_posix()
            except Exception:
                continue
            parts = [p for p in rel.split("/") if p]
            if any(_is_excluded_dir_name(seg) for seg in parts[:-1]):
                continue

            cur2 = tree
            for seg in parts[:-1]:
                cur2 = cur2.dirs.setdefault(seg, Node())
            cur2.files.append(parts[-1])

    _sort_tree(tree)
    return tree, count


# =============================================================================
# Export builders
# =============================================================================

def _build_txt(tree_text: str) -> bytes:
    return (tree_text if tree_text.endswith("\n") else tree_text + "\n").encode("utf-8")


def _build_md(tree_text: str, root_name: str, path_str: str) -> bytes:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md = (
        f"# Tree Export\n\n"
        f"**Root**: `{root_name}`  \n"
        f"**Path**: `{path_str}`  \n"
        f"**Generated**: {now}\n\n"
        f"```text\n{tree_text}```\n"
    )
    return md.encode("utf-8")


def _build_html(tree_text: str, root_name: str, path_str: str) -> bytes:
    # standalone HTML (geen hub styling dependencies)
    esc = html.escape(tree_text)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    doc = f"""<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <title>Tree Export - {html.escape(root_name)}</title>
  <style>
    body {{
      font-family: system-ui, Segoe UI, Arial, sans-serif;
      margin: 20px;
      background: #0b0f12;
      color: #e6f1ff;
    }}
    .meta {{ color: #9fb3b3; margin: 10px 0 14px; }}
    pre {{
      background: #050708;
      border: 1px solid rgba(255,255,255,.12);
      border-radius: 12px;
      padding: 14px 16px;
      overflow: auto;
      white-space: pre;
      line-height: 1.35;
      font-family: ui-monospace, Consolas, "Courier New", monospace;
      font-size: 13px;
      color: #7CFF7C;
    }}
    code {{ background: rgba(255,255,255,.08); padding: 1px 6px; border-radius: 6px; }}
  </style>
</head>
<body>
  <h1>Tree Export</h1>
  <div class="meta">
    Root: <code>{html.escape(root_name)}</code><br>
    Path: <code>{html.escape(path_str)}</code><br>
    Generated: {now}
  </div>
  <pre>{esc}</pre>
</body>
</html>
"""
    return doc.encode("utf-8")


# =============================================================================
# Folder browser helpers
# =============================================================================

def _norm_path(p: str) -> str:
    return (p or "").strip().strip('"')


def _resolve_existing_dir(p: str) -> Optional[Path]:
    p = _norm_path(p)
    if not p:
        return None
    try:
        pp = Path(p).expanduser()
        if pp.exists() and pp.is_dir():
            return pp.resolve()
    except Exception:
        return None
    return None


def _default_start_dir() -> Path:
    return Path(__file__).resolve().parents[1]  # project root


def _list_subdirs(cur: Path) -> List[Path]:
    out: List[Path] = []
    try:
        for child in cur.iterdir():
            if child.is_dir() and not _is_excluded_dir_name(child.name):
                out.append(child)
    except Exception:
        return []
    out.sort(key=lambda p: p.name.lower())
    return out


# =============================================================================
# UI
# =============================================================================

CONTENT_TEMPLATE = r"""
<style>
.tree-wrap { max-width: 1100px; margin: 0 auto; }
.card {
  background: rgba(10,15,18,.85); border-radius: 12px; padding: 16px 20px; margin-bottom: 18px;
  border: 1px solid var(--border, rgba(255,255,255,.10));
}
.muted { color: var(--muted, #9fb3b3); }
.error-box {
  background: rgba(255,0,0,.12); border: 1px solid rgba(255,0,0,.35);
  color: #ffd6d6; padding: 10px 12px; border-radius: 10px; margin-bottom: 12px;
  font-size: 0.92rem; white-space: pre-wrap;
}
.ok-box {
  background: rgba(0,255,100,.10); border: 1px solid rgba(0,255,100,.25);
  color: #ccffd9; padding: 10px 12px; border-radius: 10px; margin-bottom: 12px;
  font-size: 0.92rem; white-space: pre-wrap;
}
.in, select {
  width: 100%; box-sizing: border-box; padding: 10px 12px;
  border-radius: 10px; background: #111; color: #fff;
  border: 1px solid var(--border, rgba(255,255,255,.18));
}
.grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.btn {
  display: inline-flex; align-items: center; justify-content: center;
  gap: 8px; padding: 10px 14px; border-radius: 12px;
  border: 1px solid var(--border, rgba(255,255,255,.18));
  background: rgba(255,255,255,.06); color: #fff; cursor: pointer;
}
.btn:hover { background: rgba(255,255,255,.10); }
.btn2 {
  display: inline-flex; align-items: center; justify-content: center;
  gap: 8px; padding: 8px 12px; border-radius: 10px;
  border: 1px solid var(--border, rgba(255,255,255,.14));
  background: rgba(255,255,255,.04); color: #fff; cursor: pointer;
  font-size: 0.95rem;
}
.btn2:hover { background: rgba(255,255,255,.08); }
.pill {
  display:inline-block; padding: 3px 9px; border-radius: 999px;
  background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.10);
  color: #dce7e7; font-size: 0.86rem;
}
.browser {
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 12px;
  overflow: hidden;
}
.browser-head {
  display:flex; gap:10px; align-items:center; justify-content:space-between;
  padding: 10px 12px;
  background: rgba(255,255,255,.03);
  border-bottom: 1px solid rgba(255,255,255,.10);
}
.path {
  font-family: ui-monospace, Consolas, "Courier New", monospace;
  font-size: 0.95rem;
  word-break: break-all;
}
.dirlist { max-height: 360px; overflow:auto; background: rgba(0,0,0,.15); }
.dirrow {
  display:flex; justify-content:space-between; align-items:center;
  padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,.06);
}
.dirrow:last-child { border-bottom: none; }
.dirname { display:flex; align-items:center; gap:10px; }
.dirname code { background: rgba(255,255,255,.06); padding: 2px 6px; border-radius: 8px; }
.actions { display:flex; gap:8px; flex-wrap:wrap; }
.small { font-size: 0.9rem; }
pre.preview {
  white-space: pre; overflow:auto; padding: 12px; border-radius: 12px;
  border: 1px solid rgba(255,255,255,.10);
  background: rgba(0,0,0,.30);
}
</style>

<script>
function goToPath(path) {
  const url = new URL(window.location.href);
  url.searchParams.set("path", path);
  window.location.href = url.toString();
}
function useThisFolder() {
  const inp = document.getElementById("server_path");
  const cur = document.getElementById("current_path");
  if (inp && cur) inp.value = cur.dataset.path;
}
function goUp() {
  const cur = document.getElementById("current_path");
  if (!cur) return;
  goToPath(cur.dataset.parent);
}
</script>

<div class="tree-wrap">
  <h1>Tree Exporter</h1>
  <p class="muted">
    Server-side folder browser (geen uploads) → export naar
    <span class="pill">.md</span> <span class="pill">.html</span> <span class="pill">.txt</span>.
  </p>

  {% if err %}
    <div class="error-box">{{ err }}</div>
  {% endif %}
  {% if ok %}
    <div class="ok-box">{{ ok }}</div>
  {% endif %}

  <div class="card">
    <h2>1) Kies map</h2>
    <p class="muted small">
      Excludes: <code>venv</code> / <code>.venv</code> / <code>__pycache__</code> / <code>*pycache*</code> /
      <code>.git</code> / <code>node_modules</code> / <code>dist</code> / <code>build</code> / <code>*.pyc</code>
    </p>

    <div class="browser">
      <div class="browser-head">
        <div class="path" id="current_path" data-path="{{ current_path }}" data-parent="{{ parent_path }}">
          {{ current_path }}
        </div>
        <div class="actions">
          <button class="btn2" type="button" onclick="goUp()">⬆ Up</button>
          <button class="btn2" type="button" onclick="useThisFolder()">✅ Gebruik deze map</button>
          <a class="btn2" href="/tree/exports" style="text-decoration:none;">📂 Open exports</a>
        </div>
      </div>

      <div class="dirlist">
        {% if not subdirs %}
          <div class="dirrow"><div class="muted">Geen submappen (of geen toegang).</div></div>
        {% endif %}

        {% for d in subdirs %}
          <div class="dirrow">
            <div class="dirname">
              <span>📁</span>
              <code>{{ d.name }}</code>
            </div>
            <div class="actions">
              <button class="btn2" type="button" onclick="goToPath('{{ d.full }}')">Open</button>
            </div>
          </div>
        {% endfor %}
      </div>
    </div>

    <div class="grid-2" style="margin-top: 10px;">
      <div>
        <label class="small muted">Pad (je kan dit ook manueel typen)</label>
        <input class="in" id="server_path" name="server_path" value="{{ selected_path }}" form="exportForm">
      </div>
      <div>
        <label class="small muted">Snelle start</label>
        <div class="grid-2">
          <button class="btn2" type="button" onclick="goToPath('{{ start_project }}')">📌 Project root</button>
          <button class="btn2" type="button" onclick="goToPath('{{ start_home }}')">🏠 Home</button>
        </div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>2) Export</h2>

    <form id="exportForm" method="post" action="/tree">
      <div class="grid-3">
        <div>
          <label><strong>Tree stijl</strong></label>
          <select name="style" class="in">
            <option value="unicode" {% if style=='unicode' %}selected{% endif %}>Unicode (├── └── │)</option>
            <option value="ascii" {% if style=='ascii' %}selected{% endif %}>ASCII (|-- \-- |)</option>
          </select>
        </div>

        <div>
          <label><strong>Bestanden tonen</strong></label>
          <select name="show_files" class="in">
            <option value="1" {% if show_files %}selected{% endif %}>Ja</option>
            <option value="0" {% if not show_files %}selected{% endif %}>Nee (enkel mappen)</option>
          </select>
        </div>

        <div>
          <label><strong>Opslaan in exports/</strong></label>
          <select name="save_mode" class="in">
            <option value="0" {% if save_mode=='0' %}selected{% endif %}>Nee</option>
            <option value="1" {% if save_mode=='1' %}selected{% endif %}>Ja</option>
          </select>
        </div>
      </div>

      <div class="grid-3" style="margin-top: 10px;">
        <div>
          <label><strong>Export formats</strong></label>
          <label class="small"><input type="checkbox" name="fmt" value="md" {% if 'md' in fmts %}checked{% endif %}> MD</label><br>
          <label class="small"><input type="checkbox" name="fmt" value="html" {% if 'html' in fmts %}checked{% endif %}> HTML</label><br>
          <label class="small"><input type="checkbox" name="fmt" value="txt" {% if 'txt' in fmts %}checked{% endif %}> TXT</label>
          <div class="muted small" style="margin-top:6px;">Meerdere formats → download als ZIP.</div>
        </div>

        <div>
          <label><strong>Actie</strong></label>
          <select name="action" class="in">
            <option value="preview" {% if action=='preview' %}selected{% endif %}>Preview</option>
            <option value="download" {% if action=='download' %}selected{% endif %}>Download</option>
            <option value="save" {% if action=='save' %}selected{% endif %}>Opslaan in exports/</option>
          </select>
          <div class="muted small" style="margin-top:6px;">Save-mode kan je ook aanzetten hierboven.</div>
        </div>

        <div>
          <label><strong>&nbsp;</strong></label>
          <button class="btn" type="submit">▶ Uitvoeren</button>
        </div>
      </div>
    </form>

    <p class="muted small" style="margin-top: 10px;">
      (Safety) Als een map gigantisch is, stopt hij na {{ max_items }} items.
    </p>
  </div>

  {% if preview_text %}
    <div class="card">
      <h2>Preview</h2>
      <p class="muted small">Path: <code>{{ preview_path }}</code></p>
      <pre class="preview">{{ preview_text }}</pre>
    </div>
  {% endif %}
</div>
"""


def _render(
    *,
    err: Optional[str] = None,
    ok: Optional[str] = None,
    current_dir: Optional[Path] = None,
    selected_path: Optional[str] = None,
    style: str = "unicode",
    show_files: bool = True,
    action: str = "preview",
    save_mode: str = "0",
    fmts: Optional[List[str]] = None,
    preview_text: str = "",
    preview_path: str = "",
) -> str:
    cur = current_dir or _default_start_dir()
    parent = cur.parent if cur.parent != cur else cur

    subdirs = [{"name": d.name, "full": str(d)} for d in _list_subdirs(cur)]

    start_project = str(_default_start_dir())
    start_home = str(Path.home())

    content_html = render_template_string(
        CONTENT_TEMPLATE,
        err=err,
        ok=ok,
        current_path=str(cur),
        parent_path=str(parent),
        selected_path=(selected_path or str(cur)),
        subdirs=subdirs,
        style=style,
        show_files=show_files,
        action=action,
        save_mode=save_mode,
        fmts=fmts or ["md"],
        start_project=start_project,
        start_home=start_home,
        max_items=MAX_ITEMS,
        preview_text=preview_text,
        preview_path=preview_path,
    )
    return hub_render_page(title="Tree Exporter", content_html=content_html)


# =============================================================================
# Exports list pages
# =============================================================================

EXPORTS_TEMPLATE = r"""
<style>
.wrap { max-width: 1100px; margin: 0 auto; }
.card {
  background: rgba(10,15,18,.85); border-radius: 12px; padding: 16px 20px; margin-bottom: 18px;
  border: 1px solid var(--border, rgba(255,255,255,.10));
}
table { width:100%; border-collapse: collapse; }
th, td { padding: 10px; border-bottom: 1px solid rgba(255,255,255,.08); text-align:left; }
code { background: rgba(255,255,255,.06); padding: 2px 6px; border-radius: 8px; }
.muted { color: var(--muted, #9fb3b3); }
.actions { display:flex; gap:10px; flex-wrap:wrap; }
.btn2 {
  display: inline-flex; align-items:center; justify-content:center;
  padding: 8px 12px; border-radius: 10px;
  border: 1px solid rgba(255,255,255,.14);
  background: rgba(255,255,255,.04); color: #fff; cursor: pointer;
  text-decoration:none;
}
.btn2:hover { background: rgba(255,255,255,.08); }
</style>

<div class="wrap">
  <h1>Tree Exports</h1>
  <p class="muted">Map: <code>{{ exports_dir }}</code></p>

  <div class="card">
    {% if not rows %}
      <div class="muted">Nog geen exports.</div>
    {% else %}
      <table>
        <thead>
          <tr>
            <th>Bestand</th>
            <th>Gewijzigd</th>
            <th>Grootte</th>
            <th>Acties</th>
          </tr>
        </thead>
        <tbody>
          {% for r in rows %}
          <tr>
            <td><code>{{ r.name }}</code></td>
            <td class="muted">{{ r.mtime }}</td>
            <td class="muted">{{ r.size }} bytes</td>
            <td>
              <div class="actions">
                <a class="btn2" href="{{ r.open_url }}" target="_blank">Open</a>
                <a class="btn2" href="{{ r.dl_url }}">Download</a>
              </div>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    {% endif %}
  </div>

  <a class="btn2" href="/tree">⬅ Terug</a>
</div>
"""


def _render_exports(rows: List[Dict[str, str]]) -> str:
    content = render_template_string(
        EXPORTS_TEMPLATE,
        rows=rows,
        exports_dir=str(_exports_dir()),
    )
    return hub_render_page(title="Tree Exports", content_html=content)


def _safe_exports_path(fname: str) -> Path:
    base = _exports_dir().resolve()
    p = (base / fname).resolve()
    if base not in p.parents or not p.exists() or not p.is_file():
        abort(404)
    return p


# =============================================================================
# Routes
# =============================================================================

def register_web_routes(app: Flask):
    @app.route("/tree", methods=["GET", "POST"])
    def tree_index():
        # folder browser path (GET param)
        requested_path = _resolve_existing_dir(request.args.get("path") or "") or _default_start_dir()

        if request.method == "GET":
            return _render(
                current_dir=requested_path,
                selected_path=str(requested_path),
                style="unicode",
                show_files=True,
                action="preview",
                save_mode="0",
                fmts=["md"],
                preview_text="",
                preview_path="",
            )

        # POST
        server_path = _norm_path(request.form.get("server_path") or "")
        folder = _resolve_existing_dir(server_path)

        style = (request.form.get("style") or "unicode").strip().lower()
        show_files = (request.form.get("show_files") or "1") == "1"
        action = (request.form.get("action") or "preview").strip().lower()
        save_mode = (request.form.get("save_mode") or "0").strip()
        fmts = request.form.getlist("fmt") or ["md"]
        fmts = [f for f in fmts if f in ("md", "html", "txt")]
        if not fmts:
            fmts = ["md"]

        if folder is None:
            return _render(
                err=f"Server pad bestaat niet of is geen map: {server_path}",
                current_dir=requested_path,
                selected_path=server_path or str(requested_path),
                style=style,
                show_files=show_files,
                action=action,
                save_mode=save_mode,
                fmts=fmts,
            )

        # Build tree
        try:
            tree_root, count = _scan_folder_build_tree(folder, include_files=show_files)
            warn = ""
            if count > MAX_ITEMS:
                warn = f"⚠️ Grote map: scan afgekapt na {MAX_ITEMS} items."
        except Exception as exc:
            return _render(
                err=f"Fout bij scannen:\n{exc}",
                current_dir=folder,
                selected_path=str(folder),
                style=style,
                show_files=show_files,
                action=action,
                save_mode=save_mode,
                fmts=fmts,
            )

        ascii_tree = (style == "ascii")
        tree_text = _render_tree(folder.name, tree_root, ascii_tree=ascii_tree, show_files=show_files)
        path_str = str(folder)

        # Preview-only
        if action == "preview":
            return _render(
                ok=("✅ Preview gemaakt. " + warn).strip(),
                current_dir=folder,
                selected_path=str(folder),
                style=style,
                show_files=show_files,
                action=action,
                save_mode=save_mode,
                fmts=fmts,
                preview_text=tree_text,
                preview_path=path_str,
            )

        # Prepare bytes per format
        def bytes_for(fmt: str) -> Tuple[str, bytes, str]:
            if fmt == "md":
                b = _build_md(tree_text, folder.name, path_str)
                return (".md", b, "text/markdown; charset=utf-8")
            if fmt == "html":
                b = _build_html(tree_text, folder.name, path_str)
                return (".html", b, "text/html; charset=utf-8")
            b = _build_txt(tree_text)
            return (".txt", b, "text/plain; charset=utf-8")

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        stem = _safe_stem(folder.name)
        base_name = f"tree_{stem}_{ts}"

        # Save if requested (either action==save OR save_mode==1)
        saved_files: List[str] = []
        if action == "save" or save_mode == "1":
            base = _exports_dir()
            for f in fmts:
                ext, b, _ = bytes_for(f)
                name = f"{base_name}{ext}"
                (base / name).write_bytes(b)
                saved_files.append(name)

        # If action==save: show preview + saved msg (no download)
        if action == "save":
            msg = "✅ Opgeslagen: " + (", ".join(saved_files) if saved_files else "(niets)")
            if warn:
                msg += f" · {warn}"
            return _render(
                ok=msg,
                current_dir=folder,
                selected_path=str(folder),
                style=style,
                show_files=show_files,
                action=action,
                save_mode=save_mode,
                fmts=fmts,
                preview_text=tree_text,
                preview_path=path_str,
            )

        # action==download
        if len(fmts) == 1:
            ext, b, mime = bytes_for(fmts[0])
            dl_name = f"{stem}{ext}"
            bio = io.BytesIO(b)
            bio.seek(0)
            return send_file(bio, as_attachment=True, download_name=dl_name, mimetype=mime)

        # multiple -> zip
        buf = io.BytesIO()
        import zipfile
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for f in fmts:
                ext, b, _ = bytes_for(f)
                z.writestr(f"{base_name}{ext}", b)
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f"{base_name}.zip", mimetype="application/zip")

    @app.get("/tree/exports")
    def tree_exports():
        base = _exports_dir()
        rows = []
        files = sorted(base.glob("tree_*.*"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]
        for p in files:
            rows.append({
                "name": p.name,
                "size": str(p.stat().st_size),
                "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "open_url": f"/tree/exports/open/{p.name}",
                "dl_url": f"/tree/exports/dl/{p.name}",
            })
        return _render_exports(rows)

    @app.get("/tree/exports/open/<path:fname>")
    def tree_exports_open(fname: str):
        p = _safe_exports_path(fname)
        ext = p.suffix.lower()
        if ext == ".html":
            return send_file(p, mimetype="text/html", as_attachment=False)
        if ext == ".md":
            return send_file(p, mimetype="text/markdown", as_attachment=False)
        return send_file(p, mimetype="text/plain", as_attachment=False)

    @app.get("/tree/exports/dl/<path:fname>")
    def tree_exports_dl(fname: str):
        p = _safe_exports_path(fname)
        return send_file(p, as_attachment=True, download_name=p.name)


# =============================================================================
# Standalone mode
# =============================================================================

if __name__ == "__main__":
    # Zorg dat project root in sys.path zit zodat "beheer.*" import werkt
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    app = Flask("Tree Exporter (standalone)")
    register_web_routes(app)

    print("🌳 Tree Exporter standalone: http://127.0.0.1:5007/tree")
    app.run("127.0.0.1", 5007, debug=True)
