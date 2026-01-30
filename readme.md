# OSDU RDDMS admin ui web client


## Install and run

Auth: 
store your adme refresh_token as env variable or in .env file

Requires: 
python libs: uvicorn fastapi httpx jinja2 numpy multipart

Call:
py -m uvicorn app.main:app --reload --port 8000 --host localhost --env-file .\.env

open http://127.0.0.1:8000/


### File Architecture 

```
rddms-admin/
├─ requirements.txt
├─ .env
└─ app/
   ├─ main.py
   ├─ auth.py
   ├─ osdu.py
   ├─ templates/
   │  ├─ base.html
   │  ├─ index.html
   │  ├─ keys.html
   │  ├─ resource.html
   │  ├─ _fragments.html
   |  └─ search.html
   └─ static/

```

### Auth Sequence Diagram

```mermaid
sequenceDiagram
    participant U as User
    participant UI as Admin UI
    participant AAD as Microsoft Identity Platform
    participant RDDMS as Reservoir DDMS
    participant SEARCH as OSDU Search

    U->>UI: GET /login
    UI->>AAD: Redirect /authorize (PKCE)
    AAD->>UI: Redirect /auth/callback?code=...
    UI->>AAD: POST /token (code + code_verifier)
    AAD-->>UI: access_token (+refresh_token)
    U->>UI: Browse
    UI->>RDDMS: Bearer access_token (list types/arrays)
    UI->>SEARCH: POST /api/search/v2/query (data-partition-id)
```

### Manifest Ingestion Sequence Diagram

```mermaid
sequenceDiagram
  participant U as User
  participant UI as Admin UI (FastAPI + JS)
  participant AAD as Azure AD
  participant WF as OSDU Workflow Service

  U->>UI: Click "Create Manifest & Ingest"
  UI->>UI: Build manifest JSON (metadata-first)
  UI->>UI: POST /api/manifest/create-and-ingest
  UI->>U: Stream manifest.json as download (no on-page print)
  Note over UI: Background task starts
  UI-->>WF: POST /api/workflow/v1/workflow/Osdu_ingest/workflowRun<br/>Authorization: Bearer ...<br/>Partition header
  WF-->>UI: 202/200 + run info
  UI-->>U: Status updated (ingest submitted)
```
