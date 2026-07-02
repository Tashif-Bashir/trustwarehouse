"""dlt pipeline — loads Ascend (Focus Group phone system) calls into BigQuery bronze."""

import json
import os
from datetime import datetime, timedelta, timezone

import dlt
from dotenv import load_dotenv

from ingestion.ascend.client import AscendClient

load_dotenv()

_TS_FMT = "%Y-%m-%dT%H:%M:%S.000Z"


def _flatten_call(call: dict) -> dict:
    """Serialize nested from/to objects to JSON strings — bronze stores what arrived."""
    return {
        k: json.dumps(v) if isinstance(v, (list, dict)) else v
        for k, v in call.items()
    }


@dlt.resource(name="ascend_calls", write_disposition="merge", primary_key="id")
def calls_resource():
    """Detailed call records — incremental, deduped by call id.

    Set ASCEND_DATE_FROM=2026-07-01T00:00:00.000Z for a historical backfill.
    Or set ASCEND_LOOKBACK_HOURS for a rolling window (default 2 hours).
    """
    date_from = os.environ.get("ASCEND_DATE_FROM", "")
    if not date_from:
        lookback_hours = int(os.environ.get("ASCEND_LOOKBACK_HOURS", "2"))
        date_from = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime(_TS_FMT)
    date_to = datetime.now(timezone.utc).strftime(_TS_FMT)
    for call in AscendClient().get_calls(date_from=date_from, date_to=date_to):
        yield _flatten_call(call)


@dlt.source(name="ascend")
def ascend_source():
    return [calls_resource()]


def run_pipeline() -> None:
    """Run the Ascend → BigQuery bronze pipeline."""
    pipeline = dlt.pipeline(
        pipeline_name="ascend",
        destination=dlt.destinations.bigquery(location="europe-west2"),
        dataset_name="bronze",
    )
    load_info = pipeline.run(ascend_source())
    print(load_info)


if __name__ == "__main__":
    run_pipeline()
