"""Ascend Cloud (Focus Group phone system) API client.

Auth: OAuth2 client_credentials against login.ascendcloud.com (service account).
Data: Analytics API — one detailed record per call.
Docs: https://developer.ascendcloud.com/api/spec/analytics/index.html
Rate limit: 250 requests/min per client — our polling uses ~1/min.
"""

import os
import time
from typing import Iterator

import requests

TOKEN_URL = "https://login.ascendcloud.com/user/connect/token"
API_BASE = "https://api.ascendcloud.com"
SCOPES = "api.service.analytics.main api.service.voice.call-recordings"
PAGE_SIZE = 500
# Refresh the bearer token a few minutes before its 1-hour expiry.
TOKEN_SAFETY_SECONDS = 300


class AscendClient:
    """Minimal Ascend API client for call-detail (CDR) retrieval."""

    def __init__(self) -> None:
        self.client_id = os.environ["ASCEND_CLIENT_ID"]
        self.client_secret = os.environ["ASCEND_CLIENT_SECRET"]
        self._token: str = ""
        self._token_expires_at: float = 0.0

    def _get_token(self) -> str:
        """Return a valid bearer token, minting a fresh one when near expiry."""
        if self._token and time.time() < self._token_expires_at:
            return self._token
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": SCOPES,
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + int(payload.get("expires_in", 3600)) - TOKEN_SAFETY_SECONDS
        return self._token

    def get_calls(self, date_from: str, date_to: str) -> Iterator[dict]:
        """Yield detailed call records (one per call) for a UTC time window.

        Args:
            date_from: inclusive UTC start, format ``yyyy-MM-ddTHH:mm:ss.SSSZ``.
            date_to: exclusive UTC end, same format.

        Paginates with offset/size in ascending start order until a short page.
        NOTE: the API's ``totalCalls`` echoes the page cap, so it is never used
        to decide when to stop.
        """
        offset = 0
        while True:
            resp = requests.post(
                f"{API_BASE}/analytics/calls/call/detail"
                f"?dateFrom={date_from}&dateTo={date_to}"
                f"&sortColumn=start&descending=false&offset={offset}&size={PAGE_SIZE}",
                headers={
                    "Authorization": f"Bearer {self._get_token()}",
                    "Content-Type": "application/json",
                },
                json={},
                timeout=60,
            )
            resp.raise_for_status()
            calls = resp.json().get("calls") or []
            yield from calls
            if len(calls) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

    def get_call_recordings(self, user_uuid: str, page_size: int = 100) -> Iterator[dict]:
        """Yield call-recording metadata for one user, newest first.

        Each record: id, fileName, duration (s), caller {phoneNumber, displayName},
        whenCreated (ISO), callId (joins to the CDR), direction, status.
        """
        offset = 0
        while True:
            resp = requests.get(
                f"{API_BASE}/voice/v2/accounts/_me/users/{user_uuid}/call-recordings"
                f"?offset={offset}&count={page_size}",
                headers={"Authorization": f"Bearer {self._get_token()}"},
                timeout=60,
            )
            resp.raise_for_status()
            records = resp.json().get("records") or []
            yield from records
            if len(records) < page_size:
                break
            offset += page_size

    def download_recording(self, user_uuid: str, recording_id: int) -> bytes:
        """Return the MP3 content of one call recording."""
        resp = requests.get(
            f"{API_BASE}/voice/v2/accounts/_me/users/{user_uuid}"
            f"/call-recordings/{recording_id}/_content",
            headers={"Authorization": f"Bearer {self._get_token()}"},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.content
