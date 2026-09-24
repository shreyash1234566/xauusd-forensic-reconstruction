# Creates a compact Claude Web handoff ZIP for the XAUUSD forensic project.
# Run this from PowerShell in the project root, e.g.:
#   cd "E:\reverse -traid"
#   .\make_claude_web_handoff.ps1

$ErrorActionPreference = "Stop"

$ProjectRoot = (Get-Location).Path
$OutDir = Join-Path $ProjectRoot "claude_web_handoff"
$ZipPath = Join-Path $OutDir "xauusd_forensic_code_and_evidence.zip"
$StageDir = Join-Path $OutDir "package"

if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Path $StageDir -Force | Out-Null

function Copy-IfExists($relativePath) {
    $src = Join-Path $ProjectRoot $relativePath
    if (-not (Test-Path $src)) { return }

    $dest = Join-Path $StageDir $relativePath
    $destParent = Split-Path $dest -Parent
    New-Item -ItemType Directory -Path $destParent -Force | Out-Null

    Copy-Item $src $dest -Recurse -Force
}

# 1) ALL project scripts. This avoids missing a phase-specific file.
Copy-IfExists "scripts"

# 2) Canonical ledger.
Copy-IfExists "data\raw\trades_raw.tsv"

# 3) Reproducibility / dependency files, when present.
@(
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
) | ForEach-Object { Copy-IfExists $_ }

# 4) Lightweight forensic evidence.
$evidenceDirs = @(
    "outputs\market_reconstruction",
    "outputs\strategy_reconstruction"
)

foreach ($dir in $evidenceDirs) {
    $src = Join-Path $ProjectRoot $dir
    if (-not (Test-Path $src)) { continue }

    $files = Get-ChildItem $src -File -Recurse |
        Where-Object {
            $_.Length -le 25MB -and
            $_.Extension -in @(
                ".md",".txt",".json",".csv",".tsv",
                ".py",".mq5",".html"
            )
        }

    foreach ($f in $files) {
        $rel = $f.FullName.Substring($ProjectRoot.Length).TrimStart('\')
        Copy-IfExists $rel
    }
}

# 5) Project metadata that helps identify exact code provenance, if available.
@(
    ".git\HEAD",
    ".git\config",
    ".git\description"
) | ForEach-Object { Copy-IfExists $_ }

# Remove obvious secrets/config credentials even if they were copied through another path.
Get-ChildItem $StageDir -File -Recurse -Force |
    Where-Object {
        $_.Name -match '(^|^\.)(env|env\..*|pem|key|crt)$' -or
        $_.Name -match '(secret|credential|password|token|apikey|api_key)'
    } |
    Remove-Item -Force -ErrorAction SilentlyContinue

# Write a manifest.
$manifest = Join-Path $StageDir "CLAUDE_HANDOFF_MANIFEST.txt"
$lines = @(
    "XAUUSD Forensic Reverse-Engineering — Claude Web Handoff",
    "Created: $(Get-Date -Format o)",
    "Project root: $ProjectRoot",
    "",
    "Included:",
    "- entire scripts/ tree",
    "- canonical data/raw/trades_raw.tsv",
    "- lightweight market_reconstruction / strategy_reconstruction artifacts <= 25 MB",
    "- dependency / project metadata when present",
    "",
    "Excluded intentionally:",
    "- data/market/raw_ticks/",
    "- large Parquet/tick stores",
    "- node_modules/",
    "- caches/build directories",
    "- secrets and credentials"
)
$lines | Set-Content -Path $manifest -Encoding UTF8

# Zip the staged package.
Compress-Archive -Path (Join-Path $StageDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal -Force

$sizeMB = [Math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
Write-Host ""
Write-Host "DONE"
Write-Host "ZIP: $ZipPath"
Write-Host "SIZE: $sizeMB MB"
Write-Host ""
Write-Host "Upload this ONE file to Claude Web:"
Write-Host $ZipPath
Write-Host ""
Write-Host "DO NOT upload data\market\raw_ticks separately unless Claude later requests a specific missing subset."
