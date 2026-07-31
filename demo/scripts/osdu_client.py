"""
osdu_client.py - Generic OSDU API client for record ingestion and search.

Handles:
  - Authentication via auth.py (multi-instance, cached tokens)
  - Storage API (PUT records, GET records)
  - Search API (query records)
  - Batch operations with retry logic

Fully independent of ORES — works with any OSDU instance.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:
    sys.exit("Missing httpx — pip install httpx")

from .config import OsduInstance


# ── Constants ────────────────────────────────────────────────────────────
BATCH_SIZE = 20           # OSDU Storage API batch limit
MAX_RETRIES = 4
RETRY_BACKOFF = [3, 6, 10, 15]  # seconds
TOKEN_BUFFER = 300        # renew 5 min before expiry


class OsduClient:
    """Generic OSDU platform API client with multi-instance auth support."""

    def __init__(self, instance: OsduInstance, *, token: Optional[str] = None):
        self.instance = instance
        self._explicit_token = token
        self._token: Optional[str] = token
        self._token_expiry: float = 0.0 if not token else time.time() + 3600
        self._http = httpx.Client(timeout=120, follow_redirects=True)

    @classmethod
    def from_instance_name(cls, name: str = "eqndev", *, token: Optional[str] = None) -> "OsduClient":
        """Create client by resolving instance name via auth module.

        This is the recommended constructor — handles full config resolution
        and token management automatically.
        """
        from .auth import resolve_instance, get_token
        instance = resolve_instance(name)
        # Get token (uses cache, env, or mints fresh)
        resolved_token = token or os.environ.get("OSDU_TOKEN", "").strip()
        if not resolved_token:
            try:
                resolved_token = get_token(name, verbose=True)
            except RuntimeError:
                resolved_token = None  # Will fail on first API call
        return cls(instance, token=resolved_token)

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ── Auth ─────────────────────────────────────────────────────────────

    @property
    def token(self) -> str:
        if self._token and time.time() < self._token_expiry:
            return self._token
        self._mint_token()
        return self._token  # type: ignore

    def set_token(self, token: str, expires_in: int = 3600):
        """Set token manually (e.g. from CLI --token flag)."""
        self._token = token
        self._explicit_token = token
        self._token_expiry = time.time() + expires_in - TOKEN_BUFFER

    def _mint_token(self):
        """Mint a new token via the auth module (full resolution chain)."""
        from .auth import get_token as auth_get_token
        try:
            self._token = auth_get_token(self.instance.name, verbose=True)
            self._token_expiry = time.time() + 3000  # conservative
        except RuntimeError as e:
            # Fallback: try direct mint if instance has credentials
            self._mint_token_direct()

    def _mint_token_direct(self):
        """Direct token mint from instance credentials (fallback)."""
        inst = self.instance
        if not inst.tenant_id or not inst.client_id:
            raise RuntimeError(
                "Cannot mint token: missing tenant_id or client_id.\n"
                "Provide a token via --token, OSDU_TOKEN env var, or configure auth.\n"
                "Run: python demo/scripts/cli.py --help for setup instructions."
            )
        url = f"https://login.microsoftonline.com/{inst.tenant_id}/oauth2/v2.0/token"
        data: Dict[str, str] = {"client_id": inst.client_id}

        if inst.refresh_token:
            data["grant_type"] = "refresh_token"
            data["refresh_token"] = inst.refresh_token
            if inst.scope:
                data["scope"] = inst.scope
            else:
                data["scope"] = f"{inst.client_id}/.default openid offline_access"
            if inst.client_secret:
                data["client_secret"] = inst.client_secret
        elif inst.client_secret:
            data["grant_type"] = "client_credentials"
            data["client_secret"] = inst.client_secret
            data["scope"] = inst.scope or f"{inst.client_id}/.default"
        else:
            raise RuntimeError(
                "Cannot mint token: need refresh_token or client_secret.\n"
                "Set OSDU_REFRESH_TOKEN or OSDU_CLIENT_SECRET."
            )

        resp = self._http.post(url, data=data)
        if resp.status_code != 200:
            raise RuntimeError(f"Token mint failed ({resp.status_code}): {resp.text[:500]}")

        body = resp.json()
        self._token = body["access_token"]
        self._token_expiry = time.time() + body.get("expires_in", 3600) - TOKEN_BUFFER

    # ── Headers ──────────────────────────────────────────────────────────

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "data-partition-id": self.instance.partition,
            "Content-Type": "application/json",
        }

    # ── Storage API ──────────────────────────────────────────────────────

    def put_records(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """PUT records to Storage API in batches. Returns aggregated response."""
        url = f"{self.instance.host}/api/storage/v2/records"
        all_ids: List[str] = []
        all_errors: List[Dict[str, Any]] = []

        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i:i + BATCH_SIZE]
            resp_data = self._put_batch(url, batch)
            all_ids.extend(resp_data.get("recordIds", []))
            if "errors" in resp_data:
                all_errors.extend(resp_data["errors"])

        result: Dict[str, Any] = {"recordIds": all_ids, "totalCount": len(all_ids)}
        if all_errors:
            result["errors"] = all_errors
        return result

    def _put_batch(self, url: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """PUT a single batch with retry logic."""
        for attempt in range(MAX_RETRIES + 1):
            resp = self._http.put(url, json=records, headers=self.headers)
            if resp.status_code in (200, 201):
                return resp.json()
            if resp.status_code in (404, 429, 500, 502, 503) and attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                print(f"  ⟳ Retry {attempt + 1}/{MAX_RETRIES} after {wait}s "
                      f"(HTTP {resp.status_code})")
                time.sleep(wait)
                continue
            # Non-retryable error
            raise RuntimeError(
                f"Storage API error ({resp.status_code}): {resp.text[:500]}"
            )
        return {}

    def get_record(self, record_id: str) -> Optional[Dict[str, Any]]:
        """GET a single record by ID."""
        url = f"{self.instance.host}/api/storage/v2/records/{record_id}"
        resp = self._http.get(url, headers=self.headers)
        if resp.status_code == 200:
            return resp.json()
        return None

    def delete_record(self, record_id: str) -> bool:
        """Soft-delete a record."""
        url = f"{self.instance.host}/api/storage/v2/records/{record_id}"
        resp = self._http.delete(url, headers=self.headers)
        return resp.status_code in (200, 204)

    # ── Search API ───────────────────────────────────────────────────────

    def search(self, kind: str, query: str = "*", *, limit: int = 100,
               returned_fields: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Query the OSDU Search API."""
        url = f"{self.instance.host}/api/search/v2/query"
        body: Dict[str, Any] = {
            "kind": kind,
            "query": query,
            "limit": min(limit, 1000),
        }
        if returned_fields:
            body["returnedFields"] = returned_fields

        resp = self._http.post(url, json=body, headers=self.headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Search API error ({resp.status_code}): {resp.text[:500]}")
        return resp.json().get("results", [])

    # ── Validation ───────────────────────────────────────────────────────

    def validate_records(self, records: List[Dict[str, Any]]) -> List[str]:
        """Basic client-side validation before ingestion."""
        errors: List[str] = []
        for i, rec in enumerate(records):
            if "id" not in rec:
                errors.append(f"Record [{i}]: missing 'id'")
            if "kind" not in rec:
                errors.append(f"Record [{i}]: missing 'kind'")
            if "acl" not in rec:
                errors.append(f"Record [{i}]: missing 'acl'")
            if "legal" not in rec:
                errors.append(f"Record [{i}]: missing 'legal'")
            if "data" not in rec:
                errors.append(f"Record [{i}]: missing 'data'")
            # Validate ID format
            rec_id = rec.get("id", "")
            if rec_id and ":" not in rec_id:
                errors.append(f"Record [{i}]: id format invalid (expected partition:type:name:version)")
        return errors
