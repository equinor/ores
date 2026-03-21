# ─────────────────────────────────────────────────────────────────────
# run_pipeline_dg2.ps1 — Drogon DG2 (Concept Select) end-to-end pipeline
#
# Pre-requisite: DG1 pipeline has been run (shared master data manifests
# must exist in demo/drogon/).
#
# Pipeline:
#   DG2 params (×0.8) → DG2 raw volumes (×0.8) → DG2 statistics →
#   DG2 activity → DG2 risks → DG2 documents → DG2 BD →
#   records → ingestion
#
# Usage:
#   .\demo\drogon_dg2\run_pipeline_dg2.ps1                # full pipeline
#   .\demo\drogon_dg2\run_pipeline_dg2.ps1 -SkipIngest    # generate only
#   .\demo\drogon_dg2\run_pipeline_dg2.ps1 -Delay 5       # custom delay
# ─────────────────────────────────────────────────────────────────────
param(
    [switch]$SkipIngest,
    [int]$Delay = 3
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot  = (Resolve-Path "$ScriptDir\..\..").Path

Push-Location $RepoRoot
try {

    # ── Pre-check: verify DG1 shared manifests exist ────────────────
    Write-Host "`n═══ Pre-check: DG1 shared manifests ═══" -ForegroundColor Cyan
    $dg1Dir = "demo/drogon"
    $requiredDG1 = @(
        "manifest_masterwp_drogon.json"
    )
    foreach ($f in $requiredDG1) {
        $path = Join-Path $dg1Dir $f
        if (-not (Test-Path $path)) {
            throw "DG1 manifest missing: $path — run DG1 pipeline first"
        }
        Write-Host "  OK $f" -ForegroundColor Green
    }

    # ── Step 1: Generate DG2 Parameters (porosity ×0.8) ──────────────
    Write-Host "`n═══ Step 1: DG2 Parameters (porosity ×0.8) ═══" -ForegroundColor Cyan
    py demo/drogon_dg2/genparamsmanifest_dg2.py
    if ($LASTEXITCODE -ne 0) { throw "genparamsmanifest_dg2.py failed" }

    # ── Step 2: Generate DG2 Raw Volumes (pore volumes ×0.8) ──────
    Write-Host "`n═══ Step 2: DG2 Raw Volumes (×0.8) ═══" -ForegroundColor Cyan
    py demo/drogon_dg2/genrawmanifest_dg2.py
    if ($LASTEXITCODE -ne 0) { throw "genrawmanifest_dg2.py failed" }

    # ── Step 3: Generate DG2 Statistics ───────────────────────────
    Write-Host "`n═══ Step 3: DG2 Statistics ═══" -ForegroundColor Cyan
    py demo/drogon_dg2/genstatmanifest_dg2.py
    if ($LASTEXITCODE -ne 0) { throw "genstatmanifest_dg2.py failed" }

    # ── Step 4: Generate DG2 Activity (links DG2 WPCs) ───────────
    Write-Host "`n═══ Step 4: DG2 Activity ═══" -ForegroundColor Cyan
    py demo/drogon_dg2/gen_activity_dg2.py
    if ($LASTEXITCODE -ne 0) { throw "gen_activity_dg2.py failed" }

    # ── Step 5: Generate DG2 Risk manifest (4 risks) ──────────────
    Write-Host "`n═══ Step 5: DG2 Risks ═══" -ForegroundColor Cyan
    py demo/drogon_dg2/gen_risk_dg2.py
    if ($LASTEXITCODE -ne 0) { throw "gen_risk_dg2.py failed" }

    # ── Step 6: Generate DG2 Document WPC manifest ────────────────
    Write-Host "`n═══ Step 6: DG2 Documents ═══" -ForegroundColor Cyan
    py demo/drogon_dg2/gen_documents_dg2.py
    if ($LASTEXITCODE -ne 0) { throw "gen_documents_dg2.py failed" }

    # ── Step 6b: Generate DG2 DevelopmentConcept WPC ────────────────
    Write-Host "`n═══ Step 6b: DG2 DevelopmentConcept WPC ═══" -ForegroundColor Cyan
    py demo/drogon_dg2/gen_devconcept_dg2.py
    if ($LASTEXITCODE -ne 0) { throw "gen_devconcept_dg2.py failed" }

    # ── Step 7: Generate DG2 Business Decision ────────────────────
    Write-Host "`n═══ Step 7: DG2 Business Decision ═══" -ForegroundColor Cyan
    py demo/drogon_dg2/gen_businessdecision_dg2.py
    if ($LASTEXITCODE -ne 0) { throw "gen_businessdecision_dg2.py failed" }

    # ── Step 8: Split manifests → individual record files ─────────
    Write-Host "`n═══ Step 8: Manifests → records ═══" -ForegroundColor Cyan
    if (Test-Path demo\drogon_dg2\records\*.json) {
        Remove-Item demo\drogon_dg2\records\*.json
    }
    py demo/drogon_dg2/manifest2records_dg2.py
    if ($LASTEXITCODE -ne 0) { throw "manifest2records_dg2.py failed" }

    if ($SkipIngest) {
        Write-Host "`n═══ Ingestion skipped ═══" -ForegroundColor DarkGray
        Write-Host "Manifests and records generated in demo/drogon_dg2/"
        Write-Host "  Run ingestion manually:"
        Write-Host "  py demo/drogon_dg2/ingest_records_batch.py --delay $Delay"
        return
    }

    # ── Step 9: Ingest via Storage API ─────────────────────────────
    Write-Host "`n═══ Step 9: Storage API ingestion ═══" -ForegroundColor Cyan
    py demo/drogon_dg2/ingest_records_batch.py --delay $Delay
    if ($LASTEXITCODE -ne 0) { throw "ingest_records_batch.py failed" }

    Write-Host "`n═══ DG2 Pipeline complete ═══" -ForegroundColor Green

} finally {
    Pop-Location
}
