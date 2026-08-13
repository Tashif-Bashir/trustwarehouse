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

        max_attempts = 6
        for attempt in range(max_attempts):
            try:
                r = requests.get(url, params=full_params, timeout=90)
            except requests.RequestException as e:
                if attempt == max_attempts - 1:
                    raise MetaAPIError(f"Network error after {max_attempts} retries: {e}") from e
                time.sleep(2 ** attempt)
                continue

            # App-level throttling ("Application request limit reached",
            # subcode 1504022) comes back as 403 with is_transient=true in
            # the body — confirmed live during ad-daily backfill testing.
            # Treat it like 429/5xx: back off and retry.
            transient_403 = False
            if r.status_code == 403:
                try:
                    transient_403 = bool(r.json().get("error", {}).get("is_transient"))
                except ValueError:
                    transient_403 = False

            if r.status_code == 429 or 500 <= r.status_code < 600 or transient_403:
                if attempt == max_attempts - 1:
                    raise MetaAPIError(
                        f"HTTP {r.status_code} after {max_attempts} retries: {r.text[:500]}"
                    )
                time.sleep(min(2**attempt, 30))
                continue

            if not r.ok:
                raise MetaAPIError(f"HTTP {r.status_code}: {r.text[:500]}")

            return r.json()

        raise MetaAPIError(f"Failed after {max_attempts} attempts: {url}")

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

    def _edge(
        self,
        edge: str,
        fields: list[str],
        filtering: list[dict] | None = None,
        page_limit: int = 500,
    ) -> Iterator[dict]:
        """Yield rows from any /act_X/{edge} object-list endpoint (ads, campaigns, adsets).

        fields: Graph API field list, dot/brace syntax supported, e.g.
            "creative{id,name,object_story_spec,asset_feed_spec,thumbnail_url}".
        filtering: optional Graph API filtering spec, e.g.
            [{"field": "effective_status", "operator": "IN", "value": ["ACTIVE"]}]
        page_limit: rows per page. Confirmed empirically: 500 (the insights
            default) 500s ("reduce the amount of data") on /ads once
            object_story_spec/asset_feed_spec are requested — 100 is safe
            there. campaigns/adsets have no such heavy nested fields and are
            fine at 500 (confirmed live).
        """
        params: dict[str, Any] = {
            "fields": ",".join(fields),
            "limit": page_limit,
        }
        if filtering:
            params["filtering"] = json.dumps(filtering)

        url: str | None = f"{_BASE}/act_{self.account_id}/{edge}"
        first = True
        while url:
            data = self._get(url, params=params if first else None)
            for row in data.get("data", []):
                yield row
            url = data.get("paging", {}).get("next")
            first = False

    def ads(
        self,
        fields: list[str],
        filtering: list[dict] | None = None,
        page_limit: int = 100,
    ) -> Iterator[dict]:
        """Yield rows from /act_X/ads — ad objects with nested creative fields."""
        yield from self._edge("ads", fields=fields, filtering=filtering, page_limit=page_limit)

    def campaigns(
        self,
        fields: list[str],
        filtering: list[dict] | None = None,
    ) -> Iterator[dict]:
        """Yield rows from /act_X/campaigns — confirmed live: 234 rows, single page."""
        yield from self._edge("campaigns", fields=fields, filtering=filtering, page_limit=500)

    def adsets(
        self,
        fields: list[str],
        filtering: list[dict] | None = None,
        page_limit: int = 500,
    ) -> Iterator[dict]:
        """Yield rows from /act_X/adsets — confirmed live: paginates beyond 500 rows."""
        yield from self._edge("adsets", fields=fields, filtering=filtering, page_limit=page_limit)
