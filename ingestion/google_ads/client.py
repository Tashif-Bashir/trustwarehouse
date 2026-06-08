"""Google Ads API client.

Wraps the official `google-ads` SDK. Auth uses OAuth2 refresh-token flow with
the developer token, matching the same credentials Airbyte uses today.

Env vars (all required for any real call):
  GOOGLE_ADS_DEVELOPER_TOKEN      — approved Basic/Standard access token
  GOOGLE_ADS_CLIENT_ID            — OAuth2 client ID
  GOOGLE_ADS_CLIENT_SECRET        — OAuth2 client secret
  GOOGLE_ADS_REFRESH_TOKEN        — OAuth2 refresh token
  GOOGLE_ADS_LOGIN_CUSTOMER_ID    — MCC account ID (digits only, no dashes)
  GOOGLE_ADS_CUSTOMER_ID          — operating account ID (optional; defaults to login_customer_id)
"""

import os
from typing import Any, Iterator

from dotenv import load_dotenv

load_dotenv()


class GoogleAdsConfigError(RuntimeError):
    """Raised when required Google Ads env vars are missing."""


def _strip_dashes(customer_id: str) -> str:
    return customer_id.replace("-", "").strip()


def _build_config() -> dict[str, Any]:
    required = [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    ]
    missing = [k for k in required if not os.getenv(k, "").strip()]
    if missing:
        raise GoogleAdsConfigError(
            f"Missing Google Ads env vars: {', '.join(missing)}"
        )

    return {
        "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"].strip(),
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"].strip(),
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"].strip(),
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"].strip(),
        "login_customer_id": _strip_dashes(os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"]),
        "use_proto_plus": True,
    }


def get_client():
    """Return an authenticated GoogleAdsClient. Import is lazy so the module
    loads even when the SDK is not yet installed."""
    from google.ads.googleads.client import GoogleAdsClient  # type: ignore

    return GoogleAdsClient.load_from_dict(_build_config())


def operating_customer_id() -> str:
    """Customer ID to run queries against. Falls back to login_customer_id."""
    cid = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "").strip()
    if not cid:
        cid = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "")
    return _strip_dashes(cid)


def list_accessible_customers() -> list[str]:
    """Read-only auth ping. Returns resource names of customers the refresh
    token can access. Used by `__main__ --verify` and never writes anything."""
    client = get_client()
    service = client.get_service("CustomerService")
    response = service.list_accessible_customers()
    return list(response.resource_names)


def search_stream(query: str, customer_id: str | None = None) -> Iterator[Any]:
    """Run a GAQL query against the operating customer. Yields raw response
    rows. Not used by any current pipeline — wired up for future use."""
    client = get_client()
    cid = customer_id or operating_customer_id()
    if not cid:
        raise GoogleAdsConfigError(
            "No customer ID set. Add GOOGLE_ADS_CUSTOMER_ID or "
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID to .env."
        )

    service = client.get_service("GoogleAdsService")
    stream = service.search_stream(customer_id=cid, query=query)
    for batch in stream:
        for row in batch.results:
            yield row
