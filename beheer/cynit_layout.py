from __future__ import annotations
from flask import g


def render_page(*, title: str, content_html: str) -> str:
    app_name = "CyNiT Tools"
    page_title = title or g.get("page_title") or app_name

    return f"""<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{page_title} — {app_name}</title>
  <link rel="icon" href="/favicon.ico" />
  <style>
    :root {{
      --bg: #0b0f14;
      --panel: #0f1621;
      --line: #1f2a3a;
      --text: #e8eef7;
      --muted: #9fb2c9;
      --btn: #2a3a52;
      --btn2: #3f5f8a;
    }}
    body {{ margin:0; font-family:Segoe UI,Arial,sans-serif; background:var(--bg); color:var(--text); }}
    .topbar {{ position:sticky; top:0; z-index:10; background:var(--panel); border-bottom:1px solid var(--line); }}
    .topbar .row {{ display:flex; align-items:center; gap:12px; padding:12px 14px; }}
    .brand {{ display:flex; align-items:center; gap:10px; text-decoration:none; color:inherit; }}
    .brand img {{ width:28px; height:28px; object-fit:contain; }}
    .brand .title {{ font-weight:700; letter-spacing:.2px; }}
    .spacer {{ flex:1; }}
    .pill {{ font-size:12px; padding:4px 10px; border:1px solid var(--btn); border-radius:999px; color:var(--muted); }}
    .wrap {{ max-width:1000px; margin:0 auto; padding:18px; }}
    a.btn {{ display:inline-block; padding:10px 14px; border-radius:12px; border:1px solid var(--btn); color:var(--text); text-decoration:none; }}
    a.btn:hover {{ border-color:var(--btn2); }}
    .footer {{ position:sticky; bottom:0; background:var(--panel); border-top:1px solid var(--line); padding:10px 14px; color:var(--muted); }}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="row">
      <a class="brand" href="/" title="Home">
        <img src="/logo.png" alt="logo" />
        <span class="title">CyNiT Tools</span>
      </a>
      <div class="spacer"></div>
      <span class="pill">{page_title}</span>
    </div>
  </header>

  <main>
    {content_html}
  </main>

  <footer class="footer">
    CyNiT Hub — footer altijd zichtbaar
  </footer>
</body>
</html>
"""
