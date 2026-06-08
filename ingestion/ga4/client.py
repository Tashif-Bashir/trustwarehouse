"""GA4 Data API client.

Thin wrapper around `google-analytics-data` v1beta. Authenticates via
Application Default Credentials (same service account dbt uses — Trust GA4
property 336938127 grants this account viewer access).

Env vars:
  GA4_PROPERTY_ID   — defaults to 336938127 (Trust Electric Heating's property)
"""

import os
import re
from typing import Iterator

from dotenv import load_dotenv
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    OrderBy,
    RunReportRequest,
)

load_dotenv()


def _to_snake(name: str) -> str:
    """Convert GA4's camelCase field names to snake_case so the dict keys
    yielded by the client match the snake_case columns dlt creates in BigQuery.
    Needed so resource primary_key lists match the actual row keys."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()

_DEFAULT_PROPERTY_ID = "336938127"
_PAGE_SIZE = 100_000


class GA4ConfigError(RuntimeError):
    """Raised when required GA4 config is missing."""


def property_id() -> str:
    return os.getenv("GA4_PROPERTY_ID", _DEFAULT_PROPERTY_ID)


class GA4Client:
    """Minimal GA4 Data API client. Handles pagination via offset/limit."""

    def __init__(self, prop_id: str | None = None):
        self.property_id = prop_id or property_id()
        self.client = BetaAnalyticsDataClient()

    def run_report(
        self,
        dimensions: list[str],
        metrics: list[str],
        since: str,
        until: str,
    ) -> Iterator[dict]:
        """Run a GA4 report and yield rows as dicts. Pages until exhausted."""
        offset = 0
        while True:
            request = RunReportRequest(
                property=f"properties/{self.property_id}",
                dimensions=[Dimension(name=d) for d in dimensions],
                metrics=[Metric(name=m) for m in metrics],
                date_ranges=[DateRange(start_date=since, end_date=until)],
                limit=_PAGE_SIZE,
                offset=offset,
                order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
            )
            response = self.client.run_report(request)

            for row in response.rows:
                out: dict = {}
                for i, dim_header in enumerate(response.dimension_headers):
                    out[_to_snake(dim_header.name)] = row.dimension_values[i].value
                for i, met_header in enumerate(response.metric_headers):
                    out[_to_snake(met_header.name)] = row.metric_values[i].value
                yield out

            row_count = getattr(response, "row_count", 0) or 0
            if offset + _PAGE_SIZE >= row_count:
                break
            offset += _PAGE_SIZE

    def verify(self) -> dict:
        """Read-only auth ping. Returns a tiny session count for yesterday."""
        from datetime import date, timedelta

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        rows = list(
            self.run_report(
                dimensions=["date"],
                metrics=["sessions"],
                since=yesterday,
                until=yesterday,
            )
        )
        return {"property_id": self.property_id, "yesterday_rows": rows}
