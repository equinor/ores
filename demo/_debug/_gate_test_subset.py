#!/usr/bin/env python3
"""One-off gate test: import drogon22_subset.epc into a fresh test dataspace on
interop using increased --timeout / --transaction-retries / --reconnect-retries
to overcome the large-IJK-array import instability. Then verify via REST and
delete the test dataspace (interop has ETP delete rights).

DOES NOT print tokens.
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
DEMO_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(DEMO_DIR))
from _auth import get_token, load_instance  # noqa: E402

INSTANCE = sys.argv[1] if len(sys.argv) > 1 else "interop"
EPC = SCRIPT_DIR / "drogon22_subset.epc"
IMAGE = "osdu-etp-sslclient"
TEST_DS = "maap/drogon22-sub-test"

inst = load_instance(INSTANCE)
host = inst["host"].replace("https://", "").replace("http://", "").rstrip("/")
partition = inst["partition"]
legal = inst["legal_tag"]
etp_url = f"wss://{host}/api/reservoir-ddms-etp/v2/"
base_rddms = f"https://{host}/api/reservoir-ddms/v2"
token = get_token(INSTANCE, verbose=False)
hdr = {"Authorization": f"Bearer {token}", "data-partition-id": partition}

tok = SCRIPT_DIR / ".etp_token"
tok.write_text(token)


def run(inner: str, timeout: int):
    cmd = ["docker", "run", "--rm", "-v", f"{SCRIPT_DIR}:/data",
           "--entrypoint=sh", IMAGE, "-c", inner]
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


try:
    # fresh dataspace (delete via ETP if present, create via REST)
    print(f"=== create fresh {TEST_DS} on {INSTANCE} ===")
    run(f"export JWT=$(cat /data/.etp_token) && /bin/openETPServer space "
        f"--server-url {etp_url} --data-partition-id {partition} "
        f"--auth bearer --jwt-token $JWT -s {TEST_DS} --delete", 120)
    time.sleep(2)
    payload = [{
        "DataspaceId": TEST_DS, "Path": TEST_DS,
        "CustomData": {"legaltags": [legal],
                       "otherRelevantDataCountries": ["NO"],
                       "owners": inst["owners"], "viewers": inst["viewers"]},
    }]
    cr = httpx.post(f"{base_rddms}/dataspaces", headers=hdr,
                    json=payload, timeout=30)
    print(f"  REST create status: {cr.status_code} {cr.text[:120]}")
    time.sleep(3)

    print(f"\n=== import {EPC.name} (timeout 60s,120s; retries) ===")
    inner = (
        f"export JWT=$(cat /data/.etp_token) && /bin/openETPServer space "
        f"--server-url {etp_url} --data-partition-id {partition} "
        f"--auth bearer --jwt-token $JWT -s {TEST_DS} "
        f"--import-epc /data/{EPC.name} -j -M 50MB "
        f"--timeout 60s,120s --transaction-retries 5 --reconnect-retries 5"
    )
    cmd = ["docker", "run", "--rm", "-v", f"{SCRIPT_DIR}:/data",
           "--entrypoint=sh", IMAGE, "-c", inner]
    res = subprocess.run(cmd, text=True, timeout=900)
    print(f"import rc={res.returncode}")

    print("\n=== verify via REST ===")
    ds_enc = TEST_DS.replace("/", "%2F")
    rr = httpx.get(f"{base_rddms}/dataspaces/{ds_enc}/resources",
                   headers=hdr, timeout=30)
    if rr.is_success:
        rl = rr.json()
        total = sum(t.get("count", 0) for t in rl) if isinstance(rl, list) else 0
        print(f"  {total} objects across {len(rl)} types")
        for t in sorted(rl, key=lambda x: -x.get("count", 0)):
            print(f"    {t.get('count'):4d}  {t.get('name','?').split('/')[-1]}")
    else:
        print(f"  verify failed: {rr.status_code} {rr.text[:200]}")
finally:
    tok.unlink(missing_ok=True)
