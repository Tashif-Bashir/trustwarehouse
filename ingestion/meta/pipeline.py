"""dlt pipeline — Meta Marketing API → BigQuery bronze (campaign-level daily).

Phase 1 minimum viable replacement for Airbyte's `facebook_adsads_insights`.
Produces `bronze.meta_api_campaign_daily` at campaign × date granularity.

Write disposition is `replace` — each run rewrites the rolling window in full.
Meta revises attribution within ~28 days, so a 7-day rolling window per
scheduled run catches the bulk of late-arriving conversions without re-pulling
all history each time. All-time backfill is done explicitly via --all-time.
"""

import os
from datetime import date, timedelta

import dlt
from dotenv import load_dotenv

from ingestion.meta.client import MetaClient

load_dotenv()


def _row_campaign_daily(row: dict) -> dict:
    def _f(key: str, default=None):
        v = row.get(key)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    def _i(key: str, default=None):
        v = row.get(key)
        try:
            return int(float(v)) if v is not None else default
        except (TypeError, ValueError):
            return default

    return {
        "date": row.get("date_start"),
        "account_id": row.get("account_id"),
        "account_currency": row.get("account_currency"),
        "campaign_id": row.get("campaign_id"),
        "campaign_name": row.get("campaign_name"),
        "objective": row.get("objective"),
        "spend_gbp": _f("spend"),
        "impressions": _i("impressions"),
        "clicks": _i("clicks"),
        "unique_clicks": _i("unique_clicks"),
        "reach": _i("reach"),
        "frequency": _f("frequency"),
        "cpc": _f("cpc"),
        "cpm": _f("cpm"),
        "ctr": _f("ctr"),
    }


def _chunk_dates(since: str, until: str, chunk_days: int = 90):
    """Yield (chunk_start, chunk_end) pairs covering [since, until] in
    chunk_days windows. Meta's insights endpoint times out on very long ranges
    so we chunk to keep individual responses small."""
    s = date.fromisoformat(since)
    u = date.fromisoformat(until)
    cur = s
    while cur <= u:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), u)
        yield cur.isoformat(), chunk_end.isoformat()
        cur = chunk_end + timedelta(days=1)


def _campaign_daily_resource(since: str, until: str):
    @dlt.resource(
        name="meta_api_campaign_daily",
        write_disposition="merge",
        primary_key=["date", "campaign_id"],
    )
    def campaign_daily():
        client = MetaClient()
        for chunk_since, chunk_until in _chunk_dates(since, until, chunk_days=90):
            print(f"  Meta chunk: {chunk_since} -> {chunk_until}")
            for row in client.insights(
                level="campaign", since=chunk_since, until=chunk_until, time_increment=1
            ):
                yield _row_campaign_daily(row)
    return campaign_daily


def run_pipeline(lookback_days: int | None = 7, start_date: str | None = None) -> None:
    """Pull Meta campaign-level daily insights into bronze.

    - Daily run: lookback_days=7 (catches 28-day attribution updates well enough
      with each subsequent run extending the rolling window).
    - Backfill / all-time: pass start_date='2020-01-01'.
    """
    end = date.today()
    if start_date:
        since = start_date
    elif lookback_days:
        since = (end - timedelta(days=lookback_days - 1)).isoformat()
    else:
        raise ValueError("Either lookback_days or start_date must be provided.")
    until = end.isoformat()

    pipeline = dlt.pipeline(
        pipeline_name="meta_api",
        destination=dlt.destinations.bigquery(location="europe-west2"),
        dataset_name="bronze",
    )
    load_info = pipeline.run(_campaign_daily_resource(since, until)())
    print(load_info)
