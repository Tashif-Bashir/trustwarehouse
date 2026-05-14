"""dlt pipeline — loads Wildix data into Motherduck bronze schema."""

import json
import os
from datetime import datetime, timedelta, timezone

import dlt
from dotenv import load_dotenv

from ingestion.wildix.client import WildixClient

load_dotenv()


def _client() -> WildixClient:
    return WildixClient()


@dlt.resource(name="wildix_colleagues", write_disposition="replace")
def colleagues_resource():
    """All users/extensions from WMS — full replace."""
    yield from _client().get_all_colleagues()


@dlt.resource(name="wildix_departments", write_disposition="replace")
def departments_resource():
    """All departments from WMS — full replace."""
    yield from _client().get_departments()


@dlt.resource(name="wildix_groups", write_disposition="replace")
def groups_resource():
    """All call groups from WMS — full replace."""
    yield from _client().get_groups()



@dlt.resource(name="wildix_contacts", write_disposition="replace")
def contacts_resource():
    """All phonebook contacts from WMS — full replace."""
    yield from _client().get_contacts()


@dlt.resource(name="wildix_call_history", write_disposition="replace")
def call_history_resource():
    """System-wide PBX call history from WMS — full replace."""
    yield from _client().get_all_call_history()


def _flatten_call(call: dict) -> dict:
    """Serialize any list/dict fields to JSON strings to avoid nested dlt tables."""
    return {
        k: json.dumps(v) if isinstance(v, (list, dict)) else v
        for k, v in call.items()
    }


@dlt.resource(name="wildix_calls", write_disposition="merge", primary_key=["id", "_wms_id"])
def calls_resource():
    """Per-user call history from WDA — incremental, last 2 hours, deduped by (id, wms_id)."""
    date_from = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for call in _client().get_all_calls(date_from=date_from):
        yield _flatten_call(call)


@dlt.source(name="wildix")
def wildix_source():
    return [
        colleagues_resource(),
        departments_resource(),
        groups_resource(),

        contacts_resource(),
        call_history_resource(),
        calls_resource(),
    ]


def run_pipeline() -> None:
    """Run the Wildix → Motherduck bronze pipeline."""
    token = os.environ.get("MOTHERDUCK_TOKEN")
    database = os.environ.get("MOTHERDUCK_DATABASE", "trust-pipeline")

    if not token:
        raise RuntimeError("MOTHERDUCK_TOKEN is not set.")

    pipeline = dlt.pipeline(
        pipeline_name="wildix",
        destination=dlt.destinations.motherduck(f"md:{database}?motherduck_token={token}"),
        dataset_name="bronze",
    )

    load_info = pipeline.run(wildix_source())
    print(load_info)


if __name__ == "__main__":
    run_pipeline()
