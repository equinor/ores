"""Test all GraphQL presets (both Easy Mode and JSON/GraphQL mode) against live server."""
import requests, json, sys

BASE = 'http://localhost:8000'
URL = f'{BASE}/api/graphql/query'
DS = 'maap/drogon'
DS_LIST = f'["{DS}"]'
DS_ARG = f'dataspace: "{DS}"'
DS_NAME = 'Drogon'
headers = {'Content-Type': 'application/json'}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GraphQL Mode (JSON tab) presets — from GQL_PRESETS in keys.js
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
gql_presets = {
    # Browse & Explore
    'status': '{ status }',
    'dataspaces': '{ dataspaces { path uri } }',
    'types': f'{{ resourceTypes(dataspace: "{DS}") {{ name count }} }}',
    'objects_grid': f'{{ resqmlObjects(dataspace: "{DS}" typeName: "resqml20.obj_PointSetRepresentation" limit: 5) {{ uuid title typeName }} }}',
    'objects_wells': f'{{ resqmlObjects(dataspace: "{DS}" typeName: "resqml20.obj_WellboreFeature" limit: 5) {{ uuid title typeName }} }}',

    # Relations (PASTE-UUID presets — test schema validity only)
    'rel_grid_targets': f'{{ objectRelations(dataspace: "{DS}" typeName: "resqml20.obj_FaultInterpretation" uuid: "PASTE-UUID-HERE" direction: "both") {{ uuid name typeName direction contentType }} }}',
    'rel_well_chain': f'{{ objectRelations(dataspace: "{DS}" typeName: "resqml20.obj_WellboreFeature" uuid: "PASTE-UUID-HERE" direction: "sources") {{ uuid name typeName direction contentType }} }}',

    # Deep Search
    'deep_poro': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_FaultInterpretation" includeRelations: true limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'deep_perm': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_HorizonInterpretation" includeRelations: true limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'deep_sw': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_StratigraphicUnitInterpretation" includeRelations: true limit: 5) {{ totalScanned totalMatched queryDescription objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'deep_all_props': f'{{ horizons: deepSearch({DS_ARG} typeName: "resqml20.obj_GeneticBoundaryFeature" includeRelations: true limit: 5) {{ totalScanned totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} faults: deepSearch({DS_ARG} typeName: "resqml20.obj_TectonicBoundaryFeature" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',

    # Surfaces & Arrays
    'deep_grid2d_horizons': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_PolylineSetRepresentation" includeRelations: true limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'deep_grid2d_arrays': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_Grid2dRepresentation" includeRelations: true includeStatistics: true limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title relations {{ uuid name typeName direction }} properties {{ title kind uom statistics {{ count minValue maxValue mean stdDev }} }} }} }} }}',
    'array_stats': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_PointSetRepresentation" includeRelations: true includeStatistics: true includeSampleValues: true limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title relations {{ uuid name typeName direction }} properties {{ title kind uom statistics {{ count minValue maxValue mean stdDev }} arrays {{ path totalElements statistics {{ count minValue maxValue mean stdDev }} sampleValues }} }} }} }} }}',

    # Stratigraphy
    'strat_column': f'{{ col: deepSearch({DS_ARG} typeName: "resqml20.obj_StratigraphicColumn" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} units: deepSearch({DS_ARG} typeName: "resqml20.obj_StratigraphicUnitInterpretation" includeRelations: true limit: 20) {{ totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'strat_horizons': f'{{ horizons: deepSearch({DS_ARG} typeName: "resqml20.obj_HorizonInterpretation" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'xref_strat_horizons': f'{{ federatedSearch(text: "*" kind: "osdu:wks:work-product-component--HorizonInterpretation:*" dataspaces: {DS_LIST} typeName: "resqml20.obj_HorizonInterpretation" searchCatalog: true searchRddms: true includeRelations: true relationFilter: ["Grid2d", "PointSet", "Boundary", "Stratigraphic", "TriangulatedSet"] limit: 5) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title dataspace foundInCatalog foundInLocalRddms osduId osduKind relations {{ uuid name typeName direction }} }} }} }}',

    # FIRP
    'struct_features_to_reps': f'{{ features: deepSearch({DS_ARG} typeName: "resqml20.obj_GeneticBoundaryFeature" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} faultFeatures: deepSearch({DS_ARG} typeName: "resqml20.obj_TectonicBoundaryFeature" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} }}',
    'struct_faults_graph': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_FaultInterpretation" includeRelations: true limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} }}',
    'struct_org_model': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_OrganizationFeature" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} }}',
    'markers_by_horizon': f'{{ deepSearch({DS_ARG} typeName: "resqml20.obj_WellboreMarkerFrameRepresentation" includeRelations: true limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title typeName relations {{ uuid name typeName direction contentType }} }} }} }}',

    # Well Data (WITSML)
    'deep_well_phit': f'{{ logs: deepSearch(dataspace: "{DS}" typeName: "witsml21.Log" includeRelations: true limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'deep_well_perm': f'{{ deepSearch(dataspace: "{DS}" category: "witsml" titleContains: "A-1" includeRelations: true limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} }}',
    'deep_well_all': f'{{ deepSearch(dataspace: "{DS}" category: "witsml" includeRelations: true includeStatistics: true limit: 10) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title typeName relations {{ uuid name typeName direction }} properties {{ title kind uom statistics {{ count minValue maxValue mean stdDev }} }} }} }} }}',
    'deep_well_gr_filter': f'{{ deepSearch(dataspace: "{DS}" typeName: "witsml21.Log" includeStatistics: true propertyFilter: {{ kind: "GR" arrayFilter: {{ operator: GT, threshold: 50.0 }} }} limit: 5) {{ backend totalScanned totalMatched queryDescription objects {{ uuid title typeName properties {{ title kind uom statistics {{ count minValue maxValue mean stdDev }} matchingCells {{ count total fraction }} }} }} }} }}',
    'witsml_browse_wells': f'{{ wells: deepSearch({DS_ARG} typeName: "witsml21.Well" includeRelations: true limit: 5) {{ backend totalScanned totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} wellbores: deepSearch({DS_ARG} typeName: "witsml21.Wellbore" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} }}',

    # Federated
    'fed_local': f'{{ federatedSearch(text: "*" searchCatalog: false searchRddms: true searchRemoteRddms: false dataspaces: {DS_LIST} limit: 10) {{ totalLocalRddms totalMerged sources hits {{ uuid title typeName dataspace foundInLocalRddms }} }} }}',
    'fed_both': f'{{ federatedSearch(text: "{DS_NAME}" kind: "osdu:wks:work-product-component--*:*" dataspaces: {DS_LIST} searchCatalog: true searchRddms: true searchRemoteRddms: true limit: 10) {{ totalCatalog totalLocalRddms totalRemoteRddms totalMerged sources hits {{ uuid title typeName dataspace foundInCatalog foundInLocalRddms foundInRemoteRddms osduId osduKind }} }} }}',
    'fed_enrich': f'{{ federatedSearch(text: "*" dataspaces: {DS_LIST} typeName: "resqml20.obj_HorizonInterpretation" searchCatalog: true searchRddms: true includeRelations: true limit: 5) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title typeName dataspace foundInCatalog foundInLocalRddms relations {{ uuid name typeName direction }} }} }} }}',

    # Cross-system
    'xref_grid_props': f'{{ federatedSearch(text: "*" kind: "osdu:wks:work-product-component--FaultInterpretation:*" dataspaces: {DS_LIST} typeName: "resqml20.obj_FaultInterpretation" searchCatalog: true searchRddms: true includeRelations: true limit: 5) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title typeName dataspace foundInCatalog foundInLocalRddms osduId osduKind relations {{ uuid name typeName direction }} }} }} }}',
    'xref_horizon_reps': f'{{ federatedSearch(text: "*" kind: "osdu:wks:work-product-component--HorizonInterpretation:*" dataspaces: {DS_LIST} typeName: "resqml20.obj_HorizonInterpretation" searchCatalog: true searchRddms: true includeRelations: true relationFilter: ["Grid2d", "PointSet", "TriangulatedSet"] limit: 5) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title dataspace foundInCatalog foundInLocalRddms osduId osduKind relations {{ uuid name typeName direction }} }} }} }}',
    'xref_orphan_rddms': f'{{ federatedSearch(text: "{DS_NAME}" kind: "osdu:wks:work-product-component--*:*" dataspaces: {DS_LIST} searchCatalog: true searchRddms: true limit: 20) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title typeName dataspace foundInCatalog foundInLocalRddms osduId }} }} }}',
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Easy Mode presets — simulates the template builder
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
    # relations (PASTE-UUID)
    'ez_relations': f'{{ objectRelations(dataspace: "{DS}" typeName: "resqml20.obj_IjkGridRepresentation" uuid: "PASTE-UUID-HERE" direction: "both") {{ uuid name typeName direction contentType }} }}',
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


def run_tests(label, presets):
    print(f'\n{"="*70}')
    print(f'  {label} ({len(presets)} presets)')
    print(f'{"="*70}\n')
    ok = err = 0
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
            else:
                summary = summarize(data['data'])
                print(f'  OK     {name}: {summary}')
                ok += 1
        except Exception as e:
            print(f'  FAIL   {name}: {e}')
            err += 1
    return ok, err


print(f'Testing against {URL} (ds={DS})\n')

ok1, err1 = run_tests('GraphQL Mode (JSON tab) presets', gql_presets)
ok2, err2 = run_tests('Easy Mode presets', easy_presets)

total_ok = ok1 + ok2
total_err = err1 + err2
total = total_ok + total_err

print(f'\n{"="*70}')
print(f'  TOTAL: {total_ok}/{total} OK, {total_err} errors')
print(f'    GraphQL Mode: {ok1}/{ok1+err1}')
print(f'    Easy Mode:    {ok2}/{ok2+err2}')
print(f'{"="*70}')

sys.exit(1 if total_err > 0 else 0)
