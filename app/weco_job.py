"""WeCo Correlation Job Worker.

Radix job component that handles heavy correlation workloads.
Receives well data + options via payload, runs engine with higher limits,
returns results via the scheduler API.
"""
import os
import json
import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional

logger = logging.getLogger("weco-job")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

app = FastAPI(title="WeCo Correlation Job", version="1.0.0")

# Job-level limits (higher than web component, controlled via env)
MAX_COR_LIMIT = int(os.environ.get("WECO_MAX_COR", "50"))
THREAD_COUNT = int(os.environ.get("WECO_THREAD", "4"))


class JobPayload(BaseModel):
    """Payload received from the web component via Radix job scheduler."""
    wells_json: str  # JSON-serialized well data
    options: Dict[str, Any] = Field(default_factory=dict)
    n_best: int = 5
    callback_url: Optional[str] = None  # Optional webhook for results


class JobResult(BaseModel):
    status: str
    elapsed_ms: float = 0
    n_wells: int = 0
    n_results: int = 0
    results: List[Dict[str, Any]] = Field(default_factory=list)
    options_used: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


def _apply_job_guards(options: dict, n_wells: int) -> dict:
    """Apply job-level memory guards (more generous than web component)."""
    opts = dict(options)
    opts["thread"] = min(int(opts.get("thread", THREAD_COUNT)), THREAD_COUNT)
    opts["max-cor"] = min(int(opts.get("max-cor", MAX_COR_LIMIT)), MAX_COR_LIMIT)
    if n_wells > 50:
        opts["nbr-cor"] = min(int(opts.get("nbr-cor", 5)), 10)
        opts.setdefault("band-width", 30)
    elif n_wells > 20:
        opts["nbr-cor"] = min(int(opts.get("nbr-cor", 10)), 20)
        opts.setdefault("band-width", 30)
    return opts


@app.get("/")
def health():
    return {"status": "ready", "max_cor_limit": MAX_COR_LIMIT, "threads": THREAD_COUNT}


@app.post("/run")
def run_correlation(payload: JobPayload):
    """Execute correlation job with full resources."""
    try:
        from weco.data import WellList
        from weco.api import _run_engine, _extract_results

        # Deserialize wells
        wl = WellList()
        wells_data = json.loads(payload.wells_json)
        wl.from_dict(wells_data)

        n_wells = len(wl.wells)
        logger.info(f"Job started: {n_wells} wells, options={payload.options}")

        # Apply job-level guards
        safe_opts = _apply_job_guards(payload.options, n_wells)
        logger.info(f"Guarded options: {safe_opts}")

        # Run engine
        t0 = time.perf_counter()
        rf, data, elapsed = _run_engine(wl, safe_opts)
        results = _extract_results(rf, data, payload.n_best)
        total_ms = (time.perf_counter() - t0) * 1000

        logger.info(f"Job completed: {len(results)} results in {total_ms:.0f}ms")

        return JobResult(
            status="ok",
            elapsed_ms=round(total_ms, 2),
            n_wells=n_wells,
            n_results=len(results),
            results=results,
            options_used=safe_opts,
        )

    except Exception as e:
        logger.error(f"Job failed: {e}", exc_info=True)
        return JobResult(status="error", error=str(e))


# Radix job payload endpoint (reads from /input/payload mounted by scheduler)
@app.on_event("startup")
async def process_payload_on_startup():
    """If launched with a payload file (Radix batch job mode), process it."""
    payload_path = Path("/input/payload")
    if payload_path.exists():
        try:
            raw = json.loads(payload_path.read_text())
            payload = JobPayload(**raw)
            result = run_correlation(payload)
            # Write result for Radix to pick up
            Path("/data/result.json").write_text(result.json())
            logger.info("Batch payload processed, result written to /data/result.json")
        except Exception as e:
            logger.error(f"Batch payload processing failed: {e}", exc_info=True)
