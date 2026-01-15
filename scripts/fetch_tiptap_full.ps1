
# ======================================================================
#  CyNiT-Hub – FIX FULL TIPTAP + PROSEMIRROR VENDOR BUNDLE
# ======================================================================
Write-Host "=== Tiptap / ProseMirror Vendor Installer ===" -ForegroundColor Cyan

$Root = "C:\gh\CyNiT-Hub\static\vendor\tiptap"
$PM   = Join-Path $Root "prosemirror"

# 1) Verwijder oude map
if (Test-Path $Root) {
    Write-Host "Removing old vendor/tiptap ..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $Root
}

# 2) Maak structuur opnieuw
Write-Host "Creating folders..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $Root        | Out-Null
New-Item -ItemType Directory -Force -Path $PM          | Out-Null

$folders = @(
    "core", "starter-kit",
    "ext-link", "ext-image", "ext-placeholder"
)

foreach ($f in $folders) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $f) | Out-Null
}

# === Helper om bestanden te downloaden ===
function Fetch($url, $out) {
    Write-Host "Downloading $url..." -ForegroundColor Gray
    Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
}

# ======================================================================
# 3) DOWNLOAD TIPTAP MODULES (2.6.6)
# ======================================================================
$ver = "2.6.6"
$base = "https://esm.sh/@tiptap"

# Core
Fetch "$base/core@$ver"              (Join-Path $Root "core/index.js")

# Starter kit
Fetch "$base/starter-kit@$ver"       (Join-Path $Root "starter-kit/index.js")

# Extensions
Fetch "$base/extension-link@$ver"        (Join-Path $Root "ext-link/index.js")
Fetch "$base/extension-image@$ver"       (Join-Path $Root "ext-image/index.js")
Fetch "$base/extension-placeholder@$ver" (Join-Path $Root "ext-placeholder/index.js")

# ======================================================================
# 4) DOWNLOAD PROSEMIRROR DEPENDENCIES
# ======================================================================
$pmList = @{
    "model.js"          = "https://esm.sh/prosemirror-model@1.21.0"
    "state.js"          = "https://esm.sh/prosemirror-state@1.4.2"
    "transform.js"      = "https://esm.sh/prosemirror-transform@1.7.3"
    "view.js"           = "https://esm.sh/prosemirror-view@1.32.7"
    "keymap.js"         = "https://esm.sh/prosemirror-keymap@1.2.2"
    "commands.js"       = "https://esm.sh/prosemirror-commands@1.5.1"
    "history.js"        = "https://esm.sh/prosemirror-history@1.3.0"
    "schema-basic.js"   = "https://esm.sh/prosemirror-schema-basic@1.2.1"
    "schema-list.js"    = "https://esm.sh/prosemirror-schema-list@1.2.2"
    "gapcursor.js"      = "https://esm.sh/prosemirror-gapcursor@1.3.1"
    "dropcursor.js"     = "https://esm.sh/prosemirror-dropcursor@1.6.1"
    "orderedmap.js"     = "https://esm.sh/orderedmap@2.0.0"
}

foreach ($kv in $pmList.GetEnumerator()) {
    Fetch $kv.Value (Join-Path $PM $kv.Key)
}

Write-Host "=== DONE ===" -ForegroundColor Green
Write-Host "Je Tiptap & ProseMirror vendor-map is volledig gerebuilt!"
Write-Host "Restart master.py"
