#!/usr/bin/env python3
"""
mint_refresh_token.py - Interactive PKCE login to get a refresh_token.

Opens a browser for user sign-in, captures the authorization code via a
localhost callback, and exchanges it for tokens.  Prints the refresh_token
so you can paste it into k8s/secret.yaml.

Prerequisites:
  - The app registration must have http://localhost:8400/callback as a
    redirect URI (Web or SPA platform).
  - "Allow public client flows" should be enabled in Azure Portal
    (Authentication blade) if the app has no client_secret.

Usage:
  python demo/mint_refresh_token.py

  # Or override defaults:
  python demo/mint_refresh_token.py \\
      --client-id 21b442a9-6c1c-4551-b234-afdf010dd3be \\
      --tenant 3aa4a235-b6e2-48d5-9195-7fcf05b459b0 \\
      --scope "https://energy.azure.com/.default openid offline_access"

After sign-in, paste the printed REFRESH_TOKEN into:
  k8s/secret.yaml → INSTANCE_EQNDEV_REFRESH_TOKEN
"""
from __future__ import annotations

import argparse
import hashlib
import secrets
import sys
import urllib.parse

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")

# ── Defaults (ores-dev app) ──────────────────────────────────────────────
DEFAULT_CLIENT_ID = "21b442a9-6c1c-4551-b234-afdf010dd3be"
DEFAULT_TENANT    = "3aa4a235-b6e2-48d5-9195-7fcf05b459b0"
DEFAULT_SCOPE     = "https://energy.azure.com/.default openid offline_access"
REDIRECT_PORT     = 8400
REDIRECT_URI      = f"http://localhost:{REDIRECT_PORT}/callback"


def _pkce_pair():
    """Generate PKCE code_verifier + code_challenge (S256)."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    import base64
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


_VERIFIER_FILE = "/tmp/_ores_pkce_verifier.json"


def main():
    ap = argparse.ArgumentParser(description="Mint a refresh_token via interactive PKCE login")
    ap.add_argument("--client-id", default=DEFAULT_CLIENT_ID, help="App (client) ID")
    ap.add_argument("--tenant", default=DEFAULT_TENANT, help="Azure AD tenant ID")
    ap.add_argument("--scope", default=DEFAULT_SCOPE, help="Space-separated scopes")
    ap.add_argument("--callback", default=None,
                    help="Full callback URL from browser address bar (step 2)")
    args = ap.parse_args()

    client_id = args.client_id
    tenant = args.tenant
    scopes = args.scope

    auth_base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
    token_url = f"{auth_base}/token"

    # ── STEP 2: Exchange a callback URL for tokens ───────────────────────
    if args.callback:
        import json as _json
        try:
            with open(_VERIFIER_FILE) as f:
                saved = _json.load(f)
        except FileNotFoundError:
            sys.exit(f"ERROR: No saved PKCE state found at {_VERIFIER_FILE}.\n"
                     f"       Run without --callback first to generate the auth URL.")
        code_verifier = saved["code_verifier"]
        saved_state = saved["state"]

        qs = urllib.parse.urlparse(args.callback).query
        p = urllib.parse.parse_qs(qs)
        code = p.get("code", [None])[0]
        cb_state = p.get("state", [None])[0]
        err = p.get("error", [None])[0]

        if err:
            sys.exit(f"ERROR: {err}: {p.get('error_description', [''])[0]}")
        if not code:
            sys.exit("ERROR: No ?code= found in the callback URL.")
        if cb_state != saved_state:
            sys.exit(f"ERROR: State mismatch - expected {saved_state[:8]}..., "
                     f"got {(cb_state or '(none)')[:8]}...")

        print("  Exchanging code for tokens...")
        _exchange_code(token_url, client_id, code, code_verifier, scopes)
        import os; os.unlink(_VERIFIER_FILE)
        return

    # ── STEP 1: Generate PKCE pair, save verifier, print auth URL ────────
    code_verifier, code_challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    # Persist verifier for step 2
    import json as _json
    with open(_VERIFIER_FILE, "w") as f:
        _json.dump({"code_verifier": code_verifier, "state": state,
                     "client_id": client_id}, f)

    authorize_url = f"{auth_base}/authorize"
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    url = f"{authorize_url}?{urllib.parse.urlencode(params)}"

    print(f"\n  App:    {client_id}")
    print(f"  Scopes: {scopes}\n")
    print(f"  1. Open this URL in your browser:\n")
    print(f"  {url}\n")
    print(f"  2. Sign in with your Equinor account.")
    print(f"  3. The browser will redirect to localhost:8400 - it will FAIL to load.")
    print(f"     That's OK! Copy the FULL URL from the address bar.\n")
    print(f"  4. Run step 2:")
    print(f'     python demo/mint_refresh_token.py --callback "URL_FROM_BROWSER"\n')


# ── Exchange code for tokens ─────────────────────────────────────────
def _exchange_code(token_url, client_id, code, code_verifier, scopes):
    """Exchange authorization code for tokens and print result."""
    r = httpx.post(token_url, data={
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
        "scope": scopes,
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
        print(f'  INSTANCE_EQNDEV_CLIENT_ID: "{client_id}"')
        print(f'  INSTANCE_EQNDEV_SCOPE: "{scopes}"')
    else:
        print("\n  WARNING: No refresh_token returned!")
        print("  Make sure 'offline_access' is in your scopes")
        print("  and the app has 'Allow public client flows' enabled.")
    print()


if __name__ == "__main__":
    main()