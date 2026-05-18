"""
app/tokenstore.py - Persistent per-user refresh-token store.

Security features:
  • Refresh tokens are **encrypted at rest** using Fernet symmetric
    encryption derived from ``SECRET_KEY``.
  • Composite primary key ``(oid, instance_name)`` so tokens from
    different OSDU instances never collide.
  • A single module-level SQLite connection protected by a
    ``threading.Lock`` avoids "database is locked" errors.
  • Access tokens are cached **in-memory only** (never persisted).

The database path defaults to ``/data/ores_tokens.db`` (writable in k8s
via a PVC) and falls back to ``./ores_tokens.db`` for local dev.
Override with the ``TOKEN_DB_PATH`` env var.

Schema (v2)
-----------
sessions(oid, instance_name, refresh_token_enc, upn, updated_at)
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("rddms-admin.tokenstore")

# ── Encryption (Fernet from cryptography, derived from SECRET_KEY) ───────────

_fernet = None
_fernet_init = False          # distinguish "not yet tried" from "unavailable"


def _get_fernet():
    global _fernet, _fernet_init
    if _fernet_init:
        return _fernet
    _fernet_init = True
    try:
        from cryptography.fernet import Fernet
        key = os.getenv("SECRET_KEY", "")
        if not key:
            log.warning("SECRET_KEY not set - token encryption uses empty key (INSECURE)")
            key = "insecure-default"
        dk = hashlib.sha256(key.encode()).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(dk))
    except ImportError:
        log.warning("cryptography package not installed - tokens stored unencrypted")
        _fernet = None
    return _fernet


def _encrypt(plaintext: str) -> str:
    f = _get_fernet()
    if f:
        return f.encrypt(plaintext.encode()).decode()
    return plaintext


def _decrypt(ciphertext: str) -> Optional[str]:
    f = _get_fernet()
    if not f:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        log.warning("tokenstore: decryption failed (SECRET_KEY changed?) - token invalidated")
        return None


# ── DB connection (module-level, lazy, thread-safe) ──────────────────────────

_DEFAULT_PATHS = ["/data/ores_tokens.db", "./ores_tokens.db"]

_db_path: Optional[Path] = None
_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()


def _resolve_db_path() -> Path:
    env = os.getenv("TOKEN_DB_PATH")
    candidates = [env] if env else _DEFAULT_PATHS
    for p in candidates:
        if not p:
            continue
        try:
            path = Path(p)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            return path
        except OSError:
            continue
    return Path("./ores_tokens.db")


def _get_conn() -> sqlite3.Connection:
    """Return the module-level connection, creating it on first call."""
    global _conn, _db_path
    if _conn is not None:
        return _conn
    if _db_path is None:
        _db_path = _resolve_db_path()
    _conn = sqlite3.connect(str(_db_path), check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
               oid             TEXT NOT NULL,
               instance_name   TEXT NOT NULL DEFAULT '',
               refresh_token_enc TEXT NOT NULL,
               upn             TEXT DEFAULT '',
               updated_at      REAL NOT NULL,
               PRIMARY KEY (oid, instance_name)
           )"""
    )
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS saved_queries (
               id              INTEGER PRIMARY KEY AUTOINCREMENT,
               oid             TEXT NOT NULL DEFAULT '',
               instance_name   TEXT NOT NULL DEFAULT '',
               name            TEXT NOT NULL,
               kind            TEXT NOT NULL DEFAULT '',
               query           TEXT NOT NULL DEFAULT '*',
               created_at      REAL NOT NULL
           )"""
    )
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS weco_workflows (
               id              INTEGER PRIMARY KEY AUTOINCREMENT,
               oid             TEXT NOT NULL DEFAULT '',
               name            TEXT NOT NULL,
               demo_id         TEXT NOT NULL DEFAULT '',
               dataspace       TEXT NOT NULL DEFAULT '',
               options         TEXT NOT NULL DEFAULT '{}',
               n_best          INTEGER NOT NULL DEFAULT 5,
               well_ids        TEXT NOT NULL DEFAULT '[]',
               notes           TEXT NOT NULL DEFAULT '',
               updated_at      REAL NOT NULL
           )"""
    )
    _conn.commit()
    log.info("tokenstore: opened %s", _db_path)
    return _conn


# ── In-memory access-token cache (never persisted) ──────────────────────────

_at_cache: dict[tuple[str, str], tuple[str, float]] = {}


def get_cached_at(oid: str, instance: str) -> Optional[str]:
    """Return a cached access token if still valid, else ``None``."""
    cached = _at_cache.get((oid, instance))
    if cached and time.time() < cached[1]:
        return cached[0]
    return None


def set_cached_at(oid: str, instance: str, at: str, exp: float) -> None:
    """Cache an access token in memory (never written to disk)."""
    _at_cache[(oid, instance)] = (at, exp)


def clear_cached_at(oid: str, instance: str) -> None:
    _at_cache.pop((oid, instance), None)


# ── Public API ────────────────────────────────────────────────────────────────

def upsert(oid: str, instance: str, refresh_token: str, upn: str = "") -> None:
    """Persist (or update) the refresh token for ``(oid, instance)``."""
    if not oid or not refresh_token:
        return
    enc = _encrypt(refresh_token)
    try:
        with _lock:
            conn = _get_conn()
            conn.execute(
                """INSERT INTO sessions (oid, instance_name, refresh_token_enc, upn, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(oid, instance_name) DO UPDATE SET
                       refresh_token_enc = excluded.refresh_token_enc,
                       upn               = excluded.upn,
                       updated_at        = excluded.updated_at""",
                (oid, instance, enc, upn, time.time()),
            )
            conn.commit()
        log.debug("tokenstore: upserted for oid=%s inst=%s", oid[:8], instance)
    except Exception as exc:
        log.warning("tokenstore.upsert failed: %s", exc)


def fetch(oid: str, instance: str) -> Optional[str]:
    """Return the decrypted refresh token for ``(oid, instance)``, or ``None``."""
    if not oid:
        return None
    try:
        with _lock:
            conn = _get_conn()
            row = conn.execute(
                "SELECT refresh_token_enc FROM sessions WHERE oid = ? AND instance_name = ?",
                (oid, instance),
            ).fetchone()
        if row:
            return _decrypt(row[0])
    except Exception as exc:
        log.warning("tokenstore.fetch failed: %s", exc)
    return None


def delete(oid: str, instance: str = "") -> None:
    """Remove a user's stored token (called on logout)."""
    if not oid:
        return
    try:
        with _lock:
            conn = _get_conn()
            if instance:
                conn.execute(
                    "DELETE FROM sessions WHERE oid = ? AND instance_name = ?",
                    (oid, instance),
                )
            else:
                conn.execute("DELETE FROM sessions WHERE oid = ?", (oid,))
            conn.commit()
        clear_cached_at(oid, instance)
        log.debug("tokenstore: deleted for oid=%s inst=%s", oid[:8], instance)
    except Exception as exc:
        log.warning("tokenstore.delete failed: %s", exc)


# ── Saved queries ─────────────────────────────────────────────────────────────

def save_query(oid: str, instance: str, name: str, kind: str, query: str) -> Optional[int]:
    """Save a search query. Returns the row id, or None on failure."""
    try:
        with _lock:
            conn = _get_conn()
            cur = conn.execute(
                """INSERT INTO saved_queries (oid, instance_name, name, kind, query, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (oid or "", instance or "", name, kind or "", query or "*", time.time()),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as exc:
        log.warning("tokenstore.save_query failed: %s", exc)
        return None


def list_queries(oid: str, instance: str) -> list[dict]:
    """Return all saved queries for (oid, instance), newest first."""
    try:
        with _lock:
            conn = _get_conn()
            rows = conn.execute(
                """SELECT id, name, kind, query, created_at
                   FROM saved_queries
                   WHERE oid = ? AND instance_name = ?
                   ORDER BY created_at DESC""",
                (oid or "", instance or ""),
            ).fetchall()
        return [
            {"id": r[0], "name": r[1], "kind": r[2], "query": r[3], "created_at": r[4]}
            for r in rows
        ]
    except Exception as exc:
        log.warning("tokenstore.list_queries failed: %s", exc)
        return []


def delete_query(query_id: int, oid: str = "") -> bool:
    """Delete a saved query by id. If oid is given, enforce ownership."""
    try:
        with _lock:
            conn = _get_conn()
            if oid:
                conn.execute(
                    "DELETE FROM saved_queries WHERE id = ? AND oid = ?",
                    (query_id, oid),
                )
            else:
                conn.execute("DELETE FROM saved_queries WHERE id = ?", (query_id,))
            conn.commit()
            return True
    except Exception as exc:
        log.warning("tokenstore.delete_query failed: %s", exc)
        return False


# ── WeCo workflow storage ─────────────────────────────────────────────────────

def save_workflow(oid: str, name: str, demo_id: str = "", dataspace: str = "",
                  options: str = "{}", n_best: int = 5,
                  well_ids: str = "[]", notes: str = "",
                  workflow_id: Optional[int] = None) -> Optional[int]:
    """Save or update a WeCo workflow configuration. Returns row id."""
    try:
        with _lock:
            conn = _get_conn()
            if workflow_id:
                conn.execute(
                    """UPDATE weco_workflows
                       SET name=?, demo_id=?, dataspace=?, options=?,
                           n_best=?, well_ids=?, notes=?, updated_at=?
                       WHERE id=? AND oid=?""",
                    (name, demo_id, dataspace, options, n_best,
                     well_ids, notes, time.time(), workflow_id, oid or ""),
                )
                conn.commit()
                return workflow_id
            else:
                cur = conn.execute(
                    """INSERT INTO weco_workflows
                       (oid, name, demo_id, dataspace, options, n_best, well_ids, notes, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (oid or "", name, demo_id, dataspace, options, n_best,
                     well_ids, notes, time.time()),
                )
                conn.commit()
                return cur.lastrowid
    except Exception as exc:
        log.warning("tokenstore.save_workflow failed: %s", exc)
        return None


def list_workflows(oid: str) -> list[dict]:
    """Return all saved WeCo workflows for the user, newest first."""
    try:
        with _lock:
            conn = _get_conn()
            rows = conn.execute(
                """SELECT id, name, demo_id, dataspace, options, n_best,
                          well_ids, notes, updated_at
                   FROM weco_workflows
                   WHERE oid = ?
                   ORDER BY updated_at DESC""",
                (oid or "",),
            ).fetchall()
        return [
            {"id": r[0], "name": r[1], "demo_id": r[2], "dataspace": r[3],
             "options": r[4], "n_best": r[5], "well_ids": r[6],
             "notes": r[7], "updated_at": r[8]}
            for r in rows
        ]
    except Exception as exc:
        log.warning("tokenstore.list_workflows failed: %s", exc)
        return []


def get_workflow(workflow_id: int, oid: str = "") -> Optional[dict]:
    """Get a single workflow by id, enforcing ownership."""
    try:
        with _lock:
            conn = _get_conn()
            row = conn.execute(
                """SELECT id, name, demo_id, dataspace, options, n_best,
                          well_ids, notes, updated_at
                   FROM weco_workflows
                   WHERE id = ? AND oid = ?""",
                (workflow_id, oid or ""),
            ).fetchone()
        if row:
            return {"id": row[0], "name": row[1], "demo_id": row[2],
                    "dataspace": row[3], "options": row[4], "n_best": row[5],
                    "well_ids": row[6], "notes": row[7], "updated_at": row[8]}
    except Exception as exc:
        log.warning("tokenstore.get_workflow failed: %s", exc)
    return None


def delete_workflow(workflow_id: int, oid: str = "") -> bool:
    """Delete a saved workflow by id, enforcing ownership."""
    try:
        with _lock:
            conn = _get_conn()
            if oid:
                conn.execute(
                    "DELETE FROM weco_workflows WHERE id = ? AND oid = ?",
                    (workflow_id, oid),
                )
            else:
                conn.execute("DELETE FROM weco_workflows WHERE id = ?", (workflow_id,))
            conn.commit()
            return True
    except Exception as exc:
        log.warning("tokenstore.delete_workflow failed: %s", exc)
        return False


# ── JWT payload helper ────────────────────────────────────────────────────────

def _b64pad(s: str) -> str:
    return s + "=" * (-len(s) % 4)


def decode_id_token_payload(id_token: str) -> dict:
    """Decode the payload of a JWT without signature verification.

    Only used to extract stable claims (oid, upn/preferred_username).
    Signature is already verified by Azure AD during the PKCE exchange.
    """
    try:
        parts = id_token.split(".")
        if len(parts) < 2:
            return {}
        payload = base64.urlsafe_b64decode(_b64pad(parts[1]))
        return json.loads(payload)
    except Exception as exc:
        log.debug("id_token decode failed: %s", exc)
        return {}
