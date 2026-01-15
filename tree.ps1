param(
  [string]$Path = ".",
  [switch]$Files,    # toon bestanden
  [switch]$Ascii     # ASCII output (voor markdown)
)

# ❌ Mappen die ALTIJD genegeerd worden
$ExcludeExact = @(
  "venv",
  ".venv",
  "__pycache__",
  ".git",
  "node_modules",
  "dist",
  "build"
)

# ❌ Patterns (regex) die genegeerd worden
$ExcludePatterns = @(
  "pycache"          # vangt __pycache__, _pycache_, etc
)

function Should-Exclude($item) {
  $name = $item.Name.ToLower()

  if ($ExcludeExact -contains $name) { return $true }

  foreach ($pattern in $ExcludePatterns) {
    if ($name -match $pattern) { return $true }
  }

  return $false
}

function Get-Children($dir) {
  Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue |
    Where-Object { -not (Should-Exclude $_) } |
    Sort-Object @{Expression={$_.PSIsContainer}; Descending=$true}, Name
}

function Print-Tree([string]$dir, [string]$prefix = "") {
  $items = Get-Children $dir
  $count = @($items).Count

  for ($i = 0; $i -lt $count; $i++) {
    $item = $items[$i]
    $isLast = ($i -eq ($count - 1))

    if ($Ascii) {
      if ($isLast) {
        $branch = "\-- "
        $nextPrefix = $prefix + "    "
      } else {
        $branch = "|-- "
        $nextPrefix = $prefix + "|   "
      }
    } else {
      if ($isLast) {
        $branch = "└── "
        $nextPrefix = $prefix + "    "
      } else {
        $branch = "├── "
        $nextPrefix = $prefix + "│   "
      }
    }

    if ($item.PSIsContainer) {
      Write-Output ($prefix + $branch + $item.Name + "/")
      Print-Tree -dir $item.FullName -prefix $nextPrefix
    } else {
      if ($Files) {
        Write-Output ($prefix + $branch + $item.Name)
      }
    }
  }
}

$full = (Resolve-Path -LiteralPath $Path).Path
Write-Output ((Split-Path $full -Leaf) + "/")
Print-Tree -dir $full -prefix ""
