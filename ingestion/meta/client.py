"""Meta Marketing API client (Graph API v21.0).

Thin wrapper around the /act_X/insights endpoint. Uses requests with cursor
pagination and exponential backoff on transient errors.

Env vars (both required):
  META_ACCESS_TOKEN     — system-user token with ads_read scope
  META_AD_ACCOUNT_ID    — operating ad account, digits only (no `act_` prefix)
"""

import json
import os
import time
from typing import Any, Iterator

import requests
from dotenv import load_dotenv

load_dotenv()

_BASE = "https://graph.facebook.com/v21.0"

_DEFAULT_INSIGHT_FIELDS = [
    "account_id",
    "account_currency",
    "campaign_id",
    "campaign_name",
    "objective",
    "spend",
    "impressions",
    "clicks",
    "unique_clicks",
    "reach",
    "frequency",
    "cpc",
    "cpm",
    "ctr",
    "date_start",
    "date_stop",
]


class MetaConfigError(RuntimeError):
    """Raised when required Meta env vars are missing."""


class MetaAPIError(RuntimeError):
    """Raised when the Graph API returns a non-2xx response."""


class MetaClient:
    """Minimal Marketing API client."""

    def __init__(self, token: str | None = None, ad_account_id: str | None = None):
        self.token = (token or os.getenv("META_ACCESS_TOKEN", "")).strip()
        self.account_id = (ad_account_id or os.getenv("META_AD_ACCOUNT_ID", "")).strip()

        if not self.token:
            raise MetaConfigError("META_ACCESS_TOKEN is not set.")
        if not self.account_id:
            raise MetaConfigError("META_AD_ACCOUNT_ID is not set.")

    def _get(self, url: str, params: dict | None = None) -> dict[str, Any]:
        full_params: dict[str, Any] | None = None
        if params is not None:
            full_params = dict(params)
            full_params["access_token"] = self.token

        for attempt in range(4):
            try:
                r = requests.get(url, params=full_params, timeout=90)
            except requests.RequestException as e:
                if attempt == 3:
                    raise MetaAPIError(f"Network error after 3 retries: {e}") from e
                time.sleep(2 ** attempt)
                continue

            if r.status_code == 429 or 500 <= r.status_code < 600:
                time.sleep(2 ** attempt)
                continue

            if not r.ok:
                raise MetaAPIError(f"HTTP {r.status_code}: {r.text[:500]}")

            return r.json()

        raise MetaAPIError(f"Failed after 4 attempts: {url}")

    def verify(self) -> dict:
        """Read-only auth ping. Returns token debug info + account metadata."""
        debug = self._get(f"{_BASE}/debug_token", params={"input_token": self.token})
        account = self._get(
            f"{_BASE}/act_{self.account_id}",
            params={"fields": "id,name,account_status,currency,timezone_name,amount_spent"},
        )
        return {"token": debug.get("data", {}), "account": account}

    def insights(
        self,
        level: str = "campaign",
        breakdowns: list[str] | None = None,
        fields: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
        time_increment: int = 1,
    ) -> Iterator[dict]:
        """Yield rows from /act_X/insights.

        level: account | campaign | adset | ad
        since/until: ISO dates (YYYY-MM-DD). Defaults to today only.
        time_increment: 1 = daily; 7 = weekly; passing "all_days" = roll-up
        """
        from datetime import date

        if since is None:
            since = date.today().isoformat()
        if until is None:
            until = date.today().isoformat()

        params: dict[str, Any] = {
            "level": level,
            "fields": ",".join(fields or _DEFAULT_INSIGHT_FIELDS),
            "time_range": json.dumps({"since": since, "until": until}),
            "time_increment": time_increment,
            "limit": 500,
        }
        if breakdowns:
            params["breakdowns"] = ",".join(breakdowns)

        url: str | None = f"{_BASE}/act_{self.account_id}/insights"
        first = True
        while url:
            data = self._get(url, params=params if first else None)
            for row in data.get("data", []):
                yield row
            url = data.get("paging", {}).get("next")
            first = False
