"""dlt pipeline — loads SharpSpring data into BigQuery bronze dataset."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import dlt
from dotenv import load_dotenv

from ingestion.sharpspring.client import SharpSpringClient

load_dotenv()

# SharpSpring timestamps have no timezone in the payload — CLAUDE.md rules
# they are UK local (Europe/London), matching every other SharpSpring date
# field already handled this way (getFields/dbt sources).
_SS_TZ = ZoneInfo("Europe/London")


def _parse_ss_timestamp(raw: str | None) -> datetime | None:
    """Parse SharpSpring's ``YYYY-MM-DD HH:MM:SS`` timestamp as Europe/London."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_SS_TZ)
    except ValueError:
        return None


# Populated by leads_resource() as it yields — captures the full set of lead
# ids the pipeline just loaded, so run_pipeline() can hand them straight to
# the deletion sweep without re-paginating the API. Module-level because dlt
# resources are plain generators; there is no other hook to capture yields.
_captured_lead_ids: set[str] = set()

# Populated alongside _captured_lead_ids — id -> this run's re-enquiry signal
# fields (page_submitted, marketing_url, description, create_timestamp), fed
# to the returning-lead detector after a successful load. Same rationale:
# no other hook exists to see the rows dlt just yielded.
_captured_lead_signals: dict[str, dict] = {}


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
    global _captured_lead_ids, _captured_lead_signals
    _captured_lead_ids = set()
    _captured_lead_signals = {}
    for lead in _client().get_all_leads():
        lead_id = lead.get("id")
        if lead_id is not None:
            lead_id = str(lead_id)
            _captured_lead_ids.add(lead_id)
            _captured_lead_signals[lead_id] = {
                "page_submitted": lead.get("page_submitted_5af30a9090796") or "",
                "marketing_url": lead.get("exact_marketing_url_64d0bebced518") or "",
                "description": lead.get("description") or "",
                "create_timestamp": _parse_ss_timestamp(lead.get("createTimestamp")),
            }
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

    # Snapshot BEFORE the run — the merge overwrites the re-enquiry signal
    # fields with this load's values, so the "old" state must be captured
    # while bronze still holds it. Order matters (see reenquiries.py).
    from ingestion.sharpspring.reenquiries import take_preload_snapshot

    reenquiries_snapshot, reenquiries_expected = take_preload_snapshot()

    load_info = pipeline.run(sharpspring_source())
    print(load_info)

    if not load_info.has_failed_jobs and _captured_lead_ids:
        from ingestion.sharpspring.deletions import sweep

        sweep(_captured_lead_ids)

    if not load_info.has_failed_jobs and _captured_lead_signals:
        from ingestion.sharpspring.reenquiries import detect

        detect(_captured_lead_signals, reenquiries_snapshot, reenquiries_expected)


if __name__ == "__main__":
    run_pipeline()
