
# Validate existence of referenced ReferenceData records in OSDU
# Uses: osdu search id <ID> --output json
# Output: ✅ Found / ❌ Missing per ID, plus summary

# ---- Config: list of ReferenceData IDs to check ----
$refs = @(
    # As requested (exact record)
    "dev:reference-data--ReservoirEstimatedVolumeType:EstimatedInPlaceVolumes",

    # From your generator/manifest (ColumnBasedTableType is AdHoc)
    "dev:reference-data--ColumnBasedTableType:AdHoc",

    # Unit of measure used in columns
    "dev:reference-data--UnitOfMeasure:m3",

    # Property types used in columns
    "dev:reference-data--ReservoirEstimatedVolumePropertyType:Bulk",
    "dev:reference-data--ReservoirEstimatedVolumePropertyType:Net",
    "dev:reference-data--ReservoirEstimatedVolumePropertyType:Pore",
    "dev:reference-data--ReservoirEstimatedVolumePropertyType:Hydrocarbon",
    "dev:reference-data--ReservoirEstimatedVolumePropertyType:Oil",
    "dev:reference-data--ReservoirEstimatedVolumePropertyType:AssociatedGas"
)

# ---- Function: check single ID ----
function Test-OsduReferenceDataId {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Id
    )

    try {
        $json = osdu search id $Id --output json 2>$null | ConvertFrom-Json
        # Some OSDU CLIs return an array; some return an object with 'results'
        if ($null -eq $json) {
            return @{ Id = $Id; Found = $false }
        }

        $count =
            if ($json -is [System.Collections.IEnumerable]) { ($json | Measure-Object).Count }
            elseif ($json.PSObject.Properties.Name -contains 'results') { ($json.results | Measure-Object).Count }
            else { 1 } # treat any object as found

        if ($count -gt 0) {
            return @{ Id = $Id; Found = $true }
        } else {
            return @{ Id = $Id; Found = $false }
        }
    }
    catch {
        return @{ Id = $Id; Found = $false; Error = $_.Exception.Message }
    }
}

# ---- Main: iterate and report ----
$results = foreach ($id in $refs) {
    $r = Test-OsduReferenceDataId -Id $id
    if ($r.Found) {
        Write-Host "✅ Found: $($r.Id)" -ForegroundColor Green
    } else {
        Write-Host "❌ Missing: $($r.Id)" -ForegroundColor Red
        if ($r.ContainsKey('Error') -and $r.Error) {
            Write-Host "   ↳ Error: $($r.Error)" -ForegroundColor DarkRed
        }
    }
    $r
}

# ---- Summary ----
$found    = $results | Where-Object { $_.Found }
$missing  = $results | Where-Object { -not $_.Found }

Write-Host ""
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host ("  Found   : {0,2}" -f ($found | Measure-Object).Count) -ForegroundColor Green
Write-Host ("  Missing : {0,2}" -f ($missing | Measure-Object).Count) -ForegroundColor Red

if ($missing) {
    Write-Host "Missing IDs:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  - $($_.Id)" -ForegroundColor Red }
}
