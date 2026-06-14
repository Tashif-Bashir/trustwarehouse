"""dlt pipeline — loads Unleashed data into BigQuery bronze dataset.

Incremental: the four slow-changing entities (products, sales orders, purchase
orders, customers) only pull records changed since the last sync. The API's
`modifiedSince` filter does the filtering; we persist the high-water mark
(max LastModifiedOn, as epoch ms) in dlt resource state and `merge` by Guid.
StockOnHand is a live snapshot and stays full-refresh.

Note: we deliberately do NOT use dlt.sources.incremental here — it truncated
the generator to a single page. The API filter + resource-state watermark is
equivalent and reliable.
"""

import datetime
import os

import dlt
from dotenv import load_dotenv

from ingestion.unleashed.client import UnleashedClient

load_dotenv()

# Re-fetch a 25h window behind the high-water mark so a UTC/local-time skew on the
# API's modifiedSince filter can never drop a record. merge-by-Guid makes the
# re-fetched overlap a harmless upsert.
_BUFFER_MS = 25 * 3600 * 1000


def _client() -> UnleashedClient:
    return UnleashedClient()


def _since(last_value_ms: int) -> str:
    """Convert the stored watermark (epoch ms) to an Unleashed modifiedSince string."""
    if not last_value_ms:
        return "2010-01-01T00:00:00"  # first run — full backfill
    ms = max(0, int(last_value_ms) - _BUFFER_MS)
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")


def _pull(fetch):
    """Yield every row the API returns since the stored watermark, advancing it.

    `fetch` is a bound client method (e.g. client.get_customers) taking modified_since.
    The watermark lives in dlt resource state and persists across runs.
    """
    state = dlt.current.resource_state()
    last_ms = state.get("max_modified_ms", 0)
    max_seen = last_ms
    for item in fetch(modified_since=_since(last_ms)):
        ms = item.get("_modified_ms", 0)
        if ms > max_seen:
            max_seen = ms
        yield item
    state["max_modified_ms"] = max_seen


@dlt.resource(name="unleashed_products", write_disposition="merge", primary_key="Guid")
def products_resource():
    yield from _pull(_client().get_products)


@dlt.resource(name="unleashed_stock_on_hand", write_disposition="replace")
def stock_on_hand_resource():
    yield from _client().get_stock_on_hand()


@dlt.resource(name="unleashed_sales_orders", write_disposition="merge", primary_key="Guid")
def sales_orders_resource():
    yield from _pull(_client().get_sales_orders)


@dlt.resource(name="unleashed_purchase_orders", write_disposition="merge", primary_key="Guid")
def purchase_orders_resource():
    yield from _pull(_client().get_purchase_orders)


@dlt.resource(name="unleashed_customers", write_disposition="merge", primary_key="Guid")
def customers_resource():
    yield from _pull(_client().get_customers)


@dlt.source(name="unleashed")
def unleashed_source():
    return [
        products_resource(),
        stock_on_hand_resource(),
        sales_orders_resource(),
        purchase_orders_resource(),
        customers_resource(),
    ]


def run_pipeline() -> None:
    """Run the Unleashed → BigQuery bronze pipeline."""
    project = os.environ.get("GCP_PROJECT_ID", "trustwarehouse")

    pipeline = dlt.pipeline(
        pipeline_name="unleashed",
        destination=dlt.destinations.bigquery(location="europe-west2"),
        dataset_name="bronze",
    )

    load_info = pipeline.run(unleashed_source())
    print(load_info)


if __name__ == "__main__":
    run_pipeline()
