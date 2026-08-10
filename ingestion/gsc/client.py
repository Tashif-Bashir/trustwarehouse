"""Google Search Console (searchanalytics) API client.

Auth: service-account credentials from ``trust_pipeline_key.json`` (repo root),
scope ``https://www.googleapis.com/auth/webmasters.readonly``. The SA must be
granted access on the property directly in Search Console — there is no
delegation step.

Docs: https://developers.google.com/webmaster-tools/v1/searchanalytics/query
Rate limits are generous but bursty backfills can 429 — callers should back off.
"""

import time
from typing import Any, Iterator

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

_KEY_FILE = "trust_pipeline_key.json"
_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
_ROW_LIMIT = 25_000


class GSCClient:
    """Minimal Search Console client: list sites, paginate searchanalytics queries."""

    def __init__(self, key_file: str = _KEY_FILE) -> None:
        creds = service_account.Credentials.from_service_account_file(
            key_file, scopes=_SCOPES
        )
        self.service = build("searchconsole", "v1", credentials=creds)

    def list_sites(self) -> list[dict[str, Any]]:
        """Return the raw siteEntry list — each has siteUrl and permissionLevel."""
        resp = self.service.sites().list().execute()
        return resp.get("siteEntry", [])

    def query(
        self,
        site_url: str,
        start_date: str,
        end_date: str,
        dimensions: list[str],
        row_limit: int = _ROW_LIMIT,
        max_retries: int = 2,
    ) -> Iterator[dict[str, Any]]:
        """Yield rows for one searchanalytics query, paginated via startRow.

        Each row's `keys` list (positional, matches `dimensions` order) is
        exploded into named columns; clicks/impressions/ctr/position pass
        through as-is. Stops when a page returns fewer than `row_limit` rows.

        On HTTP 429, backs off (5s, then 15s) and retries up to `max_retries`
        times before raising.
        """
        start_row = 0
        while True:
            body = {
                "startDate": start_date,
                "endDate": end_date,
                "dimensions": dimensions,
                "rowLimit": row_limit,
                "startRow": start_row,
            }
            attempt = 0
            while True:
                try:
                    resp = (
                        self.service.searchanalytics()
                        .query(siteUrl=site_url, body=body)
                        .execute()
                    )
                    break
                except HttpError as e:
                    if e.resp.status == 429 and attempt < max_retries:
                        time.sleep(5 if attempt == 0 else 15)
                        attempt += 1
                        continue
                    raise

            rows = resp.get("rows", [])
            for row in rows:
                out: dict[str, Any] = dict(zip(dimensions, row.get("keys", [])))
                out["clicks"] = row.get("clicks")
                out["impressions"] = row.get("impressions")
                out["ctr"] = row.get("ctr")
                out["position"] = row.get("position")
                yield out

            if len(rows) < row_limit:
                break
            start_row += row_limit
