
from __future__ import annotations
import os
from typing import Optional, Dict, Any
from fastapi import APIRouter
from authlib.integrations.httpx_client import AsyncOAuth2Client

# ─────────────────────────────────────────────────────────────
# Azure AD / Microsoft identity platform (no PKCE, no cookies)
# ─────────────────────────────────────────────────────────────
TENANT = os.getenv("AZURE_TENANT_ID", "")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
SCOPES = os.getenv("AZURE_SCOPE", "openid offline_access").split()

AUTH_BASE = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0"
TOKEN_URL = f"{AUTH_BASE}/token"

router = APIRouter(tags=["auth"])  # keep router so main.py include works

async def tokens_from_env() -> Optional[Dict[str, Any]]:
    """
    Mint tokens from a refresh_token present in the environment (.env or process env).
    This avoids browser login, PKCE, cookies, and state handling.
    """
    rt = os.getenv("REFRESH_TOKEN") or os.getenv("refresh_token")
    if not rt or not CLIENT_ID or not TENANT:
        return None

    async with AsyncOAuth2Client(client_id=CLIENT_ID, scope=SCOPES) as cli:
        token = await cli.fetch_token(
            TOKEN_URL,
            grant_type="refresh_token",
            refresh_token=rt,
            scope=" ".join(SCOPES),
        )

    return {
        "access_token": token.get("access_token"),
        "refresh_token": token.get("refresh_token") or rt,
        "expires_in": token.get("expires_in"),
        "id_token": token.get("id_token", ""),
    }

# Optional: simple diagnostics endpoint (non-sensitive)
@router.get("/auth")
async def auth_info():
    return {
        "azure_tenant": TENANT[:8] + "..." if TENANT else "",
        "client_id": CLIENT_ID[:8] + "..." if CLIENT_ID else "",
        "scopes": SCOPES,
        "mode": "refresh_token_only",
    }
