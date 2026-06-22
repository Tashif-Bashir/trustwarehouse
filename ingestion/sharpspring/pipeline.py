"""dlt pipeline — loads SharpSpring data into BigQuery bronze dataset."""

import os
from datetime import datetime, timedelta

import dlt
from dotenv import load_dotenv

from ingestion.sharpspring.client import SharpSpringClient

load_dotenv()


def _client() -> SharpSpringClient:
    return SharpSpringClient()


@dlt.resource(
    name="sharpspring_leads",
    write_disposition="merge",
    primary_key="id",
)
def leads_resource():
    """Full paginated load of all leads, merged on id (upsert).
    SharpSpring getLeads where clause only accepts id/emailAddress — updateTimestamp
    filtering is not supported server-side, so we always fetch all records."""
    yield from _client().get_all_leads()


@dlt.resource(name="sharpspring_campaigns", write_disposition="replace")
def campaigns_resource():
    """All campaigns — full replace."""
    yield from _client().get_campaigns()


@dlt.resource(name="sharpspring_opportunities", write_disposition="replace")
def opportunities_resource():
    """All opportunities — full replace."""
    yield from _client().get_opportunities()


@dlt.resource(name="sharpspring_fields", write_disposition="replace")
def fields_resource():
    """Field definitions — maps custom hash IDs to human-readable labels."""
    yield from _client().get_fields()


@dlt.resource(name="sharpspring_deal_stages", write_disposition="replace")
def deal_stages_resource():
    """Deal stage definitions (Appointment Booked, Appointment Done, etc.)."""
    yield from _client().get_deal_stages()


@dlt.resource(
    name="sharpspring_notes",
    write_disposition="merge",
    primary_key="id",
)
def notes_resource():
    """Notes for leads with appointments, fetched incrementally via dlt state.

    On first run fetches notes for all appointment leads updated in the last 90 days.
    On subsequent runs only processes leads updated since the previous run.
    Set SHARPSPRING_NOTES_FULL_BACKFILL=1 to fetch all appointment leads regardless of age.
    """
    state = dlt.current.resource_state()
    full_backfill = os.getenv("SHARPSPRING_NOTES_FULL_BACKFILL", "").strip() == "1"

    if full_backfill:
        lead_cutoff = "2000-01-01 00:00:00"
    else:
        lead_cutoff = state.get(
            "last_lead_update_seen",
            (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S"),
        )

    client = _client()
    max_update_seen = lead_cutoff

    for lead in client.get_all_leads():
        if lead.get("appointment_booked_5ae8cb01a35c6") != "Yes":
            continue
        updated = lead.get("updateTimestamp", "")
        if updated < lead_cutoff:
            continue
        if updated > max_update_seen:
            max_update_seen = updated
        yield from client.get_contact_notes(str(lead["id"]))

    state["last_lead_update_seen"] = max_update_seen


@dlt.source(name="sharpspring")
def sharpspring_source():
    return [
        leads_resource(),
        campaigns_resource(),
        opportunities_resource(),
        fields_resource(),
        deal_stages_resource(),
        notes_resource(),
    ]


def run_pipeline() -> None:
    """Run the SharpSpring → BigQuery bronze pipeline."""
    project = os.environ.get("GCP_PROJECT_ID", "trustwarehouse")

    pipeline = dlt.pipeline(
        pipeline_name="sharpspring",
        destination=dlt.destinations.bigquery(location="europe-west2"),
        dataset_name="bronze",
    )

    load_info = pipeline.run(sharpspring_source())
    print(load_info)


if __name__ == "__main__":
    run_pipeline()
