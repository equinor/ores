# ─────────────────────────────────────────────────────────────────────
# run_pipeline.ps1  –  Drogon / Valysar end-to-end OSDU pipeline
#
# Default pipeline: CSV → manifests → records → Storage API ingestion
# Alternative:      CSV → manifests → Workflow API ingestion (broken)
#
# Usage:
#   .\demo\drogon\run_pipeline.ps1                 # full pipeline
#   .\demo\drogon\run_pipeline.ps1 -SkipIngest     # generate only
#   .\demo\drogon\run_pipeline.ps1 -WorkflowIngest # manifest ingestion (broken)
#   .\demo\drogon\run_pipeline.ps1 -SkipSplit      # skip CSV split (reuse existing)
#   .\demo\drogon\run_pipeline.ps1 -Delay 5        # custom inter-record delay
# ─────────────────────────────────────────────────────────────────────
param(
    [switch]$SkipSplit,         # skip split_valysar.py (CSVs already exist)
    [switch]$SkipIngest,        # generate manifests + records only, don't ingest
    [switch]$WorkflowIngest,    # use Workflow API (manifest) instead of Storage API (records)
    [switch]$VerifyAfter,       # run verify-only after ingestion
    [int]$Delay = 3             # seconds between Storage API PUTs
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot  = (Resolve-Path "$ScriptDir\..\..").Path

Push-Location $RepoRoot
try {

    # ── Step 0: Split raw CSV into volumes + parameters ─────────────
    if (-not $SkipSplit) {
        Write-Host "`n═══ Step 0: Split CSV ═══" -ForegroundColor Cyan
        py demo/drogon_dg1/split_valysar.py
        if ($LASTEXITCODE -ne 0) { throw "split_valysar.py failed" }
    } else {
        Write-Host "`n═══ Step 0: Split CSV (skipped) ═══" -ForegroundColor DarkGray
    }

    # ── Step 0b: Generate reference data (PropertyTypes + FacetRoles) ──
    Write-Host "`n═══ Step 0b: Reference data ═══" -ForegroundColor Cyan
    py demo/drogon_dg1/genrefpropertytypes_drogon.py
    if ($LASTEXITCODE -ne 0) { throw "genrefpropertytypes_drogon.py failed" }
    py demo/drogon_dg1/genreffacetrole_drogon.py
    if ($LASTEXITCODE -ne 0) { throw "genreffacetrole_drogon.py failed" }

    # ── Step 1: Generate master data (Reservoir + Segments + WP) ────
    Write-Host "`n═══ Step 1: Master data ═══" -ForegroundColor Cyan
    py demo/drogon_dg1/genmaster_drogon.py
    if ($LASTEXITCODE -ne 0) { throw "genmaster_drogon.py failed" }

    # ── Step 2: Generate RAW volumes WPC ────────────────────────────
    Write-Host "`n═══ Step 2: RAW volumes WPC ═══" -ForegroundColor Cyan
    py demo/drogon_dg1/genrawmanifest_drogon.py
    if ($LASTEXITCODE -ne 0) { throw "genrawmanifest_drogon.py failed" }

    # ── Step 3: Generate statistics WPC ─────────────────────────────
    Write-Host "`n═══ Step 3: Statistics WPC ═══" -ForegroundColor Cyan
    py demo/drogon_dg1/genstatmanifest_drogon.py
    if ($LASTEXITCODE -ne 0) { throw "genstatmanifest_drogon.py failed" }

    # ── Step 4: Generate parameters ColumnBasedTable WPC ────────────
    Write-Host "`n═══ Step 4: Parameters WPC ═══" -ForegroundColor Cyan
    py demo/drogon_dg1/genparamsmanifest_drogon.py
    if ($LASTEXITCODE -ne 0) { throw "genparamsmanifest_drogon.py failed" }

    # ── Step 5: Generate Risk ───────────────────────────────────────
    Write-Host "`n═══ Step 5: Risk ═══" -ForegroundColor Cyan
    py demo/drogon_dg1/gen_risk_drogon.py
    if ($LASTEXITCODE -ne 0) { throw "gen_risk_drogon.py failed" }

    # ── Step 6: Generate Business Decision ──────────────────────────    Write-Host "`n═══ Step 5b: Activity manifest ═══" -ForegroundColor Cyan
    py demo/drogon_dg1/gen_activity_drogon.py
    if ($LASTEXITCODE -ne 0) { throw "gen_activity_drogon.py failed" }

    Write-Host "`n═══ Step 5c: DevelopmentConcept WPC ═══" -ForegroundColor Cyan
    py demo/drogon_dg1/gen_devconcept_drogon.py
    if ($LASTEXITCODE -ne 0) { throw "gen_devconcept_drogon.py failed" }

    Write-Host "`n═══ Step 6: Business Decision ═══" -ForegroundColor Cyan
    py demo/drogon_dg1/gen_businessdecision_drogon.py
    if ($LASTEXITCODE -ne 0) { throw "gen_businessdecision_drogon.py failed" }

    # ── Step 7: Split manifests → individual record files ───────────
    Write-Host "`n═══ Step 7: Manifests → records ═══" -ForegroundColor Cyan
    if (Test-Path demo\drogon\records\*.json) {
        Remove-Item demo\drogon\records\*.json
    }
    py demo/drogon_dg1/manifest2records_drogon.py
    if ($LASTEXITCODE -ne 0) { throw "manifest2records_drogon.py failed" }

    if ($SkipIngest) {
        Write-Host "`n═══ Ingestion skipped ═══" -ForegroundColor DarkGray
        Write-Host "Manifests and records generated. Run ingestion manually:"
        Write-Host "  py demo/drogon_dg1/ingest_records_batch.py --delay $Delay"
        return
    }

    # ── Step 8: Ingest ──────────────────────────────────────────────
    if ($WorkflowIngest) {
        # Alternative: Workflow API manifest ingestion (currently broken)
        Write-Host "`n═══ Step 8: Workflow API ingestion (manifests) ═══" -ForegroundColor Yellow
        Write-Host "  WARNING: Workflow API ingestion is known to be broken" -ForegroundColor Yellow
        Write-Host "  Records may report 'finished' but not persist in Storage" -ForegroundColor Yellow
        py demo/drogon_dg1/ingest_workflow_drogon.py
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  Workflow ingestion failed (expected)" -ForegroundColor Red
        }
    } else {
        # Default: Storage API record-by-record ingestion (works)
        Write-Host "`n═══ Step 8: Storage API ingestion (records) ═══" -ForegroundColor Cyan
        py demo/drogon_dg1/ingest_records_batch.py --delay $Delay
        if ($LASTEXITCODE -ne 0) { throw "ingest_records_batch.py failed" }
    }

    # ── Step 9 (optional): Verify all records exist ─────────────────
    if ($VerifyAfter) {
        Write-Host "`n═══ Step 9: Verify records ═══" -ForegroundColor Cyan
        py demo/drogon_dg1/ingest_verified_drogon.py --verify-only
    }

    Write-Host "`n═══ Pipeline complete ═══" -ForegroundColor Green

} finally {
    Pop-Location
}
