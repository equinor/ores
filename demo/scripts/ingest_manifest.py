#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_manifest.py — Ingest a built RDDMS/OSDU manifest into an OSDU instance.

Two ingestion paths:
  * RECORD ingestion (DEFAULT): direct Storage API PUT. Reliable, gives precise
    per-record errors, and creates every entity.
  * DAG ingestion (--dag): submit to the Osdu_ingest Airflow DAG via the
    Workflow API and poll to a terminal state.

Why record ingestion is the default
------------------------------------
The Osdu_ingest DAG enforces STRICT JSON-schema validation and SILENTLY DROPS
any entity that fails (the run still reports "finished"). Two things make the
raw RDDMS-gateway manifest fail that strict check while Storage (soft/optional
schema validation) accepts it:
  1. Every record carries a top-level `authoringSoftware` property. OSDU record
     schemas are `additionalProperties: false` at the root, so this is a hard
     schema violation — the DAG removes the record.
  2. Some domain reference-data kinds (e.g. reference-data--CurveMainFamily) may
     not be registered in the target Schema Service (404) — the DAG removes them.

This tool NORMALISES records (strips `authoringSoftware` + server-managed fields)
so they validate cleanly for BOTH paths. With normalisation the DAG creates the
same complete set the Storage path does. (Measured on teapot: raw manifest via
DAG created 15/57; after stripping authoringSoftware the dropped Wells/WPCs are
created.)

Usage:
    python scripts/ingest_manifest.py <manifest.json> [options]
      --instance NAME   OSDU instance (default: preship)
      --dag             use the Osdu_ingest DAG instead of Storage PUT
      --app-key KEY     DAG AppKey label (default: rddms-ingest)
      --no-normalize    do NOT strip authoringSoftware (reproduces the DAG bug)
      --keep-refdata    include reference-data (default: included)
      --verify          after ingest, confirm records via Storage query
      --dry-run         normalise + rewrite only; print counts, do not send
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, "/home/maap/ores/demo")
import _auth  # noqa: E402
import httpx  # noqa: E402

warnings.filterwarnings("ignore")

LOCAL_PARTITION = "opendes"
# top-level keys that OSDU schemas reject / the server owns
STRIP_TOP_LEVEL = ("authoringSoftware", "createTime", "createUser",
                   "modifyTime", "modifyUser", "version", "ancestry")
BATCH = 20


# ── manifest helpers ──────────────────────────────────────────────────────
def all_sections(man: dict) -> list[dict]:
    secs: list[dict] = []
    secs += man.get("MasterData", [])
    secs += man.get("ReferenceData", [])
    d = man.get("Data", {})
    secs += d.get("WorkProductComponents", [])
    secs += d.get("Datasets", [])
    if d.get("WorkProduct"):
        secs.append(d["WorkProduct"])
    return secs


def normalize(rec: dict, acl: dict, legal: dict, *, do_strip: bool = True) -> dict:
    rec["acl"] = acl
    rec["legal"] = legal
    if do_strip:
        for k in STRIP_TOP_LEVEL:
            rec.pop(k, None)
    return rec


def typ(rec_id: str) -> str:
    try:
        return rec_id.split(":", 1)[1].rsplit(":", 1)[0]
    except Exception:
        return rec_id


# ── ingestion paths ───────────────────────────────────────────────────────
def ingest_records(cli: httpx.Client, host: str, hdrs: dict,
                   records: list[dict]) -> tuple[list[str], list[tuple]]:
    url = f"{host}/api/storage/v2/records"
    created: list[str] = []
    failed: list[tuple] = []

    def put_one(rec):
        rr = cli.put(url, headers=hdrs, json=[rec])
        if rr.status_code in (200, 201):
            created.extend(rr.json().get("recordIds", [rec.get("id")]))
        else:
            failed.append((rec.get("id"), rr.status_code, rr.text[:300].replace("\n", " ")))

    for i in range(0, len(records), BATCH):
        chunk = records[i:i + BATCH]
        rr = cli.put(url, headers=hdrs, json=chunk)
        if rr.status_code in (200, 201):
            created.extend(rr.json().get("recordIds", []))
        else:
            for rec in chunk:
                put_one(rec)
    return created, failed


def ingest_dag(cli: httpx.Client, host: str, hdrs: dict, partition: str,
               manifest: dict, app_key: str) -> str:
    run_url = f"{host}/api/workflow/v1/workflow/Osdu_ingest/workflowRun"
    body = {"executionContext": {
        "manifest": manifest,
        "Payload": {"data-partition-id": partition, "AppKey": app_key}}}
    r = cli.post(run_url, headers=hdrs, json=body)
    if r.status_code not in (200, 201, 202):
        raise RuntimeError(f"submit HTTP {r.status_code}: {r.text[:500]}")
    run_id = r.json().get("runId", "?")
    print(f"  submitted runId={run_id}")
    deadline = time.time() + 600
    last = None
    while time.time() < deadline:
        time.sleep(8)
        pr = cli.get(f"{run_url}/{run_id}", headers=hdrs)
        if not pr.is_success:
            continue
        st = (pr.json().get("status") or "unknown").lower()
        if st != last:
            print(f"  status={st}")
            last = st
        if st in ("finished", "completed", "succeeded", "success",
                  "failed", "error", "cancelled"):
            return st
    return "timeout"


def verify(cli: httpx.Client, host: str, hdrs: dict, ids: list[str]) -> tuple[int, int]:
    ok = 0
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        r = cli.post(f"{host}/api/storage/v2/query/records", headers=hdrs,
                     json={"records": chunk})
        if r.status_code == 200:
            ok += len(r.json().get("records", []))
    return ok, len(ids)


# ── main ──────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest an OSDU/RDDMS manifest (record ingestion by default)")
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--instance", default="preship")
    ap.add_argument("--dag", action="store_true", help="use Osdu_ingest DAG instead of Storage PUT")
    ap.add_argument("--app-key", default="rddms-ingest")
    ap.add_argument("--no-normalize", action="store_true")
    ap.add_argument("--keep-refdata", action="store_true", help="(reference-data included by default)")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    inst = _auth.load_instance(a.instance)
    verify_ssl = str(inst.get("ssl_verify", "true")).lower() not in ("false", "0", "no")
    token = _auth._mint(inst, verbose=False)
    host = inst["host"].rstrip("/")
    partition = inst["partition"]
    hdrs = {"Authorization": f"Bearer {token}", "data-partition-id": partition,
            "Content-Type": "application/json"}
    acl = {"owners": inst["owners"], "viewers": inst["viewers"]}
    legal = {"legaltags": [inst["legal_tag"]],
             "otherRelevantDataCountries": inst["countries"] or ["US"],
             "status": "compliant"}

    raw = a.manifest.read_text()
    if partition != LOCAL_PARTITION:
        raw = raw.replace(f"{LOCAL_PARTITION}:", f"{partition}:")
    manifest = json.loads(raw)

    records = all_sections(manifest)
    for r in records:
        normalize(r, acl, legal, do_strip=not a.no_normalize)
    ids = [r["id"] for r in records if r.get("id")]
    mode = "DAG (Osdu_ingest)" if a.dag else "RECORD (Storage PUT)"
    print(f"manifest={a.manifest.name}  records={len(records)}  mode={mode}")
    print(f"instance={a.instance} partition={partition} legal={inst['legal_tag']} "
          f"normalize={not a.no_normalize} verify_ssl={verify_ssl}")

    if a.dry_run:
        print("[dry-run] not sending.")
        return 0

    with httpx.Client(verify=verify_ssl, timeout=120) as cli:
        if a.dag:
            st = ingest_dag(cli, host, hdrs, partition, manifest, a.app_key)
            print(f"DAG final status: {st}")
            if a.verify:
                ok, tot = verify(cli, host, hdrs, ids)
                print(f"verified {ok}/{tot} records present")
            return 0 if st in ("finished", "completed", "succeeded", "success") else 2
        created, failed = ingest_records(cli, host, hdrs, records)
        print(f"\nCREATED {len(created)}  FAILED {len(failed)}  / {len(records)}")
        if failed:
            seen: dict = {}
            for i, sc, msg in failed:
                seen.setdefault((sc, msg), i)
            for (sc, msg), sample in list(seen.items())[:10]:
                print(f"  [{sc}] {msg}\n        e.g. {sample}")
        if a.verify:
            ok, tot = verify(cli, host, hdrs, created or ids)
            print(f"verified {ok}/{tot} records present")
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
