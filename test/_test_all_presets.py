"""Test all GraphQL presets (both Easy Mode and JSON/GraphQL mode) against live server.

Verifies:
  1. No GraphQL errors returned
  2. Non-nil results (totalMatched > 0 or hits/objects list non-empty)
"""
import requests, json, sys

BASE = 'http://localhost:8000'
URL = f'{BASE}/api/graphql/query'
DS = 'maap/drogon'
DS_LIST = f'["{DS}"]'
DS_ARG = f'dataspace: "{DS}"'
DS_NAME = 'Drogon'
headers = {'Content-Type': 'application/json'}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GraphQL Mode (JSON tab) presets - from GQL_PRESETS in keys.js
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
gql_presets = {
    # Browse & Explore
    'status': '{ status }',
    'dataspaces': '{ dataspaces { path uri } }',
    'types': f'{{ resourceTypes(dataspace: "{DS}") {{ name count }} }}',
    'objects_grid': f'{{ resqmlObjects(dataspace: "{DS}" typeName: "resqml20.obj_PointSetRepresentation" limit: 5) {{ uuid title typeName }} }}',

    # Relations (requires real UUIDs - resolved dynamically below)
    'rel_grid_targets': None,

    # Deep Search - IjkGrid property filter + array threshold
    'deep_poro': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_IjkGridRepresentation" includeRelations: true includeStatistics: true propertyFilter: {{ kind: "porosity" arrayFilter: {{ operator: GT, threshold: 0.20 }} }} limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title relations {{ uuid name typeName direction }} properties {{ title kind uom statistics {{ count minValue maxValue mean stdDev }} matchingCells {{ count total fraction }} }} }} }} }}',
    'deep_all_props': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_IjkGridRepresentation" includeRelations: true includeStatistics: true limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title relations {{ uuid name typeName direction }} properties {{ title kind uom statistics {{ count minValue maxValue mean stdDev }} }} }} }} }}',

    # Surfaces with sample values
    'deep_grid2d_arrays': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_Grid2dRepresentation" includeRelations: true includeStatistics: true includeSampleValues: true limit: 10) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title relations {{ uuid name typeName direction }} properties {{ title kind uom statistics {{ count minValue maxValue mean stdDev }} arrays {{ path totalElements statistics {{ count minValue maxValue mean stdDev }} sampleValues }} }} }} }} }}',

    # Stratigraphy
    'strat_column': f'{{ col: deepSearch({DS_ARG} typeName: "resqml20.obj_StratigraphicColumn" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} units: deepSearch({DS_ARG} typeName: "resqml20.obj_StratigraphicUnitInterpretation" includeRelations: true limit: 20) {{ totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'xref_strat_horizons': f'{{ federatedSearch(text: "*" kind: "osdu:wks:work-product-component--HorizonInterpretation:*" dataspaces: {DS_LIST} typeName: "resqml20.obj_HorizonInterpretation" searchCatalog: true searchRddms: true includeRelations: true relationFilter: ["Grid2d", "PointSet", "Boundary", "Stratigraphic", "TriangulatedSet"] limit: 5) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title dataspace foundInCatalog foundInLocalRddms osduId osduKind relations {{ uuid name typeName direction }} }} }} }}',

    # FIRP
    'struct_features_to_reps': f'{{ features: deepSearch({DS_ARG} typeName: "resqml20.obj_GeneticBoundaryFeature" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} faultFeatures: deepSearch({DS_ARG} typeName: "resqml20.obj_TectonicBoundaryFeature" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} }}',
    'markers_by_horizon': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_WellboreMarkerFrameRepresentation" includeRelations: true limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title typeName relations {{ uuid name typeName direction contentType }} }} }} }}',

    # Federated
    'fed_enrich': f'{{ federatedSearch(text: "*" dataspaces: {DS_LIST} typeName: "resqml20.obj_HorizonInterpretation" searchCatalog: true searchRddms: true includeRelations: true limit: 5) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title typeName dataspace foundInCatalog foundInLocalRddms relations {{ uuid name typeName direction }} }} }} }}',

    # Cross-system
    'xref_grid_poro_perm': f'{{ federatedSearch(text: "*" kind: "osdu:wks:work-product-component--IjkGridRepresentation:*" dataspaces: {DS_LIST} typeName: "resqml20.obj_IjkGridRepresentation" searchCatalog: true searchRddms: true includeRelations: true includeProperties: true includeStatistics: true propertyFilter: {{ kind: "porosity" arrayFilter: {{ operator: GT, threshold: 0.15 }} }} limit: 5) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title typeName dataspace foundInCatalog foundInLocalRddms osduId osduKind relations {{ uuid name typeName direction }} properties {{ title kind uom statistics {{ count minValue maxValue mean stdDev }} matchingCells {{ count total fraction }} }} }} }} }}',
    'xref_well_grid_props': f'{{ wells: deepSearch({DS_ARG} typeName: "resqml20.obj_WellboreTrajectoryRepresentation" includeRelations: true limit: 10) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title relations {{ uuid name typeName direction }} }} }} grids: deepSearch({DS_ARG} typeName: "resqml20.obj_IjkGridRepresentation" includeRelations: true includeStatistics: true propertyFilter: {{ kind: "porosity" }} limit: 5) {{ totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} properties {{ title kind uom statistics {{ count minValue maxValue mean stdDev }} }} }} }} }}',
    'xref_orphan_rddms': f'{{ federatedSearch(text: "{DS_NAME}" kind: "osdu:wks:work-product-component--*:*" dataspaces: {DS_LIST} searchCatalog: true searchRddms: true limit: 20) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title typeName dataspace foundInCatalog foundInLocalRddms osduId }} }} }}',

    # Native RDDMS GraphQL (M27+ - uses REST fallback on ADME interop)
    'native_graph_traverse': f'{{ nativeGraphSearch(dataspace: "{DS}" typeName: "resqml20.obj_IjkGridRepresentation" depth: 1 limit: 2) {{ backend resources {{ uri name dataObjectType }} edges {{ sourceUri targetUri }} }} }}',
    'native_object_content': f'{{ nativeObjectContent(dataspace: "{DS}" typeName: "resqml20.obj_ContinuousProperty" limit: 1) {{ uri name dataObjectType content }} }}',
    'native_array_metadata': f'{{ nativeArrayMetadata(dataspace: "{DS}" typeName: "resqml20.obj_ContinuousProperty" limit: 2) {{ uri name arrays {{ pathInResource dimensions }} }} }}',
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Easy Mode presets - simulates the template builder
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
easy_presets = {
    # deep_search (no filter)
    'ez_deep_faults': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_FaultInterpretation" includeRelations: true includeStatistics: false includeSampleValues: false limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title typeName relations {{ uuid name typeName direction contentType }} properties {{ title kind uom }} }} }} }}',
    # deep_search with stats
    'ez_deep_grid2d_stats': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_Grid2dRepresentation" includeRelations: true includeStatistics: true includeSampleValues: false limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title typeName relations {{ uuid name typeName direction contentType }} properties {{ title kind uom statistics {{ count minValue maxValue mean stdDev }} }} }} }} }}',
    # deep_search with sample values
    'ez_deep_pointset_sample': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_PointSetRepresentation" includeRelations: false includeStatistics: true includeSampleValues: true limit: 3) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title typeName properties {{ title kind uom statistics {{ count minValue maxValue mean stdDev }} arrays {{ path totalElements statistics {{ count minValue maxValue mean stdDev }} sampleValues }} }} }} }} }}',
    # deep_search with property filter
    'ez_deep_prop_filter': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_IjkGridRepresentation" propertyFilter: {{ titleContains: "PHIT" }} includeRelations: true includeStatistics: true includeSampleValues: false limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title typeName relations {{ uuid name typeName direction contentType }} properties {{ title kind uom statistics {{ count minValue maxValue mean stdDev }} }} }} }} }}',
    # deep_search with array filter (GT)
    'ez_deep_array_filter': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_IjkGridRepresentation" propertyFilter: {{ titleContains: "PHIT" arrayFilter: {{ operator: GT, threshold: 0.2 }} }} includeRelations: false includeStatistics: true includeSampleValues: false limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title typeName properties {{ title kind uom statistics {{ count minValue maxValue mean stdDev }} matchingCells {{ count total fraction }} }} }} }} }}',
    # browse
    'ez_browse': f'{{ resqmlObjects(dataspace: "{DS}" typeName: "resqml20.obj_IjkGridRepresentation" limit: 10) {{ uuid title typeName }} }}',
    # relations (requires a real UUID - resolved dynamically below)
    'ez_relations': None,  # will be filled after browse
    # federated (no filter)
    'ez_federated': f'{{ federatedSearch(text: "*" dataspaces: {DS_LIST} typeName: "resqml20.obj_HorizonInterpretation" searchCatalog: true searchRddms: true searchRemoteRddms: true includeRelations: true includeProperties: false includeStatistics: false limit: 5) {{ totalCatalog totalLocalRddms totalRemoteRddms totalMerged sources hits {{ uuid title typeName dataspace foundInCatalog foundInLocalRddms foundInRemoteRddms relations {{ uuid name typeName direction }} }} }} }}',
    # federated with stats
    'ez_federated_stats': f'{{ federatedSearch(text: "*" dataspaces: {DS_LIST} typeName: "resqml20.obj_FaultInterpretation" searchCatalog: true searchRddms: true searchRemoteRddms: true includeRelations: true includeProperties: true includeStatistics: true limit: 5) {{ totalCatalog totalLocalRddms totalRemoteRddms totalMerged sources hits {{ uuid title typeName dataspace foundInCatalog foundInLocalRddms foundInRemoteRddms relations {{ uuid name typeName direction }} properties {{ title kind statistics {{ count minValue maxValue mean }} }} }} }} }}',
    # cross_system
    'ez_cross_system': f'{{ federatedSearch(text: "*" dataspaces: {DS_LIST} typeName: "resqml20.obj_HorizonInterpretation" searchCatalog: true searchRddms: true searchRemoteRddms: true includeRelations: true includeProperties: true includeStatistics: true limit: 5) {{ totalCatalog totalLocalRddms totalRemoteRddms totalMerged sources queryDescription hits {{ uuid title typeName dataspace foundInCatalog foundInLocalRddms foundInRemoteRddms osduId osduKind relations {{ uuid name typeName direction }} properties {{ title kind uom statistics {{ count minValue maxValue mean stdDev }} }} }} }} }}',
}


def summarize(d):
    parts = []
    for k, v in d.items():
        if isinstance(v, list):
            parts.append(f'{k}={len(v)}')
        elif isinstance(v, dict):
            if 'objects' in v:
                parts.append(f'{k}: {v.get("totalMatched", "?")}m')
            elif 'hits' in v:
                parts.append(f'{k}: {v.get("totalMerged", "?")}merged')
            else:
                parts.append(f'{k}=dict')
        elif isinstance(v, str):
            parts.append(v[:40])
        else:
            parts.append(str(v)[:30])
    return ' | '.join(parts)


def has_results(data):
    """Check if any field in the response has non-empty results."""
    if not data:
        return False
    for k, v in data.items():
        if isinstance(v, str):
            if v:  # status string, etc.
                return True
        elif isinstance(v, list):
            if len(v) > 0:
                return True
        elif isinstance(v, dict):
            if v.get('objects') and len(v['objects']) > 0:
                return True
            if v.get('hits') and len(v['hits']) > 0:
                return True
            if v.get('resources') and len(v['resources']) > 0:
                return True
            if v.get('totalMatched', 0) > 0 or v.get('totalMerged', 0) > 0:
                return True
        elif isinstance(v, (int, float)):
            if v > 0:
                return True
    return False


def run_tests(label, presets):
    print(f'\n{"="*70}')
    print(f'  {label} ({len(presets)} presets)')
    print(f'{"="*70}\n')
    ok = err = nil_results = 0
    for name, query in presets.items():
        try:
            r = requests.post(URL, headers=headers, json={'query': query}, timeout=30)
            data = r.json()
            if data.get('errors'):
                msg = data['errors'][0].get('message', '')[:80]
                print(f'  ERROR  {name}')
                print(f'         {msg}')
                err += 1
            elif not data.get('data'):
                print(f'  EMPTY  {name}: no data field')
                err += 1
            elif not has_results(data['data']):
                summary = summarize(data['data'])
                print(f'  NIL    {name}: query OK but 0 results - {summary}')
                nil_results += 1
            else:
                summary = summarize(data['data'])
                print(f'  OK     {name}: {summary}')
                ok += 1
        except Exception as e:
            print(f'  FAIL   {name}: {e}')
            err += 1
    return ok, err, nil_results


print(f'Testing against {URL} (ds={DS})\n')

# ── Resolve real UUIDs for relation presets ──────────────────────────────
def fetch_uuid(type_name):
    """Fetch one UUID from the RDDMS for the given type."""
    q = f'{{ resqmlObjects(dataspace: "{DS}" typeName: "{type_name}" limit: 1) {{ uuid }} }}'
    try:
        r = requests.post(URL, headers=headers, json={'query': q}, timeout=10)
        objs = r.json().get('data', {}).get('resqmlObjects', [])
        return objs[0]['uuid'] if objs else None
    except Exception:
        return None

fault_uuid = fetch_uuid('resqml20.obj_FaultInterpretation')
grid_uuid = fetch_uuid('resqml20.obj_IjkGridRepresentation')

if fault_uuid:
    gql_presets['rel_grid_targets'] = f'{{ objectRelations(dataspace: "{DS}" typeName: "resqml20.obj_FaultInterpretation" uuid: "{fault_uuid}" direction: "both") {{ uuid name typeName direction contentType }} }}'
if grid_uuid:
    easy_presets['ez_relations'] = f'{{ objectRelations(dataspace: "{DS}" typeName: "resqml20.obj_IjkGridRepresentation" uuid: "{grid_uuid}" direction: "both") {{ uuid name typeName direction contentType }} }}'

# Remove presets that couldn't be resolved (no objects of that type in RDDMS)
gql_presets = {k: v for k, v in gql_presets.items() if v is not None}
easy_presets = {k: v for k, v in easy_presets.items() if v is not None}


ok1, err1, nil1 = run_tests('GraphQL Mode (JSON tab) presets', gql_presets)
ok2, err2, nil2 = run_tests('Easy Mode presets', easy_presets)

total_ok = ok1 + ok2
total_err = err1 + err2
total_nil = nil1 + nil2
total = total_ok + total_err + total_nil

print(f'\n{"="*70}')
print(f'  TOTAL: {total_ok}/{total} OK, {total_err} errors, {total_nil} nil-results')
print(f'    GraphQL Mode: {ok1}/{ok1+err1+nil1} OK, {err1} err, {nil1} nil')
print(f'    Easy Mode:    {ok2}/{ok2+err2+nil2} OK, {err2} err, {nil2} nil')
print(f'{"="*70}')

sys.exit(1 if (total_err > 0 or total_nil > 0) else 0)
