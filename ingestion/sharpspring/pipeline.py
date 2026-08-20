"""dlt pipeline — loads SharpSpring data into BigQuery bronze dataset."""

import os

import dlt
from dotenv import load_dotenv

from ingestion.sharpspring.client import SharpSpringClient

load_dotenv()

# Populated by leads_resource() as it yields — captures the full set of lead
# ids the pipeline just loaded, so run_pipeline() can hand them straight to
# the deletion sweep without re-paginating the API. Module-level because dlt
# resources are plain generators; there is no other hook to capture yields.
_captured_lead_ids: set[str] = set()


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
    global _captured_lead_ids
    _captured_lead_ids = set()
    for lead in _client().get_all_leads():
        lead_id = lead.get("id")
        if lead_id is not None:
            _captured_lead_ids.add(str(lead_id))
        yield lead


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
    """Run the SharpSpring → BigQuery bronze pipeline."""
    project = os.environ.get("GCP_PROJECT_ID", "trustwarehouse")

    pipeline = dlt.pipeline(
        pipeline_name="sharpspring",
        destination=dlt.destinations.bigquery(location="europe-west2"),
        dataset_name="bronze",
    )

    load_info = pipeline.run(sharpspring_source())
    print(load_info)

    if not load_info.has_failed_jobs and _captured_lead_ids:
        from ingestion.sharpspring.deletions import sweep

        sweep(_captured_lead_ids)


if __name__ == "__main__":
    run_pipeline()
