"""Separate dlt pipeline for SharpSpring lead notes.

Runs on its own slow (daily) schedule — deliberately NOT bundled with the main
30-minute sharpspring sync. Fetching notes requires one API call per lead, so a
full pass takes 20-30 minutes; bundling it would block the lead/campaign sync.

It uses its own dlt pipeline name (``sharpspring_notes``) so its incremental
state is isolated from the main ``sharpspring`` pipeline.

Incremental strategy: rather than re-paginating all ~58k leads from the API on
every run, it reads candidate lead ids straight from ``bronze.sharpspring_leads``
(kept fresh by the 30-minute sync), restricted to appointment-booked leads
updated since the last run. Notes are merged on the note ``id``.

Env overrides:
- ``SHARPSPRING_NOTES_FULL_BACKFILL=1`` — ignore the cursor and fetch notes for
  every appointment-booked lead (all history). Slow (~50 min).
- ``SHARPSPRING_NOTES_SINCE_DAYS`` — first-run look-back window in days when no
  cursor exists yet (default 90).
"""

import os
from datetime import datetime, timedelta, timezone

import dlt
import google.auth
from dotenv import load_dotenv
from google.cloud import bigquery

from ingestion.sharpspring.client import SharpSpringClient

load_dotenv()

_PROJECT = os.environ.get("GCP_PROJECT_ID", "trustwarehouse")
_BQ_LOCATION = "europe-west2"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _candidate_lead_ids(since: datetime) -> list[str]:
    """Return ids of appointment-booked leads updated since ``since``.

    Reads from bronze (kept fresh by the main 30-minute sync) so we avoid
    re-paginating every lead from the API on each notes run.
    """
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/bigquery"])
    bq = bigquery.Client(project=_PROJECT, credentials=creds, location=_BQ_LOCATION)
    job = bq.query(
        """
        SELECT CAST(id AS STRING) AS id
        FROM `trustwarehouse.bronze.sharpspring_leads`
        WHERE appointment_booked_5ae8cb01a35c6 = 'Yes'
          AND update_timestamp > @since
        ORDER BY update_timestamp
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("since", "TIMESTAMP", since)]
        ),
    )
    return [row["id"] for row in job.result()]


@dlt.resource(name="sharpspring_notes", write_disposition="merge", primary_key="id")
def notes_resource():
    """Yield notes for appointment leads updated since the last run."""
    state = dlt.current.resource_state()

    if os.getenv("SHARPSPRING_NOTES_FULL_BACKFILL", "").strip() == "1":
        since = datetime(2000, 1, 1, tzinfo=timezone.utc)
    elif state.get("cursor"):
        since = datetime.fromisoformat(state["cursor"])
    else:
        days = int(os.getenv("SHARPSPRING_NOTES_SINCE_DAYS", "90"))
        since = _now_utc() - timedelta(days=days)

    run_start = _now_utc()
    client = SharpSpringClient()
    lead_ids = _candidate_lead_ids(since)
    print(
        f"sharpspring_notes: fetching notes for {len(lead_ids)} leads "
        f"(updated since {since.isoformat()})",
        flush=True,
    )

    for i, lead_id in enumerate(lead_ids, 1):
        yield from client.get_contact_notes(lead_id)
        if i % 100 == 0:
            print(f"  ...{i}/{len(lead_ids)} leads done", flush=True)

    # Advance cursor to when this run started; any lead updated mid-run is caught
    # next time (merge makes the small overlap idempotent).
    state["cursor"] = run_start.isoformat()


def run_notes_pipeline() -> None:
    """Run the SharpSpring notes → BigQuery bronze pipeline."""
    pipeline = dlt.pipeline(
        pipeline_name="sharpspring_notes",
        destination=dlt.destinations.bigquery(location=_BQ_LOCATION),
        dataset_name="bronze",
    )
    load_info = pipeline.run(notes_resource())
    print(load_info)


if __name__ == "__main__":
    run_notes_pipeline()
