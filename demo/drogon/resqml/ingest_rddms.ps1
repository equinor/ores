<#
.SYNOPSIS
  Import Drogon RESQML EPC files into the OSDU Reservoir DDMS (dev) via Docker ETP client.

.DESCRIPTION
  Follows the exact same pattern as the RDDMS bootcamp notebook (section 10.3).
  1. Authenticates via AAD refresh_token grant
  2. Creates dataspace with proper ACL
  3. Imports drogon_tables.epc and drogon_activity.epc
  4. Prints dataspace stats to verify

.NOTES
  Prerequisites:
    - Docker Desktop running
    - Image tagged as 'open-etp-sslclient':
        docker tag community.opengroup.org:5555/.../open-etp-sslclient-main open-etp-sslclient
    - .env file at repo root

.EXAMPLE
  .\demo\drogon\resqml\ingest_rddms.ps1
  .\demo\drogon\resqml\ingest_rddms.ps1 -DryRun
  .\demo\drogon\resqml\ingest_rddms.ps1 -DataspaceName "maap/my_test"
#>

param(
    [string]$DataspaceName = "maap/drogon_dg",
    [switch]$DryRun,
    [switch]$SkipCreate
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path   # demo/drogon/resqml
$RepoRoot  = (Resolve-Path "$ScriptDir\..\..\..").Path

# ── Load .env ──────────────────────────────────────────────────────────────

$envFile = Join-Path $RepoRoot ".env"
if (-not (Test-Path $envFile)) { throw ".env not found at $envFile" }

$envVars = @{}
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $k, $v = $line -split "=", 2
        $k = $k.Trim(); $v = $v.Trim().Trim('"').Trim("'")
        $envVars[$k] = $v
    }
}

function Get-EnvVal([string[]]$keys) {
    foreach ($k in $keys) { if ($envVars[$k]) { return $envVars[$k] } }
    return $null
}

$OSDU_BASE_URL     = Get-EnvVal "OSDU_HOST","OSDU_BASE_URL"
$DATA_PARTITION_ID = Get-EnvVal "DATA_PARTITION_ID","OSDU_PARTITION"
$AZURE_TENANT_ID   = Get-EnvVal "AZURE_TENANT_ID","OSDU_TENANT_ID"
$AZURE_CLIENT_ID   = Get-EnvVal "AZURE_CLIENT_ID","OSDU_CLIENT_ID"
$AZURE_SCOPE       = Get-EnvVal "AZURE_SCOPE","OSDU_SCOPE"
$REFRESH_TOKEN     = Get-EnvVal "refresh_token","REFRESH_TOKEN"
$LEGAL_TAG         = Get-EnvVal "DEFAULT_LEGAL_TAG"
if (-not $LEGAL_TAG) { $LEGAL_TAG = "$DATA_PARTITION_ID-equinor-private-default" }

$ETP_URL = "wss://${OSDU_BASE_URL}/api/reservoir-ddms-etp/v2/"
$DOCKER_IMAGE = "open-etp-sslclient"

Write-Host "=== Configuration ===" -ForegroundColor Cyan
Write-Host "  Host:       $OSDU_BASE_URL"
Write-Host "  Partition:  $DATA_PARTITION_ID"
Write-Host "  ETP URL:    $ETP_URL"
Write-Host "  Dataspace:  $DataspaceName"
Write-Host "  Image:      $DOCKER_IMAGE"
Write-Host ""

# ── Authenticate ───────────────────────────────────────────────────────────

Write-Host "=== Authenticate ===" -ForegroundColor Cyan
$tokenUrl = "https://login.microsoftonline.com/$AZURE_TENANT_ID/oauth2/v2.0/token"
$body = @{
    grant_type    = "refresh_token"
    client_id     = $AZURE_CLIENT_ID
    refresh_token = $REFRESH_TOKEN
    scope         = $AZURE_SCOPE
}
$response = Invoke-RestMethod -Uri $tokenUrl -Method POST -Body $body -ContentType "application/x-www-form-urlencoded"
$TOKEN = $response.access_token
Write-Host "  Token acquired (expires_in=$($response.expires_in)s)" -ForegroundColor Green
Write-Host ""

# ── Build ETP credentials (same as bootcamp) ──────────────────────────────

$etp_credentials = "--server-url $ETP_URL --data-partition-id $DATA_PARTITION_ID --auth bearer --jwt-token $TOKEN"
$space_root_cmd  = "/bin/openETPServer space $etp_credentials"

# ── Copy EPC+H5 files to a temp dir (avoid spaces in volume mount path) ───

$tmpRoot = if ($env:TEMP) { $env:TEMP } elseif ($env:TMPDIR) { $env:TMPDIR } else { "/tmp" }
$tempDir = Join-Path $tmpRoot "ores_resqml_import"
if (Test-Path $tempDir) { Remove-Item -Recurse -Force $tempDir }
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

$epcNames = @("drogon_tables.epc", "drogon_tables.h5", "drogon_activity.epc", "drogon_activity.h5")
foreach ($name in $epcNames) {
    $src = Join-Path $ScriptDir $name
    if (Test-Path $src) {
        Copy-Item $src $tempDir
        Write-Host "  Copied $name to temp dir" -ForegroundColor DarkGray
    } else {
        Write-Host "  WARNING: $name not found at $src" -ForegroundColor Yellow
    }
}
$mountPath = $tempDir.Replace("\", "/")
Write-Host "  Mount path: $mountPath" -ForegroundColor DarkGray
Write-Host ""

# ── Step 1: List dataspaces ────────────────────────────────────────────────

Write-Host "=== Step 1: List dataspaces ===" -ForegroundColor Cyan
$listCmd = "$space_root_cmd space --list"
Write-Host "  Running list..." -ForegroundColor DarkGray
if ($DryRun) {
    Write-Host "  [DRY-RUN] docker run --rm --entrypoint=sh $DOCKER_IMAGE -c ""$($listCmd -replace '--jwt-token\s+\S+','--jwt-token <TOKEN>')""" -ForegroundColor DarkGray
} else {
    docker run --rm --entrypoint=sh $DOCKER_IMAGE -c "$listCmd"
}
Write-Host ""

# ── Step 2: Create dataspace ──────────────────────────────────────────────

if (-not $SkipCreate) {
    Write-Host "=== Step 2: Delete + re-create dataspace '$DataspaceName' ===" -ForegroundColor Cyan

    # Try to delete existing dataspace (ignore errors if it doesn't exist)
    $deleteCmd = "$space_root_cmd space --delete -s $DataspaceName"
    Write-Host "  Deleting existing dataspace (if any)..." -ForegroundColor DarkGray
    if (-not $DryRun) {
        docker run --rm --entrypoint=sh $DOCKER_IMAGE -c "$deleteCmd" 2>$null
        Start-Sleep -Seconds 2
    }

    $domain = "$DATA_PARTITION_ID.dataservices.energy"
    # Build xdata JSON — single quotes in the sh command protect the double quotes
    $xdataRaw = "{""legaltags"":[""$LEGAL_TAG""],""otherRelevantDataCountries"":[""NO""],""owners"":[""data.default.owners@$domain""],""viewers"":[""data.default.viewers@$domain""]}"

    $createCmd = "$space_root_cmd space --new -s $DataspaceName --xdata '$xdataRaw'"
    Write-Host "  Creating dataspace..." -ForegroundColor DarkGray
    if ($DryRun) {
        Write-Host "  [DRY-RUN] docker run --rm --entrypoint=sh $DOCKER_IMAGE -c ""...create...""" -ForegroundColor DarkGray
    } else {
        docker run --rm --entrypoint=sh $DOCKER_IMAGE -c "$createCmd"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  WARNING: create returned exit code $LASTEXITCODE (dataspace may already exist)" -ForegroundColor DarkYellow
        }
    }
    Write-Host ""
} else {
    Write-Host "=== Step 2: Skipping dataspace creation ===" -ForegroundColor DarkGray
    Write-Host ""
}

# ── Step 3: Import EPC files ──────────────────────────────────────────────

Write-Host "=== Step 3: Import EPC files ===" -ForegroundColor Cyan
$epcToImport = @("drogon_tables.epc", "drogon_activity.epc")

foreach ($epcName in $epcToImport) {
    $epcFull = Join-Path $tempDir $epcName
    if (-not (Test-Path $epcFull)) {
        Write-Host "  ERROR: $epcName not found in temp dir — run gen_resqml.py first" -ForegroundColor Red
        exit 1
    }

    $importCmd = "$space_root_cmd space -s $DataspaceName --import-epc /data/$epcName"
    Write-Host "  Importing $epcName ..." -ForegroundColor Yellow
    if ($DryRun) {
        Write-Host "  [DRY-RUN] docker run --rm -v ${mountPath}:/data --entrypoint=sh $DOCKER_IMAGE -c ""...import $epcName...""" -ForegroundColor DarkGray
    } else {
        docker run --rm -v "${mountPath}:/data" --entrypoint=sh $DOCKER_IMAGE -c "$importCmd"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR: import of $epcName failed (exit code $LASTEXITCODE)" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host ""
}

# ── Step 4: Stats ─────────────────────────────────────────────────────────

Write-Host "=== Step 4: Verify ===" -ForegroundColor Cyan
$statsCmd = "$space_root_cmd space -s $DataspaceName --stats"
Write-Host "  Running stats..." -ForegroundColor DarkGray
if ($DryRun) {
    Write-Host "  [DRY-RUN] docker run --rm --entrypoint=sh $DOCKER_IMAGE -c ""...stats...""" -ForegroundColor DarkGray
} else {
    docker run --rm --entrypoint=sh $DOCKER_IMAGE -c "$statsCmd"
}

# ── Cleanup temp dir ──────────────────────────────────────────────────────
Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Done." -ForegroundColor Green
