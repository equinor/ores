


*   **Auth** via your AAD `refresh_token` (v2 first, v1 fallback), using the same defaults and pattern as your `ingest.py`. [1](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/ingest.py)[2](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/equinordev.postman_environment.json)
*   **Discover** all objects in an RD‑DMS dataspace with `GET /dataspaces/{dataspaceId}/resources/all` and collect their **URIs** (the collection does this in the “MA1. Get All Resources Uris” step). [3](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/Reservoir%20DMS.postman_collection.json)
*   **Build** an OSDU manifest from those URIs using `POST /api/reservoir-ddms/v2/manifests/build`, with default **ACL** (partition viewers/owners) and **legal** (`{partition}-equinor-private-default`, `NO`), just like the Postman flow (“MA2. Build EQN Manifest”). Overrides are available on the CLI. [3](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/Reservoir%20DMS.postman_collection.json)
*   **Ingest** the manifest via the OSDU **Workflow service** `POST /api/workflow/v1/workflow/Osdu_ingest/workflowRun` using the same wrapper as `ingest.py`. [1](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/ingest.py)

***

## ✅ Deliverable

**Python script** — build a manifest from an RD‑DMS dataspace and ingest it:

[**rddms\_build\_ingest.py**](blob:https://m365.cloud.microsoft/613667a3-2725-4b8d-ae88-197491fe15c0)

### What it does

1.  **Auth** (via refresh token)\
    Uses your defaults for AAD Authority, Client ID, Tenant ID, Scope/Resource; these match your `equinordev` Postman environment. [2](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/equinordev.postman_environment.json)

2.  **Discover** dataspace content\
    Calls RD‑DMS `GET /dataspaces/{dataspaceId}/resources/all` (pagination supported; optional filter for `dataObjectTypes`). [3](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/Reservoir%20DMS.postman_collection.json)

3.  **Collect URIs**\
    Extracts the `"uri"` property from each resource, de‑duplicates, and builds the list you’d have in Postman’s `all_uris`. [3](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/Reservoir%20DMS.postman_collection.json)

4.  **Build the manifest**\
    Calls `POST {OSDU_HOST}/api/reservoir-ddms/v2/manifests/build` with:

```json
{
  "uris": ["eml:///dataspace('demo/volve5')/…"],
  "acl": {
    "viewers": ["data.default.viewers@data.dataservices.energy"],
    "owners":  ["data.default.owners@data.dataservices.energy"]
  },
  "legal": {
    "legaltags": ["data-equinor-private-default"],
    "otherRelevantDataCountries": ["NO"]
  },
  "createMissingReferences": true
}
```

This mirrors your collection’s body and defaults, but is **CLI‑overridable** (e.g., `--viewers`, `--owners`, `--legaltags`, `--countries`). [3](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/Reservoir%20DMS.postman_collection.json)

5.  **Ingest via Workflow service**\
    Submits the built manifest to `POST /api/workflow/v1/workflow/Osdu_ingest/workflowRun` with the same wrapper `{"executionContext":{"Payload":…,"manifest":…}}` you use in `ingest.py`. [1](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/ingest.py)

***

## How the script maps to your Postman collection

| Postman step                    | HTTP call                                                | What my script does                                                                                                                                                                                                                                                                           |
| ------------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **MA1. Get All Resources Uris** | `GET /dataspaces/{dataspaceId}/resources/all`            | `list_resources_all(...)` + `collect_uris(...)` (pagination, optional type filter). [3](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/Reservoir%20DMS.postman_collection.json)                                                  |
| **MA2. Build EQN Manifest**     | `POST /api/reservoir-ddms/v2/manifests/build`            | `build_manifest(...)` with ACL/Legal defaults: viewers/owners groups and `data-equinor-private-default`. CLI flags let you override. [3](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/Reservoir%20DMS.postman_collection.json) |
| **Ingest**                      | `POST /api/workflow/v1/workflow/Osdu_ingest/workflowRun` | `ingest_manifest_via_workflow(...)`, same wrapper as `ingest.py`. [1](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/ingest.py)                                                                                                  |

**Service base addresses & IDs** are taken from your `equinordev` Postman environment (AAD tenant/client, scopes, and hosts). Defaults in the script reflect those values. [2](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/equinordev.postman_environment.json)

***

## Usage

> **Prereq**: Set an environment variable `refresh_token` (the script exchanges it for an `access_token`).

Common examples:

```bash
# 1) Build from all objects in a dataspace and ingest via Workflow
python rddms_build_ingest.py --dataspace "demo/volve5" -v

# 2) Filter to specific Energistics types (as RD-DMS understands them)
python rddms_build_ingest.py --dataspace "demo/volve5" \
  --data-object-types "resqml20.obj_Grid2dRepresentation,resqml20.obj_HorizonInterpretation"

# 3) Dry-run: build the manifest, save to a file, skip ingest
python rddms_build_ingest.py --dataspace "demo/volve5" --out manifest.json --no-ingest

# 4) Override ACL/legal explicitly (defaults come from Postman env)
python rddms_build_ingest.py --dataspace "demo/volve5" \
  --viewers "data.default.viewers@data.dataservices.energy" \
  --owners  "data.default.owners@data.dataservices.energy" \
  --legaltags "data-equinor-private-default" \
  --countries "NO"
```

**Optional overrides** (CLI or env):

*   `--osdu-host` (default `https://equinordev.energy.azure.com`) and `--rddms-host` (defaults to `${OSDU_HOST}/api/reservoir-ddms/v2`). [2](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/equinordev.postman_environment.json)[3](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/Reservoir%20DMS.postman_collection.json)
*   `--partition` (default `data`), passed as `data-partition-id` header. [2](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/equinordev.postman_environment.json)
*   `--data-object-types` to reduce scope at the RD‑DMS listing call. [3](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/Reservoir%20DMS.postman_collection.json)

> The script always includes **ACL and legal** in the `build` request and the resulting manifest—matching your “not optional” requirement. Defaults come from the collection and the environment, but you can override via CLI when needed. [3](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/Reservoir%20DMS.postman_collection.json)[2](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/equinordev.postman_environment.json)

***

## Sequence (at a glance)



*   Listing and build endpoints per RD‑DMS collection. [3](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/Reservoir%20DMS.postman_collection.json)
*   Workflow wrapper per `ingest.py`. [1](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/ingest.py)

***

## Implementation details

*   **Auth**: v2 token endpoint `…/oauth2/v2.0/token` with `OSDU_SCOPE`; fallback v1 endpoint `…/oauth2/token` with `OSDU_RESOURCE`, just like `ingest.py`. [1](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/ingest.py)[2](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/equinordev.postman_environment.json)
*   **Hosts/IDs**: defaults align with `equinordev`:\
    `OSDU_HOST=https://equinordev.energy.azure.com`,\
    `RESERVOIR_DDMS_HOST=${OSDU_HOST}/api/reservoir-ddms/v2`,\
    `OSDU_PARTITION=data`, `OSDU_TENANT_ID=…`, `OSDU_CLIENT_ID=…`, etc. [2](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/equinordev.postman_environment.json)
*   **RD‑DMS discovery**: `resources/all` supports `$skip`, `$top` and `dataObjectTypes`. The script paginates until completion and can cap the count via `--max-items`. [3](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/Reservoir%20DMS.postman_collection.json)
*   **Manifest build**: mirrors your Postman body; `createMissingReferences=true` to resolve gaps. [3](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/Reservoir%20DMS.postman_collection.json)
*   **Ingest**: uses the **Workflow** path (not direct legacy ingest), as in your `ingest.py` default mode. [1](https://statoilsrm-my.sharepoint.com/personal/maap_equinor_com/Documents/Microsoft%20Copilot%20Chat%20Files/ingest.py)

***

## The file

*   Download the script here: [rddms\_build\_ingest.py](blob:https://m365.cloud.microsoft/613667a3-2725-4b8d-ae88-197491fe15c0)

***

### Want me to tailor it further?

*   Add **type‑specific selection rules** (e.g., only RESQML grids tied to specific horizons).
*   Implement **parallel page fetch** for very large dataspaces.
*   Add a **“dry‑run summary”** of expected WorkProductComponents before ingest.

If you share one of your target dataspaces (name + which dataObjectTypes to include/exclude), I’ll wire those defaults into the script so it’s one command for your team.
