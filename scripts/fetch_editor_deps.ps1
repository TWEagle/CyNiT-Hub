
# ======================================================================
# CyNiT-Hub – Editor Dependencies (LATEST)
#   - Tiptap v3 (core + starter-kit + ALL extensions incl. list & underline)
#   - ProseMirror deps (incl. gapcursor/dropcursor/orderedmap)
#   - LinkifyJS (voor tiptap/extension-link)
#   - CodeMirror 6 (state/view + lang-* + autocomplete + search)
#   - TinyMCE 7 (core + themes + icons + plugins + skins) – zonder licensekeymanager
# Paden: C:\gh\CyNiT-Hub\static\vendor\{tiptap|codemirror|tinymce}
# Schrijft TIPTAP-extensies in BEIDE paden:
#   - static/vendor/tiptap/ext-<name>/index.js
#   - static/vendor/tiptap/extensions/<name>/index.js
# ======================================================================

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Write-Host "=== CyNiT-Hub Editor Deps Installer (LATEST) ===" -ForegroundColor Cyan

# ---- Resolve project & vendor root ----
$ScriptRoot  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptRoot "..") | Select-Object -ExpandProperty Path
$VendorRoot  = Join-Path $ProjectRoot "static\vendor"

if (!(Test-Path $VendorRoot)) { New-Item -ItemType Directory -Force -Path $VendorRoot | Out-Null }

function Ensure-Dir($p) { if (!(Test-Path $p)) { New-Item -ItemType Directory -Force -Path $p | Out-Null } }

$OK = 0; $ERR = 0; $FAILS = @()

function Fetch($Url, $OutFile) {
  try {
    Ensure-Dir (Split-Path -Parent $OutFile)
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $OutFile -ErrorAction Stop
    $global:OK++
  } catch {
    $global:ERR++
    $global:FAILS += @{ url=$Url; out=$OutFile; msg=$_.Exception.Message }
    Write-Warning "Failed: $Url -> $OutFile  ($($_.Exception.Message))"
  }
}

# =========================
# TIPTAP (LATEST via esm.sh — v3 keten)
# =========================
$tiptapRoot = Join-Path $VendorRoot "tiptap"
# schoon schip om "stale" bestanden te vermijden
if (Test-Path $tiptapRoot) {
  Write-Host "Cleaning tiptap ..." -ForegroundColor Yellow
  Remove-Item -Recurse -Force $tiptapRoot
}
Ensure-Dir $tiptapRoot

# Core + starter-kit + basis extensies
$map = @{
  "core/index.js"             = "https://esm.sh/@tiptap/core?target=es2022"
  "starter-kit/index.js"      = "https://esm.sh/@tiptap/starter-kit?target=es2022"
  "ext-link/index.js"         = "https://esm.sh/@tiptap/extension-link?target=es2022"
  "ext-image/index.js"        = "https://esm.sh/@tiptap/extension-image?target=es2022"
  "ext-placeholder/index.js"  = "https://esm.sh/@tiptap/extension-placeholder?target=es2022"
}
foreach ($kv in $map.GetEnumerator()) {
  Fetch $kv.Value (Join-Path $tiptapRoot $kv.Key)
}

# Tiptap EXTENSIONS – schrijf in BEIDE paden: ext-<name>/index.js én extensions/<name>/index.js
# (v3 set – incl. list & underline)
$extensions = @(
  "blockquote","bold","bullet-list","code","code-block","document",
  "dropcursor","gapcursor","hard-break","heading","history","horizontal-rule",
  "italic","list","list-item","ordered-list","paragraph","strike","text","underline"
)

foreach ($ext in $extensions) {
  $url = "https://esm.sh/@tiptap/extension-{0}?target=es2022" -f $ext
  Fetch $url (Join-Path $tiptapRoot ("ext-{0}\index.js" -f $ext))
  Fetch $url (Join-Path $tiptapRoot ("extensions\{0}\index.js" -f $ext))
}

# ProseMirror (mapping sluit aan op je shim)
$pmRoot = Join-Path $tiptapRoot "prosemirror"
Ensure-Dir $pmRoot
$pmMap = @{
  "model.js"         = "https://esm.sh/prosemirror-model?target=es2022"
  "state.js"         = "https://esm.sh/prosemirror-state?target=es2022"
  "transform.js"     = "https://esm.sh/prosemirror-transform?target=es2022"
  "view.js"          = "https://esm.sh/prosemirror-view?target=es2022"
  "keymap.js"        = "https://esm.sh/prosemirror-keymap?target=es2022"
  "commands.js"      = "https://esm.sh/prosemirror-commands?target=es2022"
  "history.js"       = "https://esm.sh/prosemirror-history?target=es2022"
  "schema-basic.js"  = "https://esm.sh/prosemirror-schema-basic?target=es2022"
  "schema-list.js"   = "https://esm.sh/prosemirror-schema-list?target=es2022"
  "gapcursor.js"     = "https://esm.sh/prosemirror-gapcursor?target=es2022"
  "dropcursor.js"    = "https://esm.sh/prosemirror-dropcursor?target=es2022"
  "orderedmap.js"    = "https://esm.sh/orderedmap?target=es2022"
}
foreach ($kv in $pmMap.GetEnumerator()) {
  Fetch $kv.Value (Join-Path $pmRoot $kv.Key)
}

# LinkifyJS voor extension-link shim
Fetch "https://esm.sh/linkifyjs?target=es2022" (Join-Path $tiptapRoot "ext-link\linkify.js")

# =========================
# CODEMIRROR 6 (LATEST via esm.sh)
# =========================
$cmRoot = Join-Path $VendorRoot "codemirror"
Ensure-Dir $cmRoot
$cmMap = @{
  "view/index.js"             = "https://esm.sh/@codemirror/view?target=es2022"
  "state/index.js"            = "https://esm.sh/@codemirror/state?target=es2022"
  "lang-html/index.js"        = "https://esm.sh/@codemirror/lang-html?target=es2022"
  "lang-css/index.js"         = "https://esm.sh/@codemirror/lang-css?target=es2022"
  "lang-json/index.js"        = "https://esm.sh/@codemirror/lang-json?target=es2022"
  "lang-xml/index.js"         = "https://esm.sh/@codemirror/lang-xml?target=es2022"
  "lang-markdown/index.js"    = "https://esm.sh/@codemirror/lang-markdown?target=es2022"
  "autocomplete/index.js"     = "https://esm.sh/@codemirror/autocomplete?target=es2022"
  "search/index.js"           = "https://esm.sh/@codemirror/search?target=es2022"
  "deps/crelt.js"             = "https://esm.sh/crelt?target=es2022"
  "deps/style-mod.js"         = "https://esm.sh/style-mod?target=es2022"
  "deps/w3c-keyname.js"       = "https://esm.sh/w3c-keyname?target=es2022"
  "@marijn/find-cluster-break.js" = "https://esm.sh/@marijn/find-cluster-break?target=es2022"
}
foreach ($kv in $cmMap.GetEnumerator()) {
  Fetch $kv.Value (Join-Path $cmRoot $kv.Key)
}

# =========================
# TINYMCE 7 (LATEST via jsDelivr)
# =========================
$tinyRoot = Join-Path $VendorRoot "tinymce"
Ensure-Dir $tinyRoot

# Core
Fetch "https://cdn.jsdelivr.net/npm/tinymce@latest/tinymce.min.js"              (Join-Path $tinyRoot "tinymce.min.js")
# Themes / models / icons
Fetch "https://cdn.jsdelivr.net/npm/tinymce@latest/themes/silver/theme.min.js"  (Join-Path $tinyRoot "themes\silver\theme.min.js")
Fetch "https://cdn.jsdelivr.net/npm/tinymce@latest/models/dom/model.min.js"     (Join-Path $tinyRoot "models\dom\model.min.js")
Fetch "https://cdn.jsdelivr.net/npm/tinymce@latest/icons/default/icons.min.js"  (Join-Path $tinyRoot "icons\default\icons.min.js")

# Plugins (ruim assortiment, ZONDER licensekeymanager)
$plugins = @(
  "advlist","autolink","lists","link","image","charmap","preview","anchor",
  "searchreplace","code","fullscreen","insertdatetime","media","table",
  "emoticons","wordcount","autosave","visualblocks"
)
foreach ($p in $plugins) {
  Fetch "https://cdn.jsdelivr.net/npm/tinymce@latest/plugins/$p/plugin.min.js" (Join-Path $tinyRoot "plugins\$p\plugin.min.js")
}

# Skins (dark/ui + content)
Fetch "https://cdn.jsdelivr.net/npm/tinymce@latest/skins/ui/oxide-dark/skin.min.css"      (Join-Path $tinyRoot "skins\ui\oxide-dark\skin.min.css")
Fetch "https://cdn.jsdelivr.net/npm/tinymce@latest/skins/ui/oxide/skin.min.css"           (Join-Path $tinyRoot "skins\ui\oxide\skin.min.css")
Fetch "https://cdn.jsdelivr.net/npm/tinymce@latest/skins/content/dark/content.min.css"    (Join-Path $tinyRoot "skins\content\dark\content.min.css")
Fetch "https://cdn.jsdelivr.net/npm/tinymce@latest/skins/ui/oxide/content.min.css"        (Join-Path $tinyRoot "skins\ui\oxide\content.min.css")

# =========================
# SUMMARY
# =========================
Write-Host ""
Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
Write-Host ("Success: {0} | Fout: {1}" -f $OK, $ERR)
if ($ERR -gt 0) {
  $FAILS | ForEach-Object { Write-Host (" - {0}" -f $_.url) -ForegroundColor Yellow }
  Write-Host "Tip: een her-run herstelt vaak tijdelijke CDN-fouten." -ForegroundColor Yellow
} else {
  Write-Host "Alles OK. Herstart je Flask app (python master.py) en open /i18n" -ForegroundColor Green
}
