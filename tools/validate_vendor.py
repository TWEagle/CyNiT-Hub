
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_vendor.py — controleert lokale vendor-modules voor i18n_builder (Hub + standalone)

Wat wordt gevalideerd (op basis van config/i18n_builder.json + i18n_modes.json):
- Tiptap:   core, starter-kit, ext-link, ext-image, ext-placeholder
- TinyMCE:  basis (tinymce.min.js) en skins/plugins map
- CodeMirror 6: view/state + lang-* modules (html, css, json, xml, markdown)
- wkhtmltopdf: uitvoerbaar pad (Windows/Linux)

Exitcodes:
 0 = OK, 2 = waarschuwingen, 3 = fouten
"""

from __future__ import annotations
import os, sys, json, argparse
from typing import Dict, Any, List, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_DIR = os.path.join(ROOT, "config")
STATIC_DIR = os.path.join(ROOT, "static")

DEFAULT_CFG = os.path.join(CONFIG_DIR, "i18n_builder.json")
DEFAULT_MODES = os.path.join(CONFIG_DIR, "i18n_modes.json")

def load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"__error__": f"Kon JSON niet laden ({path}): {e}"}

def norm_base(p: str) -> str:
    """Maak padconfig robuust en los 'static/...' en '/static/...' op naar lokale root."""
    if not p:
        return ""
    p = p.strip().lstrip("/")  # laat zowel '/static/...' als 'static/...' toe
    return os.path.join(ROOT, p.replace("/", os.sep))

def check_file(path: str) -> Tuple[bool, str]:
    return (os.path.isfile(path), path)

def check_dir(path: str) -> Tuple[bool, str]:
    return (os.path.isdir(path), path)

def add_result(results: List[Dict[str, Any]], ok: bool, cat: str, name: str, path: str, msg: str = ""):
    results.append({
        "category": cat,
        "name": name,
        "exists": bool(ok),
        "path": path,
        "message": msg
    })

def check_tiptap(cfg: Dict[str, Any], results: List[Dict[str, Any]]):
    ui = (cfg.get("ui") or {}).get("editors", {})
    tiptap = (ui.get("tiptap") or {})
    base = norm_base(tiptap.get("path") or "static/vendor/tiptap")
    mods = (tiptap.get("modules") or {})
    # Verwachte modules volgens je hybride JS
    required = {
        "core/index.js":          os.path.join(base, "core", "index.js"),
        "starter-kit/index.js":   os.path.join(base, "starter-kit", "index.js"),
        "ext-link/index.js":      os.path.join(base, "ext-link", "index.js"),
        "ext-image/index.js":     os.path.join(base, "ext-image", "index.js"),
        "ext-placeholder/index.js": os.path.join(base, "ext-placeholder", "index.js"),
        # prosemirror shims staan onder tiptap/prosemirror/*.js en worden door Flask-routes bediend
    }
    add_result(results, os.path.isdir(base), "tiptap", "base-dir", base)
    for label, abspath in required.items():
        ok, p = check_file(abspath)
        add_result(results, ok, "tiptap", label, p, "" if ok else "Ontbreekt: Tiptap module")

def check_tinymce(cfg: Dict[str, Any], results: List[Dict[str, Any]]):
    ui = (cfg.get("ui") or {}).get("editors", {})
    tcfg = (ui.get("tinymce") or {})
    base = norm_base(tcfg.get("path") or "static/vendor/tinymce")
    core = os.path.join(base, "tinymce.min.js")
    skins = os.path.join(base, "skins")
    plugins = os.path.join(base, "plugins")
    add_result(results, os.path.isdir(base), "tinymce", "base-dir", base)
    ok, p = check_file(core)
    add_result(results, ok, "tinymce", "tinymce.min.js", p, "" if ok else "Ontbreekt: tinymce core")
    add_result(results, os.path.isdir(skins), "tinymce", "skins/", skins, "" if os.path.isdir(skins) else "Ontbreekt: skins-map")
    add_result(results, os.path.isdir(plugins), "tinymce", "plugins/", plugins, "" if os.path.isdir(plugins) else "Ontbreekt: plugins-map")

def check_codemirror(cfg: Dict[str, Any], results: List[Dict[str, Any]], modes_cfg: Dict[str, Any]):
    ui = (cfg.get("ui") or {}).get("editors", {})
    ccfg = (ui.get("codemirror") or {})
    base = norm_base(ccfg.get("path") or "static/vendor/codemirror")
    # basis
    required_files = [
        os.path.join(base, "view", "index.js"),
        os.path.join(base, "state", "index.js"),
    ]
    for p in required_files:
        ok, abspath = check_file(p)
        add_result(results, ok, "codemirror", os.path.relpath(p, ROOT), abspath, "" if ok else "Ontbreekt: CM6 core module")

    # talen: combineer uit config en i18n_modes
    expected_langs = set(["html","css","json","xml","markdown"])
    for mkey, mdef in (modes_cfg.get("modes") or {}).items():
        if (mdef or {}).get("wysiwyg") == "codemirror":
            syn = (mdef or {}).get("syntax")
            if syn: expected_langs.add(syn)

    lang_map = {
        "markdown": os.path.join(base, "lang-markdown", "index.js"),
        "html":     os.path.join(base, "lang-html", "index.js"),
        "css":      os.path.join(base, "lang-css", "index.js"),
        "json":     os.path.join(base, "lang-json", "index.js"),
        "xml":      os.path.join(base, "lang-xml", "index.js"),
        # voeg hier extra talen toe indien je die toevoegt in vendor
    }
    for lang, p in lang_map.items():
        if lang in expected_langs:
            ok, abspath = check_file(p)
            add_result(results, ok, "codemirror", f"lang-{lang}/index.js", abspath, "" if ok else "Ontbreekt: CM6 language module")

def check_wkhtmltopdf(cfg: Dict[str, Any], results: List[Dict[str, Any]]):
    wk = (cfg.get("wkhtmltopdf") or {}).get("portable_path") or ""
    # probeer portable path en standaard vendor-folder
    candidates = []
    if wk:
        wk_norm = norm_base(wk)
        candidates.append(wk_norm)
    # fallback in static/vendor
    win = os.path.join(STATIC_DIR, "vendor", "wkhtmltox", "bin", "wkhtmltopdf.exe")
    lin = os.path.join(STATIC_DIR, "vendor", "wkhtmltox", "bin", "wkhtmltopdf")
    candidates.extend([win, lin])

    found = None
    for c in candidates:
        if os.path.isfile(c):
            found = c
            break
    add_result(results, found is not None, "wkhtmltopdf", "binary", found or (candidates[0] if candidates else ""), "" if found else "Niet gevonden. Pas 'wkhtmltopdf.portable_path' aan of plaats binary in static/vendor/wkhtmltox/bin")

def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(results)
    missing = [r for r in results if not r["exists"]]
    warnings = []
    # hint: skins/plugins zijn waarschuwingen (tool kan starten, UI is dan beperkt)
    for r in results:
        if r["category"] == "tinymce" and r["name"] in ("skins/","plugins/") and not r["exists"]:
            warnings.append(r)
    # echte fouten: core-bestanden/module ontbreekt
    errors = [r for r in missing if r not in warnings]
    status = "OK"
    exit_code = 0
    if errors and warnings:
        status, exit_code = "ERROR+WARN", 3
    elif errors:
        status, exit_code = "ERROR", 3
    elif warnings:
        status, exit_code = "WARN", 2
    return {
        "status": status,
        "exit_code": exit_code,
        "total_checks": total,
        "errors": errors,
        "warnings": warnings,
        "ok": [r for r in results if r["exists"]],
    }

def pretty_print(summary: Dict[str, Any]):
    import shutil
    cols = shutil.get_terminal_size((120, 20)).columns
    line = "-" * min(cols, 120)
    print(line)
    print(f"Vendor Validator — Status: {summary['status']}")
    print(line)

    def emit(items: List[Dict[str, Any]], title: str):
        if not items:
            return
        print(f"\n{title}:")
        for r in items:
            p = r["path"]
            print(f"  - [{r['category']}] {r['name']} -> {'OK' if r['exists'] else 'FAIL'}")
            if not r["exists"]:
                print(f"    path : {p}")
                if r["message"]:
                    print(f"    note : {r['message']}")

    emit(summary["errors"], "❌ Fouten")
    emit(summary["warnings"], "⚠ Waarschuwingen")

    oks = summary["ok"]
    if oks:
        print("\n✅ In orde:")
        for r in oks:
            print(f"  - [{r['category']}] {r['name']} -> OK")

    print(f"\nChecks: {summary['total_checks']}")
    print(line)

def main():
    ap = argparse.ArgumentParser(description="Valideer i18n_builder vendor modules (Hub + standalone).")
    ap.add_argument("--root", default=ROOT, help="Project root (default: repo root)")
    ap.add_argument("--config", default=DEFAULT_CFG, help="Pad naar i18n_builder.json")
    ap.add_argument("--modes", default=DEFAULT_MODES, help="Pad naar i18n_modes.json")
    ap.add_argument("--json", action="store_true", help="JSON output i.p.v. tekst")
    args = ap.parse_args()

    # root wisselen indien gevraagd
    if args.root:
        os.chdir(args.root)

    cfg = load_json(args.config)
    modes = load_json(args.modes)
    if "__error__" in cfg or "__error__" in modes:
        print(json.dumps({"status":"ERROR","config_error":cfg.get("__error__"),"modes_error":modes.get("__error__")}, ensure_ascii=False, indent=2))
        sys.exit(3)

    results: List[Dict[str, Any]] = []
    check_tiptap(cfg, results)
    check_tinymce(cfg, results)
    check_codemirror(cfg, results, modes)
    check_wkhtmltopdf(cfg, results)

    summary = summarize(results)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        pretty_print(summary)
    sys.exit(summary["exit_code"])

if __name__ == "__main__":
    main()
