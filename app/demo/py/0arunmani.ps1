# Optional: only if not already set for ingest
$env:AAD_AUTHORITY  = "https://login.microsoftonline.com"
$env:OSDU_TENANT_ID = "3aa4a235-b6e2-48d5-9195-7fcf05b459b0"
$env:OSDU_CLIENT_ID = "ebd2bfee-ecba-47b7-a33c-017d0131879d"
$env:OSDU_SCOPE     = "7daee810-3f78-40c4-84c2-7a199428de18/.default openid offline_Access"
$env:OSDU_REDIRECT_URI = "https://oauth.pstmn.io/v1/callback"
$env:OSDU_HOST      = "https://equinorswedev.energy.azure.com"
$env:OSDU_PARTITION = "dev"
$env:DEFAULT_REF_LEGALTAG   = "dev-equinor-osdu-reference-default"
$env:DEFAULT_LEGALTAG   = "dev-equinor-osdu-private-default"
$env:DEFAULT_ACL_OWNER  = "data.default.owners@dev.dataservices.energy"
$env:DEFAULT_ACL_VIEWER = "data.office.global.viewers@dev.dataservices.energy"

# leave OSDU_RESOURCE unset unless you must use v1
# generate for the current partition (defaults from $env:OSDU_PARTITION)

py .\5genreffacetrole.py
py .\5genrefpropertytypes.py
py .\5genrefgeolabelltypes.py
py .\4ingest.py .\reftypes_facetroles.json .\reftypes_revpropertytypes.json .\reftypes_geolabeltypes.json

py .\0genmaster.py
py .\1genrawmanifest.py
py .\2vol2stats.py
# py .\3gengeolabel.py
py .\4ingest.py  .\manifest_masterwp.json .\manifest_wpcraw.json .\manifest_wpcstat.json #.\manifest_geolabelsets.json
  
  
py .\6query.py --from-manifests ref_types_manifest.json raw_volume_cbt_manifest.json agg_volume_cbt_manifest.json geolabelsets_manifest.json --partition dev --summary --whoami
py .\6query.py --kind osdu:wks:reference-data--GeoLabelType:1.0.0 --index-diagnostics --query 'data.Code:"Oil.Volume.Bulk.P10"' --limit 5
py .\6query.py --run-id 512a8874-3a33-4366-83bc-5fa1e750f670
py .\6query.py --from-manifests ref_types_manifest.json --index-diagnostics --verify-storage --entitlements-check --check-legal --show-created-kinds --summary

py -m osducli schema get -k osdu:wks:reference-data--GeoLabelType:1.0.0
py -m osducli dataload ingest -p .\reference_statistics_bundle.json     
py -m osducli dataload ingest -p .\geolabelsets_manifest.json
py -m osducli workflow status -r "7060c6c4-ac58-48d9-be34-25d452db812d"



osdu dataload ingest -p .\manifest_raw.json     
osdu  storage  add -p .\wp.json
osdu  storage get --id  "dev:work-product:c2d69a7c-9074-43df-ae1f-49c89a38a244:1"
osdu schema get -k osdu:wks:reference-data--FacetRole:1.1.0
osdu search query --kind "osdu:wks:reference-data--FacetRole:1.1.0" -l 1000
osdu search query --kind "osdu:wks:reference-data--GeoLabelType:1.0.0" -l 1000
osdu search query --kind "osdu:wks:reference-data--ColumnBasedTableType:1.1.0" -l 1000
osdu search query --kind "osdu:wks:reference-data--ReservoirEstimatedVolumePropertyType:1.0.0" -l 1000
osdu search id "dev:reference-data--ReservoirEstimatedVolumeType:EstimatedInPlaceVolumes"
osdu search query --kind "osdu:wks:master-data--ReservoirSegment:2.0.0*"
osdu search query --kind "osdu:wks:master-data--Reservoir:2.0.0"
osdu search id "dev:reference-data--ColumnBasedTableType:AdHoc"
osdu search id "dev:work-product-component--ReservoirEstimatedVolumes:f6b50968-753a-4e36-bfe1-f3fbbb201fc6:1"
osdu search query --kind "osdu:wks:work-product-component--ReservoirEstimatedVolumes:*"

#check ref 
$refs = @(
    "dev:reference-data--ReservoirEstimatedVolumeType:EstimatedInPlaceVolumes",
    "dev:reference-data--ColumnBasedTableType:ColumnBasedTableInline",
    "dev:reference-data--UnitOfMeasure:m3",
    "dev:reference-data--ReservoirEstimatedVolumePropertyType:Bulk",
    "dev:reference-data--ReservoirEstimatedVolumePropertyType:Net",
    "dev:reference-data--ReservoirEstimatedVolumePropertyType:Pore",
    "dev:reference-data--ReservoirEstimatedVolumePropertyType:HCPV",
    "dev:reference-data--ReservoirEstimatedVolumePropertyType:STOIIP",
    "dev:reference-data--ReservoirEstimatedVolumePropertyType:AssociatedGas"
)

foreach ($id in $refs) {
    $result = osdu search id $id --output json | ConvertFrom-Json
    if ($result.Count -eq 0) {
        Write-Host "❌ Missing: $id"
    } else {
        Write-Host "✅ Found: $id"
    }
}

py query.py --only-geolabelsets --geolabels-name "GeoLabels*" --limit 2000 --summary
py query.py --only-ref --facet-types --facet-roles --ref-namespace data --summary
py query.py --from-manifests .\ref_types_manifest.data.json --summary

python 3gengeolabel.py \
  --in agg_volume_cbt_manifest.json \
  --namespace data \
  --facetrole-version 1.1.0 \
  --glt-version 1.0.0 \
  --emit-masterdata

curl -sS -X POST "https://<your-adme-host>/api/ingestion/v2/ingest" \
  -H "data-partition-id: data" \
  -H "Content-Type: application/json" \
  --data-binary @reference_statistics_bundle.json

curl -sS -X POST "https://<your-adme-host>/api/ingestion/v2/ingest" \
  -H "data-partition-id: data" \
  -H "Content-Type: application/json" \
  --data-binary @geolabelsets_manifest.json


## Pointers to official examples & guidance (as you asked)

*   **ADME tutorial** showing *workflowRun* request body (`executionContext.Payload + manifest`) and how to poll status.  
    [Tutorial: Perform manifest-based file ingestion](https://learn.microsoft.com/en-us/azure/energy-data-services/tutorial-manifest-ingestion)

*   **Manifest structure & load order** (what goes in `ReferenceData`, `MasterData`, `Data`; what’s optional).  
    [Manifest-based ingestion concepts](https://learn.microsoft.com/en-us/azure/energy-data-services/concepts-manifest-ingestion)

*   **GeoLabelSet worked example** (relationships, label value types, and where GeoLabelType fits).  
    [GeoLabels – Worked Example](https://github.com/jonslo/osdu-data-data-definitions/blob/master/Examples/WorkedExamples/ReservoirManagement/GeoLabels/README.md)

*   **FacetRole migration** 1.0.0 → 1.1.0 (use `data.FacetType` for 1.1.0).  
    [FacetRole migration guide](https://github.com/jonslo/osdu-data-data-definitions/blob/master/Guides/MigrationGuides/M21/reference-data--FacetRole.1.0.0.md)

*   **Reference data values in ADME** (FIXED/OPEN/LOCAL sync — why FacetType/FacetRole often exist already).  
    [Reference Data Values in ADME](https://learn.microsoft.com/en-us/azure/energy-data-services/concepts-reference-data-values)

*   **Troubleshoot manifest ingestion** (DAG tasks that evict invalid entities; how to get logs).  
    [Troubleshoot manifest ingestion](https://learn.microsoft.com/en-us/azure/energy-data-services/troubleshoot-manifest-ingestion)

https://community.opengroup.org/osdu/data/data-definitions/-/blob/master/Examples/WorkedExamples/ReservoirManagement/work-product-component/ReservoirEstimatedVolumes-homogeneous.json?ref_type=heads
https://community.opengroup.org/osdu/data/data-definitions/-/blob/master/E-R/reference-data/ReservoirEstimatedVolumePropertyType.1.0.0.md
