"""GA4 Data API → BigQuery bronze ingestion.

Pulls daily sessions by source/medium for the last LOOKBACK_DAYS days,
deletes those dates from bronze first, then inserts fresh rows.
Bronze table: trustwarehouse.bronze.ga4_session_source_medium
"""
import os
from datetime import date, timedelta

import pandas as pd
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)
from google.cloud import bigquery

PROPERTY_ID   = "336938127"
PROJECT       = os.getenv("GCP_PROJECT_ID", "trustwarehouse")
TABLE_ID      = f"{PROJECT}.bronze.ga4_session_source_medium"
LOOKBACK_DAYS = 3  # overlap catches late-arriving GA4 data


def _fetch(start: date, end: date) -> pd.DataFrame:
    client = BetaAnalyticsDataClient()
    request = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=[
            Dimension(name="date"),
            Dimension(name="sessionSource"),
            Dimension(name="sessionMedium"),
            Dimension(name="deviceCategory"),
            Dimension(name="country"),
        ],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="newUsers"),
            Metric(name="bounceRate"),
            Metric(name="averageSessionDuration"),
            Metric(name="screenPageViews"),
        ],
        date_ranges=[DateRange(start_date=str(start), end_date=str(end))],
    )
    response = client.run_report(request)

    rows = []
    for row in response.rows:
        r = {}
        for i, dim_header in enumerate(response.dimension_headers):
            r[dim_header.name] = row.dimension_values[i].value
        for i, met_header in enumerate(response.metric_headers):
            r[met_header.name] = row.metric_values[i].value
        rows.append(r)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["_extracted_at"] = pd.Timestamp.utcnow()
    return df


def _upsert(bq: bigquery.Client, df: pd.DataFrame, start: date, end: date) -> None:
    bq.query(
        f"DELETE FROM `{TABLE_ID}` WHERE date BETWEEN '{start}' AND '{end}'"
    ).result()

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        autodetect=True,
    )
    bq.load_table_from_dataframe(df, TABLE_ID, job_config=job_config).result()
    print(f"Loaded {len(df)} rows into {TABLE_ID}")


def run_pipeline() -> None:
    end   = date.today() - timedelta(days=1)
    start = end - timedelta(days=LOOKBACK_DAYS - 1)

    print(f"Fetching GA4 data: {start} to {end}")
    df = _fetch(start, end)

    if df.empty:
        print("No data returned from GA4.")
        return

    bq = bigquery.Client(project=PROJECT)
    _upsert(bq, df, start, end)
    print("Done.")
