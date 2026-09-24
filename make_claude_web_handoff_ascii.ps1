$ErrorActionPreference = "Stop"

$ProjectRoot = (Get-Location).Path
$OutDir = Join-Path $ProjectRoot "claude_web_handoff"
$ZipPath = Join-Path $OutDir "xauusd_forensic_code_and_evidence.zip"
$StageDir = Join-Path $OutDir "package"

if (Test-Path $OutDir) {
    Remove-Item $OutDir -Recurse -Force
}

New-Item -ItemType Directory -Path $StageDir -Force | Out-Null

function Copy-IfExists($relativePath) {
    $src = Join-Path $ProjectRoot $relativePath

    if (-not (Test-Path $src)) {
        return
    }

    $dest = Join-Path $StageDir $relativePath
    $destParent = Split-Path $dest -Parent

    New-Item -ItemType Directory -Path $destParent -Force | Out-Null
    Copy-Item $src $dest -Recurse -Force
}

# ------------------------------------------------------------
# 1. ALL PROJECT SCRIPTS
# ------------------------------------------------------------
Copy-IfExists "scripts"

# ------------------------------------------------------------
# 2. CANONICAL LEDGER
# ------------------------------------------------------------
Copy-IfExists "data\raw\trades_raw.tsv"

# ------------------------------------------------------------
# 3. PROJECT / DEPENDENCY METADATA
# ------------------------------------------------------------
$metadataFiles = @(
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "environment.yml",
    "environment.yaml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "README.md"
)

foreach ($item in $metadataFiles) {
    Copy-IfExists $item
}

# ------------------------------------------------------------
# 4. LIGHTWEIGHT FORENSIC OUTPUTS
#    Include only selected text/tabular artifacts.
#    Large raw tick stores are intentionally excluded.
# ------------------------------------------------------------
$evidenceDirs = @(
    "outputs\market_reconstruction",
    "outputs\strategy_reconstruction"
)

foreach ($dir in $evidenceDirs) {
    $src = Join-Path $ProjectRoot $dir

    if (-not (Test-Path $src)) {
        continue
    }

    $files = Get-ChildItem $src -File -Recurse |
        Where-Object {
            $_.Length -le 25MB -and
            $_.Extension.ToLower() -in @(
                ".md",
                ".txt",
                ".json",
                ".csv",
                ".tsv",
                ".py",
                ".mq5",
                ".html"
            )
        }

    foreach ($f in $files) {
        $rel = $f.FullName.Substring($ProjectRoot.Length).TrimStart('\')
        Copy-IfExists $rel
    }
}

# ------------------------------------------------------------
# 5. OPTIONAL GIT METADATA
# ------------------------------------------------------------
Copy-IfExists ".git\HEAD"
Copy-IfExists ".git\config"
Copy-IfExists ".git\description"

# ------------------------------------------------------------
# 6. REMOVE OBVIOUS SECRETS
# ------------------------------------------------------------
Get-ChildItem $StageDir -File -Recurse -Force |
    Where-Object {
        $_.Name -match '(^|^\.)(env|env\..*|pem|key|crt)$' -or
        $_.Name -match '(secret|credential|password|token|apikey|api_key)'
    } |
    Remove-Item -Force -ErrorAction SilentlyContinue

# ------------------------------------------------------------
# 7. MANIFEST
# ------------------------------------------------------------
$manifest = Join-Path $StageDir "CLAUDE_HANDOFF_MANIFEST.txt"

$lines = @(
    "XAUUSD Forensic Reverse Engineering - Claude Web Handoff",
    "Created: $(Get-Date -Format o)",
    "Project root: $ProjectRoot",
    "",
    "Included:",
    "- entire scripts directory",
    "- canonical data/raw/trades_raw.tsv",
    "- lightweight market_reconstruction artifacts",
    "- lightweight strategy_reconstruction artifacts",
    "- dependency/project metadata when present",
    "",
    "Excluded intentionally:",
    "- data/market/raw_ticks",
    "- large parquet or tick stores",
    "- node_modules",
    "- caches and build directories",
    "- secrets and credentials"
)

$lines | Set-Content -Path $manifest -Encoding ASCII

# ------------------------------------------------------------
# 8. CREATE ZIP
# ------------------------------------------------------------
Compress-Archive `
    -Path (Join-Path $StageDir "*") `
    -DestinationPath $ZipPath `
    -CompressionLevel Optimal `
    -Force

$sizeMB = [Math]::Round((Get-Item $ZipPath).Length / 1MB, 2)

Write-Host ""
Write-Host "DONE"
Write-Host "ZIP: $ZipPath"
Write-Host "SIZE: $sizeMB MB"
Write-Host ""
Write-Host "Upload this ONE file to Claude Web:"
Write-Host $ZipPath
Write-Host ""
Write-Host "Raw tick files were intentionally excluded."
