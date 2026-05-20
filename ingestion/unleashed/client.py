"""Unleashed REST API client with HMAC-SHA256 auth and pagination."""

import base64
import hashlib
import hmac
import os
import time
from typing import Any, Generator

import requests
from dotenv import load_dotenv

load_dotenv()

_BASE_URL = "https://api.unleashedsoftware.com"
_PAGE_SIZE = 200


class UnleashedError(Exception):
    """Raised when the Unleashed API returns a non-2xx response."""


class UnleashedClient:
    """Client for the Unleashed REST API."""

    def __init__(self, api_id: str | None = None, api_key: str | None = None):
        self.api_id = (api_id or os.getenv("UNLEASHED_API_ID", "")).strip()
        self.api_key = (api_key or os.getenv("UNLEASHED_API_KEY", "")).strip()

        if not self.api_id:
            raise RuntimeError("UNLEASHED_API_ID is not set.")
        if not self.api_key:
            raise RuntimeError("UNLEASHED_API_KEY is not set.")

    def _sign(self, query: str) -> str:
        """Return base64-encoded HMAC-SHA256 signature of the query string."""
        return base64.b64encode(
            hmac.new(self.api_key.encode(), query.encode(), hashlib.sha256).digest()
        ).decode()

    def _get(self, endpoint: str, query: str) -> dict[str, Any]:
        """GET one page from the Unleashed API. Retries up to 3 times."""
        headers = {
            "api-auth-id": self.api_id,
            "api-auth-signature": self._sign(query),
            "Accept": "application/json",
        }
        url = f"{_BASE_URL}/{endpoint}?{query}"

        for attempt in range(3):
            try:
                r = requests.get(url, headers=headers, timeout=30)
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
                continue

            if r.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue

            if not r.ok:
                raise UnleashedError(f"GET {endpoint} failed {r.status_code}: {r.text[:300]}")

            return r.json()

        raise UnleashedError(f"Failed after 3 attempts: {endpoint}")

    def paginate(self, endpoint: str, extra_params: str = "") -> Generator[dict, None, None]:
        """Yield every item from a paginated Unleashed endpoint."""
        page = 1
        while True:
            query = f"pageSize={_PAGE_SIZE}&pageNumber={page}"
            if extra_params:
                query += f"&{extra_params}"

            data = self._get(endpoint, query)
            items = data.get("Items", [])
            yield from items

            pagination = data.get("Pagination", {})
            if page >= pagination.get("NumberOfPages", 1):
                break
            page += 1

    def get_products(self) -> Generator[dict, None, None]:
        yield from self.paginate("Products")

    def get_stock_on_hand(self) -> Generator[dict, None, None]:
        yield from self.paginate("StockOnHand")

    def get_sales_orders(self) -> Generator[dict, None, None]:
        yield from self.paginate("SalesOrders")

    def get_purchase_orders(self) -> Generator[dict, None, None]:
        yield from self.paginate("PurchaseOrders")

    def get_customers(self) -> Generator[dict, None, None]:
        yield from self.paginate("Customers")
