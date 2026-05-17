"""dlt pipeline — loads SharpSpring data into Motherduck bronze schema."""

import os

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
def leads_resource(
    updated_since: dlt.sources.incremental[str] = dlt.sources.incremental(
        "update_timestamp",
        initial_value="2020-01-01 00:00:00",
    ),
):
    """Leads updated since the last successful run (incremental merge by id).

    On first run: fetches all leads from 2020-01-01 onwards.
    On subsequent runs: only fetches leads whose update_timestamp changed since
    the previous cursor high-watermark, then upserts them by lead id.
    SharpSpring returns leads in ascending updateTimestamp order, so the cursor
    advances correctly as pages are consumed.
    """
    from datetime import datetime

    since_dt = datetime.strptime(updated_since.last_value, "%Y-%m-%d %H:%M:%S")
    yield from _client().get_all_leads(updated_since=since_dt)


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


@dlt.source(name="sharpspring")
def sharpspring_source():
    return [
        leads_resource(),
        campaigns_resource(),
        opportunities_resource(),
        fields_resource(),
        deal_stages_resource(),
    ]


def run_pipeline() -> None:
    """Run the SharpSpring → Motherduck bronze pipeline."""
    token = os.environ.get("MOTHERDUCK_TOKEN")
    database = os.environ.get("MOTHERDUCK_DATABASE", "trust-pipeline")

    if not token:
        raise RuntimeError("MOTHERDUCK_TOKEN is not set.")

    pipeline = dlt.pipeline(
        pipeline_name="sharpspring",
        destination=dlt.destinations.motherduck(f"md:{database}?motherduck_token={token}"),
        dataset_name="bronze",
    )

    load_info = pipeline.run(sharpspring_source())
    print(load_info)


if __name__ == "__main__":
    run_pipeline()
