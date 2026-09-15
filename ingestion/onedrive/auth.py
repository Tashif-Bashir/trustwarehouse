"""Microsoft Graph sign-in for the OneDrive reader (delegated, acts as the owner).

One-time: run this module directly, enter the device code in a browser, done.
Afterwards `get_token()` refreshes silently from the on-disk token cache.

Why delegated and not application permissions: an application-permission app
would read every OneDrive in the company. Delegated Files.Read.All sees exactly
what the signed-in owner sees (owner ruling, 15 Sep 2026).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import msal
from dotenv import load_dotenv

load_dotenv()

# Delegated: everything the signed-in owner can open, and nothing more. The
# four ops workbooks live in colleagues' OneDrives and the Finance library,
# which plain Files.Read cannot reach (403, 15 Sep 2026).
SCOPES = ["Files.Read.All", "Sites.Read.All"]  # offline_access is added by MSAL automatically
AUTHORITY = "https://login.microsoftonline.com/{tenant}"
CACHE_PATH = Path(
    os.environ.get("MS_GRAPH_TOKEN_CACHE") or Path.home() / ".cache" / "ms_graph_token.json"
)


def _cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if CACHE_PATH.exists():
        cache.deserialize(CACHE_PATH.read_text(encoding="utf-8"))
    return cache


def _save(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")


def _app(cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
    tenant = os.environ["MS_GRAPH_TENANT_ID"]
    client = os.environ["MS_GRAPH_CLIENT_ID"]
    return msal.PublicClientApplication(
        client, authority=AUTHORITY.format(tenant=tenant), token_cache=cache
    )


def get_token() -> str:
    """Return a valid access token, refreshing silently from the cache.

    Raises:
        RuntimeError: when no cached sign-in exists (run `python -m ingestion.onedrive.auth`).
    """
    cache = _cache()
    app = _app(cache)
    accounts = app.get_accounts()
    result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
    _save(cache)
    if not result or "access_token" not in result:
        raise RuntimeError(
            "No Microsoft sign-in on this machine — run: python -m ingestion.onedrive.auth"
        )
    return result["access_token"]


def sign_in() -> None:
    """Interactive one-time device-code sign-in; stores the refresh token in the cache."""
    cache = _cache()
    app = _app(cache)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise SystemExit(f"Could not start device flow: {json.dumps(flow, indent=2)}")
    print(flow["message"], flush=True)
    result = app.acquire_token_by_device_flow(flow)
    _save(cache)
    if "access_token" in result:
        who = (result.get("id_token_claims") or {}).get("preferred_username", "?")
        print(f"Signed in as {who}. Token cache: {CACHE_PATH}", flush=True)
    else:
        raise SystemExit(f"Sign-in failed: {result.get('error')}: {result.get('error_description')}")


if __name__ == "__main__":
    sign_in()
    sys.exit(0)
