"""dlt pipeline — loads Wildix data into Motherduck bronze schema."""

import os

import dlt
from dotenv import load_dotenv

from ingestion.wildix.client import WildixClient

load_dotenv()


def _client() -> WildixClient:
    return WildixClient()


@dlt.resource(name="wildix_colleagues", write_disposition="replace")
def colleagues_resource():
    """All Wildix users/extensions from WMS — full replace."""
    yield from _client().get_all_colleagues()


@dlt.resource(name="wildix_calls", write_disposition="replace")
def calls_resource():
    """All call history from WDA for every colleague — full replace."""
    yield from _client().get_all_calls()


@dlt.source(name="wildix")
def wildix_source():
    return [
        colleagues_resource(),
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
