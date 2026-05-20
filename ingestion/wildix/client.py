"""Wildix API client — WMS (colleagues) and WDA (call history)."""

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

_WDA_BASE = "https://wda.wildix.com"
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

_MIN_INTERVAL = 0.15  # ~6 req/sec max


class WildixError(Exception):
    """Raised when a Wildix API call fails."""


class WildixClient:
    """Client for the Wildix WMS and WDA APIs."""

    def __init__(
        self,
        base_url: str | None = None,
        simple_token: str | None = None,
        wsk_token: str | None = None,
    ):
        self.base_url = (base_url or os.getenv("WILDIX_API_BASE_URL", "")).rstrip("/")
        self.simple_token = (simple_token or os.getenv("WILDIX_SIMPLE_TOKEN", "")).strip()
        self.wsk_token = (wsk_token or os.getenv("WILDIX_WSK_TOKEN", "")).strip()

        if not self.base_url:
            raise RuntimeError("WILDIX_API_BASE_URL is not set.")
        if not self.simple_token:
            raise RuntimeError("WILDIX_SIMPLE_TOKEN is not set.")
        if not self.wsk_token:
            raise RuntimeError("WILDIX_WSK_TOKEN is not set.")

        self._last_request_at: float = 0.0

    # --- Rate limiting ---

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        self._last_request_at = time.monotonic()

    # --- WMS API ---

    def _wms_get(self, path: str) -> dict:
        self._rate_limit()
        url = f"{self.base_url}/api/v1/{path}"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.simple_token}", "Accept": "application/json"},
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=15, context=_CTX) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 429 or (attempt < 2 and e.code >= 500):
                    time.sleep(2**attempt)
                    continue
                raise WildixError(f"WMS request failed ({e.code}): {url}") from e
            except urllib.error.URLError as e:
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise WildixError(f"WMS request failed: {url}") from e
        raise WildixError(f"WMS request failed after 3 attempts: {url}")

    def _wms_paginate(self, endpoint: str) -> list[dict]:
        """Paginate through a WMS endpoint returning {result: {records: []}}."""
        all_records: list[dict] = []
        offset = 0
        limit = 500
        while True:
            sep = "&" if "?" in endpoint else "?"
            data = self._wms_get(f"{endpoint}{sep}limit={limit}&offset={offset}")
            result = data.get("result", {})
            records = result.get("records", []) if isinstance(result, dict) else []
            all_records.extend(records)
            if len(records) < limit:
                break
            offset += limit
        return all_records

    def get_all_colleagues(self) -> list[dict]:
        """Fetch all users/extensions from WMS, paginated."""
        return self._wms_paginate("Colleagues/")

    def get_departments(self) -> list[dict]:
        """Fetch all departments from WMS."""
        data = self._wms_get("Departments/")
        return data.get("result", {}).get("records", [])

    def get_groups(self) -> list[dict]:
        """Fetch all call groups from WMS, paginated."""
        return self._wms_paginate("Groups/")


    def get_contacts(self) -> list[dict]:
        """Fetch all phonebook contacts from WMS, paginated."""
        return self._wms_paginate("Contacts/")

    def get_all_call_history(self) -> list[dict]:
        """Fetch system-wide PBX call history from WMS, paginated."""
        return self._wms_paginate("CallHistory/")

    # --- WDA API ---

    def _wda_post(self, body: dict, user_id: str | int) -> dict:
        self._rate_limit()
        url = f"{_WDA_BASE}/v2/history/user/calls?user={user_id}"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.wsk_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 429 or (attempt < 2 and e.code >= 500):
                    time.sleep(2**attempt)
                    continue
                raise WildixError(f"WDA request failed ({e.code}) for user {user_id}") from e
            except urllib.error.URLError as e:
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise WildixError(f"WDA request failed for user {user_id}") from e
        raise WildixError(f"WDA request failed after 3 attempts for user {user_id}")

    def get_calls_for_user(
        self,
        wms_id: str | int,
        date_from: str = "2020-01-01T00:00:00Z",
        date_to: str | None = None,
    ) -> list[dict]:
        """Fetch all calls for a user, paginated. date_from/to in ISO 8601 UTC."""
        if date_to is None:
            date_to = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        all_calls: list[dict] = []
        offset = 0
        limit = 100
        while True:
            data = self._wda_post(
                {"limit": limit, "offset": offset, "filter": {"from": date_from, "to": date_to}},
                wms_id,
            )
            page = data.get("calls", [])
            all_calls.extend(page)
            if len(page) < limit:
                break
            offset += limit
        return all_calls

    def get_all_calls(self, date_from: str = "2020-01-01T00:00:00Z") -> list[dict]:
        """Fetch all calls for all colleagues, tagging each call with colleague metadata."""
        colleagues = self.get_all_colleagues()
        all_calls: list[dict] = []
        date_to = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for colleague in colleagues:
            wms_id = str(colleague.get("id", ""))
            if not wms_id:
                continue
            calls = self.get_calls_for_user(wms_id, date_from=date_from, date_to=date_to)
            for call in calls:
                call["_wms_id"] = wms_id
                call["_extension"] = str(colleague.get("extension", ""))
                call["_colleague_name"] = (
                    colleague.get("displayName")
                    or f"{colleague.get('name', '')} {colleague.get('surname', '')}".strip()
                    or colleague.get("username", "")
                )
                call["_department"] = colleague.get("department", "")
            all_calls.extend(calls)

        return all_calls
