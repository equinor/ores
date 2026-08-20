"""
OSDU Notification Service integration.

Provides:
  GET  /notifications                      → status page (connectivity + subscriptions)
  GET  /api/notifications/test             → probe notification service availability
  GET  /api/notifications/subscriptions    → list push subscriptions
  POST /api/notifications/subscriptions    → create push subscription
  DELETE /api/notifications/subscriptions/{id} → delete subscription
  POST /api/notifications/check-changes    → poll record changes (lightweight)
  POST /api/notifications/webhook          → receive push callbacks
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import osdu
from .common import access_token as _access_token

log = logging.getLogger("rddms-admin.notifications")

router = APIRouter(tags=["notifications"])

templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates"),
)


# ──────────────────────────────────────────────────────────────────────────────
# API endpoints
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/api/notifications/test", response_class=JSONResponse,
            summary="Probe OSDU Notification Service connectivity")
async def notification_test_endpoint(request: Request):
    """Check whether the OSDU Notification Service is reachable."""
    at = _access_token(request)
    result = await osdu.notification_test(at)
    return JSONResponse(result)


@router.get("/api/notifications/subscriptions", response_class=JSONResponse,
            summary="List push subscriptions")
async def list_subscriptions(request: Request):
    """List all OSDU push notification subscriptions."""
    at = _access_token(request)
    try:
        subs = await osdu.notification_list_subscriptions(at)
        return JSONResponse({"ok": True, "subscriptions": subs})
    except Exception as e:
        log.warning("[NOTIFY] list subscriptions failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@router.post("/api/notifications/subscriptions", response_class=JSONResponse,
             summary="Create push subscription")
async def create_subscription(request: Request):
    """Create an OSDU push notification subscription.

    Expects JSON body::

        {
          "name": "bd-changes",
          "topic": "recordstopic",
          "push_endpoint": "https://my-app.example.com/api/notifications/webhook",
          "description": "Watch BD record changes"
        }
    """
    at = _access_token(request)
    body = await request.json()

    name = body.get("name", "").strip()
    topic = body.get("topic", "").strip()
    push_endpoint = body.get("push_endpoint", "").strip()

    if not name:
        raise HTTPException(400, "name is required")
    if not topic:
        raise HTTPException(400, "topic is required")
    if not push_endpoint:
        raise HTTPException(400, "push_endpoint is required")

    # Basic URL validation
    if not push_endpoint.startswith("https://"):
        raise HTTPException(400, "push_endpoint must be an HTTPS URL")

    try:
        result = await osdu.notification_create_subscription(
            at,
            name=name,
            topic=topic,
            push_endpoint=push_endpoint,
            description=body.get("description", ""),
        )
        return JSONResponse({"ok": True, "subscription": result})
    except Exception as e:
        log.warning("[NOTIFY] create subscription failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@router.delete("/api/notifications/subscriptions/{sub_id}",
               response_class=JSONResponse,
               summary="Delete push subscription")
async def delete_subscription(request: Request, sub_id: str):
    """Delete an OSDU push notification subscription."""
    at = _access_token(request)
    try:
        ok = await osdu.notification_delete_subscription(at, sub_id)
        return JSONResponse({"ok": ok, "deleted": sub_id})
    except Exception as e:
        log.warning("[NOTIFY] delete subscription failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@router.post("/api/notifications/check-changes", response_class=JSONResponse,
             summary="Poll record changes (lightweight)")
async def check_changes(request: Request):
    """Check for changes to specific OSDU records.

    Lightweight polling approach: queries record metadata (modifyTime)
    for a list of record IDs and returns their timestamps.

    Expects JSON body::

        {
          "record_ids": ["dev:master-data--BusinessDecision:xxx:1", ...]
        }
    """
    at = _access_token(request)
    body = await request.json()

    record_ids = body.get("record_ids", [])
    if not record_ids:
        return JSONResponse({"ok": True, "changes": []})

    try:
        results = await osdu.notification_record_changed(at, record_ids)
        return JSONResponse({"ok": True, "records": results})
    except Exception as e:
        log.warning("[NOTIFY] check-changes failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@router.post("/api/notifications/webhook", response_class=JSONResponse,
             summary="Receive OSDU push notification callbacks")
async def webhook_receiver(request: Request):
    """Endpoint that receives push notifications from OSDU.

    When a push subscription is configured with this URL as the endpoint,
    OSDU will POST change events here. The events are logged and can be
    forwarded to connected clients via SSE (future C1).
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    # Log the notification event
    log.info("[NOTIFY-WEBHOOK] Received: %s", str(body)[:500])

    # Extract useful fields
    event_type = body.get("type") or body.get("eventType") or "unknown"
    record_ids = body.get("data", {}).get("recordIds") or body.get("recordIds") or []

    # TODO: Forward to SSE clients when C1 (Real-Time Collaboration) is implemented
    # For now, just acknowledge receipt
    return JSONResponse({
        "ok": True,
        "event_type": event_type,
        "record_count": len(record_ids) if isinstance(record_ids, list) else 0,
    })


# ──────────────────────────────────────────────────────────────────────────────
# GUI page
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/notifications", response_class=HTMLResponse,
            summary="Notification Service status page")
async def notifications_page(request: Request):
    """Render the notifications management page."""
    return templates.TemplateResponse(
        request, "notifications.html", {},
    )
