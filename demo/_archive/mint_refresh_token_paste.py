#!/usr/bin/env python3
"""
mint_refresh_token_paste.py - PKCE login with manual callback paste.

Same as mint_refresh_token.py but instead of running a localhost HTTP
server (which doesn't work in WSL), it asks you to paste the full
callback URL from the browser address bar after sign-in.

Usage:
  python demo/mint_refresh_token_paste.py

After Azure AD redirects to http://localhost:8400/callback?code=...
your browser will show "can't reach this page".  That's fine -
copy the FULL URL from the address bar and paste it here.
"""
from __future__ import annotations

import hashlib
import secrets
import sys
import urllib.parse

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")

import base64

# ── Defaults (ores-dev app) ──────────────────────────────────────────────
CLIENT_ID   = "21b442a9-6c1c-4551-b234-afdf010dd3be"
TENANT      = "3aa4a235-b6e2-48d5-9195-7fcf05b459b0"
SCOPES      = "https://energy.azure.com/.default openid offline_access"
REDIRECT_URI = "http://localhost:8400/callback"


def _pkce_pair():
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def main():
    auth_base = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0"
    token_url = f"{auth_base}/token"

    code_verifier, code_challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    url = f"{auth_base}/authorize?{urllib.parse.urlencode(params)}"

    print(f"\n  1. Open this URL in your browser:\n")
    print(f"  {url}\n")
    print(f"  2. Sign in with your Equinor account.")
    print(f"  3. The browser will redirect to localhost:8400 - it will FAIL to load.")
    print(f"     That's OK! Copy the FULL URL from the address bar.\n")

    callback_url = input("  Paste the full callback URL here:\n  ").strip()

    if not callback_url:
        print("ERROR: No URL provided.")
        sys.exit(1)

    # Parse the code and state from the callback URL
    parsed = urllib.parse.urlparse(callback_url)
    qs = urllib.parse.parse_qs(parsed.query)

    error = qs.get("error", [None])[0]
    if error:
        desc = qs.get("error_description", [""])[0]
        print(f"ERROR: {error}: {desc}")
        sys.exit(1)

    code = qs.get("code", [None])[0]
    if not code:
        print("ERROR: No 'code' parameter found in the URL.")
        sys.exit(1)

    cb_state = qs.get("state", [None])[0]
    if cb_state != state:
        print(f"ERROR: State mismatch. Expected '{state}', got '{cb_state}'.")
        sys.exit(1)

    # ── Exchange code for tokens ─────────────────────────────────────────
    print("\n  Exchanging code for tokens...")
    r = httpx.post(token_url, data={
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
        "scope": SCOPES,
    }, timeout=30)

    if not r.is_success:
        print(f"ERROR: Token exchange failed ({r.status_code}):\n{r.text[:500]}")
        sys.exit(1)

    body = r.json()
    access_token = body.get("access_token", "")
    refresh_token = body.get("refresh_token", "")
    expires_in = body.get("expires_in", "?")

    print(f"\n{'='*60}")
    print(f"  Access token:  {access_token[:40]}... (expires_in={expires_in}s)")
    if refresh_token:
        print(f"\n  REFRESH TOKEN (paste into k8s/secret.yaml):\n")
        print(f"  {refresh_token}")
        print(f"\n{'='*60}")
        print(f"\n  Update k8s/secret.yaml:")
        print(f'  INSTANCE_EQNDEV_REFRESH_TOKEN: "{refresh_token[:60]}..."')
    else:
        print("\n  WARNING: No refresh_token returned!")
        print("  Make sure 'offline_access' is in scopes")
        print("  and 'Allow public client flows' is enabled in Azure Portal.")
    print()


if __name__ == "__main__":
    main()
