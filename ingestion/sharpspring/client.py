"""SharpSpring JSON-RPC API client with rate limiting and exponential backoff."""

import os
import time
import uuid
from datetime import datetime
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

_BASE_URL = "https://api.sharpspring.com/pubapi/v1.2/"
_MAX_RPS = 8  # stay under the ~10 req/sec limit
_MIN_INTERVAL = 1.0 / _MAX_RPS


class SharpSpringError(Exception):
    """Raised when the SharpSpring API returns an error payload."""


class SharpSpringClient:
    """Client for the SharpSpring JSON-RPC API."""

    def __init__(self, account_id: str | None = None, secret_key: str | None = None):
        self.account_id = account_id or os.getenv("SHARPSPRING_ACCOUNT_ID")
        self.secret_key = secret_key or os.getenv("SHARPSPRING_SECRET_KEY")

        if not self.account_id:
            raise RuntimeError("SHARPSPRING_ACCOUNT_ID is not set.")
        if not self.secret_key:
            raise RuntimeError("SHARPSPRING_SECRET_KEY is not set.")

        self._last_request_at: float = 0.0

    def _call(self, method: str, params: dict[str, Any]) -> Any:
        """POST a JSON-RPC request. Retries up to 3 times with exponential backoff."""
        payload = {
            "method": method,
            "params": params,
            "id": str(uuid.uuid4()),
        }
        url_params = {"accountID": self.account_id, "secretKey": self.secret_key}

        for attempt in range(3):
            self._rate_limit()
            try:
                response = requests.post(
                    _BASE_URL,
                    params=url_params,
                    json=payload,
                    timeout=30,
                )
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2**attempt)
                continue

            if response.status_code == 429:
                wait = 2 ** (attempt + 1)
                time.sleep(wait)
                continue

            response.raise_for_status()
            body = response.json()

            if body.get("error"):
                raise SharpSpringError(f"API error on {method}: {body['error']}")

            return body.get("result")

        raise SharpSpringError(f"Failed after 3 attempts: {method}")

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        self._last_request_at = time.monotonic()

    def get_leads(
        self,
        updated_since: datetime | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        """Fetch leads, optionally filtered by updateTimestamp."""
        where: dict[str, Any] = {}
        if updated_since:
            where["updateTimestamp"] = updated_since.strftime("%Y-%m-%d %H:%M:%S")

        result = self._call("getLeads", {"where": where, "limit": limit, "offset": offset})
        return result.get("lead", []) if result else []

    def get_all_leads(self, updated_since: datetime | None = None) -> list[dict]:
        """Paginate through all leads (handles >500 records)."""
        all_leads: list[dict] = []
        offset = 0
        while True:
            page = self.get_leads(updated_since=updated_since, limit=500, offset=offset)
            all_leads.extend(page)
            if len(page) < 500:
                break
            offset += 500
        return all_leads

    def get_campaigns(self) -> list[dict]:
        """Fetch all campaigns."""
        result = self._call("getCampaigns", {"where": {}, "limit": 500, "offset": 0})
        return result.get("campaign", []) if result else []

    def get_owners(self) -> list[dict]:
        """Fetch all user accounts (owners/assignees for leads)."""
        result = self._call("getUsers", {"where": {}, "limit": 500, "offset": 0})
        return result.get("user", []) if result else []

    def get_opportunities(self) -> list[dict]:
        """Fetch all opportunities."""
        result = self._call("getOpportunities", {"where": {}, "limit": 500, "offset": 0})
        return result.get("opportunity", []) if result else []
