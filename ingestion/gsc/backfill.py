"""One-off backfill: 16 trailing months of Google Search Console analytics -> bronze.

Loads two bronze tables (WRITE_TRUNCATE, europe-west2):
  - bronze.gsc_search_analytics_backfill  detailed: date x query x page x device x country
  - bronze.gsc_daily_totals_backfill      validation: date-level clicks/impressions/position

Run once: `python -m ingestion.gsc.backfill`. Not on a schedule — this is a
backfill, not the ongoing sync (that would be a separate incremental pipeline).

Bronze rule: every dimension/metric value from the API response is stored as
returned (strings for dimensions, native numbers for clicks/impressions/ctr/
position — GSC returns these as JSON numbers, not stringified). No casting,
no derived columns beyond the required `_backfilled_at` load timestamp.
"""

import sys
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from dateutil.relativedelta import relativedelta
from google.cloud import bigquery
from googleapiclient.errors import HttpError

from ingestion.gsc.client import GSCClient

PROJECT = "trustwarehouse"
DATASET = "bronze"
DETAIL_TABLE = "gsc_search_analytics_backfill"
TOTALS_TABLE = "gsc_daily_totals_backfill"
LOCATION = "europe-west2"

DETAIL_DIMENSIONS = ["date", "query", "page", "device", "country"]
TOTALS_DIMENSIONS = ["date"]

PAUSE_BETWEEN_CALLS_SECONDS = 0.2


def pick_property(sites: list[dict]) -> str:
    """Pick the company's main site property from the SA's sites().list() result.

    Prefers a URL-prefix property containing 'trustelectricheating'; falls back
    to the only property if there's exactly one. Raises if ambiguous.
    """
    if not sites:
        raise RuntimeError("No sites visible to the service account.")
    if len(sites) == 1:
        return sites[0]["siteUrl"]
    matches = [s["siteUrl"] for s in sites if "trustelectricheating" in s["siteUrl"]]
    if len(matches) == 1:
        return matches[0]
    raise RuntimeError(f"Could not unambiguously pick a property from: {sites}")


def compute_window() -> tuple[date, date]:
    """16 months back, ending 3 days before today (GSC data lags ~2-3 days)."""
    end = date.today() - timedelta(days=3)
    start = end - relativedelta(months=16)
    return start, end


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def pull_detailed(client: GSCClient, site_url: str, start: date, end: date) -> list[dict]:
    """Chunk one day per request; brief pause between calls; back off on 429."""
    rows: list[dict] = []
    days = list(_daterange(start, end))
    for i, day in enumerate(days):
        day_str = day.isoformat()
        try:
            day_rows = list(
                client.query(
                    site_url=site_url,
                    start_date=day_str,
                    end_date=day_str,
                    dimensions=DETAIL_DIMENSIONS,
                )
            )
        except HttpError as e:
            print(f"  STOPPED at {day_str} ({i}/{len(days)} days done) after 429 retries: {e}")
            print(f"  Rows collected before stopping: {len(rows)}")
            return rows
        rows.extend(day_rows)
        if (i + 1) % 30 == 0 or i == len(days) - 1:
            print(f"  detailed: {day_str} ({i + 1}/{len(days)} days, {len(rows)} rows so far)")
        time.sleep(PAUSE_BETWEEN_CALLS_SECONDS)
    return rows


def pull_daily_totals(client: GSCClient, site_url: str, start: date, end: date) -> list[dict]:
    """Month-chunked pulls of the [date] dimension for validation totals."""
    rows: list[dict] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + relativedelta(months=1) - timedelta(days=1), end)
        chunk_rows = list(
            client.query(
                site_url=site_url,
                start_date=cur.isoformat(),
                end_date=chunk_end.isoformat(),
                dimensions=TOTALS_DIMENSIONS,
            )
        )
        rows.extend(chunk_rows)
        print(f"  totals: {cur.isoformat()} -> {chunk_end.isoformat()} ({len(chunk_rows)} rows)")
        time.sleep(PAUSE_BETWEEN_CALLS_SECONDS)
        cur = chunk_end + timedelta(days=1)
    return rows


def load_bronze(rows: list[dict], table: str) -> int:
    """WRITE_TRUNCATE load of `rows` into bronze.{table}, with _backfilled_at added."""
    df = pd.DataFrame(rows)
    df["_backfilled_at"] = datetime.now(timezone.utc)
    bq = bigquery.Client(project=PROJECT)
    job = bq.load_table_from_dataframe(
        df,
        f"{PROJECT}.{DATASET}.{table}",
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
        location=LOCATION,
    )
    job.result()
    return len(df)


def run() -> None:
    client = GSCClient()

    # step 1: live test
    sites = client.list_sites()
    if not sites:
        print("sites().list() returned empty — waiting 60s for permission propagation, retrying once...")
        time.sleep(60)
        sites = client.list_sites()
        if not sites:
            print("STOP: sites().list() still empty after retry. Reporting and halting.")
            sys.exit(1)
    print(f"Sites visible to SA: {sites}")

    site_url = pick_property(sites)
    print(f"Using property: {site_url}")

    start, end = compute_window()
    print(f"Backfill window: {start.isoformat()} -> {end.isoformat()}")

    print("Pulling DETAILED dataset (date x query x page x device x country)...")
    detail_rows = pull_detailed(client, site_url, start, end)
    print(f"Detailed rows pulled: {len(detail_rows)}")

    print("Pulling DAILY TOTALS dataset (date)...")
    totals_rows = pull_daily_totals(client, site_url, start, end)
    print(f"Totals rows pulled: {len(totals_rows)}")

    print("Loading bronze tables...")
    n_detail = load_bronze(detail_rows, DETAIL_TABLE)
    n_totals = load_bronze(totals_rows, TOTALS_TABLE)
    print(f"Loaded {n_detail} rows -> bronze.{DETAIL_TABLE}")
    print(f"Loaded {n_totals} rows -> bronze.{TOTALS_TABLE}")

    # ---- acceptance checks ----
    totals_df = pd.DataFrame(totals_rows)
    detail_df = pd.DataFrame(detail_rows)

    expected_days = (end - start).days + 1
    got_days = totals_df["date"].nunique() if not totals_df.empty else 0
    print(f"\n(a) Days check: expected {expected_days}, got {got_days} distinct days in totals table.")

    totals_df["month"] = totals_df["date"].str[:7]
    detail_df["month"] = detail_df["date"].str[:7]
    totals_by_month = totals_df.groupby("month")["clicks"].sum()
    detail_by_month = detail_df.groupby("month")["clicks"].sum()
    coverage = (detail_by_month / totals_by_month * 100).round(1)
    overall_coverage = round(detail_df["clicks"].sum() / totals_df["clicks"].sum() * 100, 1)
    print(f"(b) Detailed vs totals clicks coverage per month:\n{coverage}")
    print(f"    Overall coverage: {overall_coverage}%")

    july_totals = totals_df[totals_df["month"] == "2026-07"]["clicks"].sum()
    july_detail = detail_df[detail_df["month"] == "2026-07"]
    top3 = (
        july_detail.groupby("query")["clicks"].sum().sort_values(ascending=False).head(3)
    )
    print(f"\n(c) July 2026 total clicks (from totals table): {july_totals}")
    print(f"    Top 3 queries by clicks (from detailed table):\n{top3}")


if __name__ == "__main__":
    run()
