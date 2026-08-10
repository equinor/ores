"""One-shot script: test all GraphQL presets against live interop maap/drogon."""
import requests, json, sys, os

# Use local app
BASE = 'http://localhost:8000'
URL = f'{BASE}/api/graphql/query'
DS = 'maap/drogon'
headers = {'Content-Type': 'application/json'}

presets = {
    # Browse & Explore
    'status': '{ status }',
    'dataspaces': '{ dataspaces { path uri } }',
    'types': f'{{ resourceTypes(dataspace: "{DS}") {{ name count }} }}',
    'objects_grid': f'{{ resqmlObjects(dataspace: "{DS}" typeName: "resqml20.obj_PointSetRepresentation" limit: 5) {{ uuid title typeName }} }}',
    'objects_wells': f'{{ resqmlObjects(dataspace: "{DS}" typeName: "resqml20.obj_WellboreFeature" limit: 5) {{ uuid title typeName }} }}',
    # Relations (UUID-dependent)
    'rel_grid_targets (uuid)': f'{{ objectRelations(dataspace: "{DS}" typeName: "resqml20.obj_FaultInterpretation" uuid: "67eb8600-bc7b-4f34-87ce-ed4c2cb287e8" direction: "both") {{ uuid name typeName direction }} }}',
    'rel_well_chain (uuid)': f'{{ objectRelations(dataspace: "{DS}" typeName: "resqml20.obj_WellboreFeature" uuid: "50495987-88f4-4e39-95c8-0b2624298c47" direction: "sources") {{ uuid name typeName direction }} }}',
    # Deep Search (RESQML)
    'deep_poro (faults)': f'{{ deepSearch(dataspace: "{DS}" typeName: "resqml20.obj_FaultInterpretation" includeRelations: true limit: 5) {{ backend totalScanned totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'deep_perm (horizons)': f'{{ deepSearch(dataspace: "{DS}" typeName: "resqml20.obj_HorizonInterpretation" includeRelations: true limit: 5) {{ backend totalScanned totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'deep_sw (strat units)': f'{{ deepSearch(dataspace: "{DS}" typeName: "resqml20.obj_StratigraphicUnitInterpretation" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'deep_all_props': f'{{ horizons: deepSearch(dataspace: "{DS}" typeName: "resqml20.obj_GeneticBoundaryFeature" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} faults: deepSearch(dataspace: "{DS}" typeName: "resqml20.obj_TectonicBoundaryFeature" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'deep_grid2d_horizons': f'{{ deepSearch(dataspace: "{DS}" typeName: "resqml20.obj_PolylineSetRepresentation" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'deep_grid2d_arrays (uuid)': f'{{ objectArrays(dataspace: "{DS}" typeName: "resqml20.obj_Grid2dRepresentation" uuid: "02a9d0b6-1f7c-4553-994b-5060cd725d6d" includeStatistics: true includeSampleValues: true sampleSize: 3) {{ path dataType dimensions totalElements statistics {{ count minValue maxValue mean stdDev }} sampleValues }} }}',
    'deep_well_gr_filter': f'{{ deepSearch(dataspace: "{DS}" typeName: "witsml21.Log" includeStatistics: true propertyFilter: {{ kind: "GR" arrayFilter: {{ operator: GT, threshold: 50.0 }} }} limit: 5) {{ totalScanned totalMatched objects {{ uuid title properties {{ title kind statistics {{ count minValue maxValue mean }} matchingCells {{ count total fraction }} }} }} }} }}',
    'array_stats (uuid)': f'{{ objectArrays(dataspace: "{DS}" typeName: "resqml20.obj_PointSetRepresentation" uuid: "0633e96a-4928-4f6e-b115-89c75e39b4df" includeStatistics: true includeSampleValues: true sampleSize: 5) {{ path dataType dimensions totalElements statistics {{ count minValue maxValue mean stdDev }} sampleValues }} }}',
    # Stratigraphy
    'strat_column': f'{{ deepSearch(dataspace: "{DS}" typeName: "resqml20.obj_StratigraphicColumn" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'strat_horizons': f'{{ deepSearch(dataspace: "{DS}" typeName: "resqml20.obj_HorizonInterpretation" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    # FIRP
    'struct_features_to_reps': f'{{ deepSearch(dataspace: "{DS}" typeName: "resqml20.obj_GeneticBoundaryFeature" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} }}',
    'struct_faults_graph': f'{{ deepSearch(dataspace: "{DS}" typeName: "resqml20.obj_FaultInterpretation" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} }}',
    'struct_org_model': f'{{ deepSearch(dataspace: "{DS}" typeName: "resqml20.obj_OrganizationFeature" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} }}',
    'markers_by_horizon': f'{{ deepSearch(dataspace: "{DS}" typeName: "resqml20.obj_WellboreMarkerFrameRepresentation" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} }}',
    # Federated
    'fed_local': f'{{ federatedSearch(text: "*" searchCatalog: false searchRddms: true searchRemoteRddms: false dataspaces: ["{DS}"] limit: 10) {{ totalLocalRddms totalMerged sources hits {{ uuid title typeName dataspace foundInLocalRddms }} }} }}',
    'fed_both': f'{{ federatedSearch(text: "Drogon" kind: "osdu:wks:work-product-component--*:*" dataspaces: ["{DS}"] searchCatalog: true searchRddms: true searchRemoteRddms: true limit: 10) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title typeName foundInCatalog foundInLocalRddms }} }} }}',
    'fed_enrich': f'{{ federatedSearch(text: "*" dataspaces: ["{DS}"] typeName: "resqml20.obj_HorizonInterpretation" searchCatalog: true searchRddms: true includeRelations: true limit: 5) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title typeName foundInCatalog foundInLocalRddms relations {{ uuid name typeName direction }} }} }} }}',
    'xref_grid_props': f'{{ federatedSearch(text: "*" kind: "osdu:wks:work-product-component--FaultInterpretation:*" dataspaces: ["{DS}"] typeName: "resqml20.obj_FaultInterpretation" searchCatalog: true searchRddms: true includeRelations: true limit: 5) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title foundInCatalog foundInLocalRddms relations {{ uuid name typeName direction }} }} }} }}',
    'xref_horizon_reps': f'{{ federatedSearch(text: "*" kind: "osdu:wks:work-product-component--HorizonInterpretation:*" dataspaces: ["{DS}"] typeName: "resqml20.obj_HorizonInterpretation" searchCatalog: true searchRddms: true includeRelations: true relationFilter: ["Grid2d", "PointSet", "TriangulatedSet"] limit: 5) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title foundInCatalog foundInLocalRddms relations {{ uuid name typeName direction }} }} }} }}',
    'xref_orphan_rddms': f'{{ federatedSearch(text: "Drogon" kind: "osdu:wks:work-product-component--*:*" dataspaces: ["{DS}"] searchCatalog: true searchRddms: true limit: 20) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title typeName foundInCatalog foundInLocalRddms }} }} }}',
    # WITSML
    'deep_well_phit': f'{{ deepSearch(dataspace: "{DS}" typeName: "witsml21.Log" includeRelations: true limit: 5) {{ backend totalScanned totalMatched objects {{ uuid title relations {{ uuid name typeName direction }} }} }} }}',
    'deep_well_perm': f'{{ deepSearch(dataspace: "{DS}" category: "witsml" titleContains: "A-1" includeRelations: true limit: 5) {{ totalScanned totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} }}',
    'deep_well_all': f'{{ deepSearch(dataspace: "{DS}" category: "witsml" includeRelations: true includeStatistics: true limit: 10) {{ totalScanned totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} properties {{ title kind uom statistics {{ count minValue maxValue mean }} }} }} }} }}',
    'witsml_browse_wells': f'{{ wells: deepSearch(dataspace: "{DS}" typeName: "witsml21.Well" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} wellbores: deepSearch(dataspace: "{DS}" typeName: "witsml21.Wellbore" includeRelations: true limit: 5) {{ totalMatched objects {{ uuid title typeName relations {{ uuid name typeName direction }} }} }} }}',
    # Federated strat
    'xref_strat_horizons': f'{{ federatedSearch(text: "*" kind: "osdu:wks:work-product-component--HorizonInterpretation:*" dataspaces: ["{DS}"] typeName: "resqml20.obj_HorizonInterpretation" searchCatalog: true searchRddms: true includeRelations: true limit: 5) {{ totalCatalog totalLocalRddms totalMerged sources hits {{ uuid title foundInCatalog foundInLocalRddms relations {{ uuid name typeName direction }} }} }} }}',
}

print(f'Testing {len(presets)} presets against {URL} (ds={DS})...\n')
ok = err = empty = 0
for name, query in presets.items():
    try:
        r = requests.post(URL, headers=headers, json={'query': query}, timeout=20)
        data = r.json()
        if data.get('errors'):
            msg = data['errors'][0].get('message', '')[:70]
            print(f'  ERROR  {name}: {msg}')
            err += 1
        elif not data.get('data'):
            print(f'  EMPTY  {name}: no data field')
            empty += 1
        else:
            d = data['data']
            # Summarize results
            parts = []
            for k, v in d.items():
                if isinstance(v, list):
                    parts.append(f'{k}={len(v)}')
                elif isinstance(v, dict) and 'objects' in v:
                    parts.append(f'{k}: {v.get("totalMatched", "?")} matched')
                elif isinstance(v, dict) and 'hits' in v:
                    parts.append(f'{k}: {v.get("totalMerged", "?")} merged ({v.get("totalCatalog",0)}C+{v.get("totalLocalRddms",0)}R)')
                elif isinstance(v, str):
                    parts.append(v[:50])
                else:
                    parts.append(str(v)[:50])
            summary = ' | '.join(parts)
            print(f'  OK     {name}: {summary}')
            ok += 1
    except Exception as e:
        print(f'  FAIL   {name}: {e}')
        err += 1

print(f'\n--- Summary: {ok} OK, {err} errors, {empty} empty ---')
