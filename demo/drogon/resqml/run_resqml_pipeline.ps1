<#
.SYNOPSIS
  Full RESQML pipeline: generate EPC files from OSDU records, then ingest to RDDMS.

.DESCRIPTION
  1. Runs gen_resqml.py to create:
       resqml/drogon_tables.epc   – PointSetRepresentations with per-column Properties
       resqml/drogon_activity.epc – ActivityTemplate + Activity
  2. Runs ingest_rddms.ps1 to import both EPCs into the OSDU Reservoir DDMS.

.EXAMPLE
  .\demo\drogon\resqml\run_resqml_pipeline.ps1
  .\demo\drogon\resqml\run_resqml_pipeline.ps1 -SkipGenerate
  .\demo\drogon\resqml\run_resqml_pipeline.ps1 -SkipIngest
  .\demo\drogon\resqml\run_resqml_pipeline.ps1 -DataspaceName "maap/my_test" -DryRun
#>

param(
    [string]$DataspaceName = "maap/drogon_dg",
    [switch]$SkipGenerate,
    [switch]$SkipIngest,
    [switch]$SkipCreate,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path   # demo/drogon/resqml
$RepoRoot  = (Resolve-Path "$ScriptDir\..\..\..").Path
$DrogonDir = (Resolve-Path "$ScriptDir\..").Path

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║        Drogon RESQML Pipeline (generate + ingest)       ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Generate RESQML EPC files ─────────────────────────────────────

if (-not $SkipGenerate) {
    Write-Host "┌─────────────────────────────────────────┐" -ForegroundColor Yellow
    Write-Host "│  Step 1/2: Generate RESQML EPC files    │" -ForegroundColor Yellow
    Write-Host "└─────────────────────────────────────────┘" -ForegroundColor Yellow
    Write-Host ""

    $genScript = Join-Path $DrogonDir "gen_resqml.py"
    if (-not (Test-Path $genScript)) {
        throw "gen_resqml.py not found at $genScript"
    }

    Push-Location $RepoRoot
    try {
        py $genScript
        if ($LASTEXITCODE -ne 0) {
            throw "gen_resqml.py failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
    Write-Host ""
} else {
    Write-Host "  Skipping RESQML generation (--SkipGenerate)" -ForegroundColor DarkGray
    Write-Host ""
}

# ── Step 2: Ingest to RDDMS ──────────────────────────────────────────────

if (-not $SkipIngest) {
    Write-Host "┌─────────────────────────────────────────┐" -ForegroundColor Yellow
    Write-Host "│  Step 2/2: Ingest EPCs to RDDMS         │" -ForegroundColor Yellow
    Write-Host "└─────────────────────────────────────────┘" -ForegroundColor Yellow
    Write-Host ""

    $ingestScript = Join-Path $ScriptDir "ingest_rddms.ps1"
    if (-not (Test-Path $ingestScript)) {
        throw "ingest_rddms.ps1 not found at $ingestScript"
    }

    $ingestArgs = @{ DataspaceName = $DataspaceName }
    if ($SkipCreate) { $ingestArgs["SkipCreate"] = $true }
    if ($DryRun)     { $ingestArgs["DryRun"]     = $true }

    & $ingestScript @ingestArgs
} else {
    Write-Host "  Skipping RDDMS ingest (--SkipIngest)" -ForegroundColor DarkGray
    Write-Host ""
}

Write-Host ""
Write-Host "Pipeline complete." -ForegroundColor Green
