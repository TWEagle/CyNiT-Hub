
# tools/convert_to_ico.py
# !/usr/bin/env python3
"""
Image → ICO Converter (CyNiT Hub, content-only).
- Route: GET/POST /ico
- Upload PNG/JPG/GIF/WebP en download een multi-size .ico
- Kies sizes (comma-separated), mode ("contain" | "crop"), en optionele padding

Afhankelijkheden:
- Pillow  (pip install pillow)
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import List, Tuple, Optional

from flask import Flask, request, render_template_string, send_file, make_response
from beheer.main_layout import render_page as hub_render_page  # hub layout

try:
    from PIL import Image, ImageOps
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageOps = None  # type: ignore

# ====== Defaults ======
DEFAULT_SIZES = "16,24,32,48,64,96,128,256"


def _parse_sizes(s: str) -> List[int]:
    out: List[int] = []
    for part in (s or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
        except ValueError:
            continue
        if 8 <= n <= 512 and n not in out:
            out.append(n)
    if not out:
        out = [16, 24, 32, 48, 64, 96, 128, 256]
    return sorted(out)


def _safe_stem(filename: str) -> str:
    stem = Path(filename or "icon").stem or "icon"
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in stem)
    return safe[:80] or "icon"


def _make_square(img: "Image.Image", pad_color=(0, 0, 0, 0)) -> "Image.Image":
    """Center-pad naar vierkant zonder vervorming."""
    w, h = img.size
    if w == h:
        return img
    side = max(w, h)
    out = Image.new("RGBA", (side, side), pad_color)
    out.paste(img, ((side - w) // 2, (side - h) // 2))
    return out


def _contain(img: "Image.Image", size: int) -> "Image.Image":
    """Schaal proportioneel tot binnen (size x size)."""
    return ImageOps.contain(img, (size, size), method=Image.LANCZOS)


def _center_on_canvas(img: "Image.Image", size: int, bg=(0, 0, 0, 0)) -> "Image.Image":
    """Plaats midden op (size x size) canvas (handig na contain)."""
    out = Image.new("RGBA", (size, size), bg)
    w, h = img.size
    out.paste(img, ((size - w) // 2, (size - h) // 2), img if img.mode == "RGBA" else None)
    return out


def _build_ico_bytes(img: "Image.Image", sizes: List[int], mode: str, pad: bool) -> bytes:
    """
    mode:
      - "crop"    -> square crop (vult canvas)
      - "contain" -> proportioneel + padding naar vierkant
    pad:
      - True  -> bron eerst vierkant pad-en vóór resizen (handig bij extreem breed/hoog)
    """
    if img.mode not in ("RGBA", "RGB"):
        img = img.convert("RGBA")
    else:
        img = img.convert("RGBA")

    # Normalizeer oriëntatie (EXIF)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    if pad:
        img = _make_square(img)

    ico_imgs: List["Image.Image"] = []
    for s in sizes:
        if mode == "contain":
            scaled = _contain(img, s)
            framed = _center_on_canvas(scaled, s)
            ico_imgs.append(framed)
        else:
            # crop naar vierkant en resize
            cropped = ImageOps.fit(img, (s, s), method=Image.LANCZOS, centering=(0.5, 0.5))
            ico_imgs.append(cropped)

    # Pillow kan meerdere sizes in 1 ICO via sizes=
    bio = io.BytesIO()
    base = ico_imgs[-1] if ico_imgs else img
    size_tuples: List[Tuple[int, int]] = [(s, s) for s in sizes]
    base.save(bio, format="ICO", sizes=size_tuples)
    return bio.getvalue()


# ====== Content-only template (layout verzorgt header/footer/css/js) ======
CONTENT_TEMPLATE = r"""
<style>
.ico-wrap { max-width: 980px; margin: 0 auto; }
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
</style>

<div class="ico-wrap">
  <h1>Image → ICO Converter</h1>
  <p class="muted">Upload een afbeelding en download een multi-size <code>.ico</code> (Windows app icons).</p>

  {% if err %}
    <div class="error-box">{{ err }}</div>
  {% endif %}

  <div class="card">
    <h2>Converter</h2>
    <small>PNG/JPG/GIF/WebP worden ondersteund. Transparantie blijft behouden waar mogelijk.</small>
    <form method="post" action="/ico" enctype="multipart/form-data">
      <div class="field-row">
        <label>Afbeelding</label>
        <input class="in" type="file" name="file" accept=".png,.jpg,.jpeg,.gif,.webp,.bmp,.tif,.tiff">
      </div>

      <div class="row-inline">
        <div>
          <label>Sizes (comma-separated)</label>
          <input class="in" type="text" name="sizes" value="{{ sizes_str }}" placeholder="16,24,32,48,64,96,128,256">
          <small class="muted">Typisch: <code>{{ default_sizes }}</code></small>
        </div>
        <div>
          <label>Mode</label>
          <select class="in" name="mode">
            <option value="contain" {% if mode == 'contain' %}selected{% endif %}>Contain (geen vervorming, padding)</option>
            <option value="crop" {% if mode == 'crop' %}selected{% endif %}>Crop (vult volledig, kan afsnijden)</option>
          </select>
        </div>
      </div>

      <div class="row-inline">
        <div>
          <label>Pad to square</label>
          <select class="in" name="pad">
            <option value="1" {% if pad %}selected{% endif %}>Aan</option>
            <option value="0" {% if not pad %}selected{% endif %}>Uit</option>
          </select>
        </div>
        <div>
          <label>&nbsp;</label>
          <button class="btn" type="submit">Convert → ICO</button>
        </div>
      </div>
    </form>
  </div>

  <div class="card">
    <h2>Tips</h2>
    <ul>
      <li>Gebruik zeker <code>256</code> voor high‑DPI Windows iconen.</li>
      <li>Niet‑vierkante logo’s? Kies <strong>Contain</strong> en zet <strong>Pad to square</strong> aan.</li>
      <li>Je kan gerust extra maten toevoegen zoals <code>20</code> of <code>180</code> (limiet 8–512 px).</li>
    </ul>
  </div>
</div>
"""


def _render(err: Optional[str] = None, sizes_str: str = DEFAULT_SIZES, mode: str = "contain", pad: bool = True):
    content_html = render_template_string(
        CONTENT_TEMPLATE,
        err=err,
        sizes_str=sizes_str,
        default_sizes=DEFAULT_SIZES,
        mode=mode,
        pad=pad,
    )
    return hub_render_page(title="Image → ICO Converter", content_html=content_html)


# ===== Routes =====
def register_web_routes(app: Flask):
    @app.route("/ico", methods=["GET", "POST"])
    def ico_index():
        sizes_str = (request.form.get("sizes") or DEFAULT_SIZES).strip()
        mode = (request.form.get("mode") or "contain").strip().lower()
        pad = (request.form.get("pad") == "1")

        if request.method == "GET":
            return _render(None, sizes_str=sizes_str, mode=mode, pad=pad)

        # POST
        if Image is None:
            return make_response("Pillow ontbreekt. Installeer 'pillow' in je venv.", 500)

        up = request.files.get("file")
        if not up or not up.filename:
            return _render("Geen afbeelding gekozen.", sizes_str=sizes_str, mode=mode, pad=pad)

        try:
            sizes = _parse_sizes(sizes_str)
            if mode not in ("contain", "crop"):
                mode = "contain"

            raw = up.read()
            img = Image.open(io.BytesIO(raw))
            out = _build_ico_bytes(img, sizes=sizes, mode=mode, pad=pad)

            safe = _safe_stem(up.filename)
            dl = f"{safe}.ico"
            bio = io.BytesIO(out)
            bio.seek(0)
            return send_file(
                bio,
                as_attachment=True,
                download_name=dl,
                mimetype="image/x-icon",
            )
        except Exception as e:
            return _render(f"Conversie faalde: {e}", sizes_str=sizes_str, mode=mode, pad=pad)


# Standalone testen (optioneel)
if __name__ == "__main__":
    app = Flask(__name__)
    register_web_routes(app)
    app.run("127.0.0.1", 5002, debug=True)
