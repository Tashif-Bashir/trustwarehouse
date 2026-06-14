"""dlt pipeline — loads Unleashed data into BigQuery bronze dataset.

Incremental: the four slow-changing entities (products, sales orders, purchase
orders, customers) use a dlt incremental cursor on `_modified_ms` (epoch ms from
Unleashed's LastModifiedOn) and `merge` by Guid, so each run only pulls records
changed since the last sync. StockOnHand is a live snapshot and stays full-refresh.
"""

import datetime
import os

import dlt
from dotenv import load_dotenv

from ingestion.unleashed.client import UnleashedClient

load_dotenv()

# Re-fetch a 25h window behind the high-water mark so a UTC/local-time skew on the
# API's modifiedSince filter can never drop a record. dlt's incremental cursor then
# keeps only genuinely-new rows, and merge-by-Guid makes the overlap a harmless upsert.
_BUFFER_MS = 25 * 3600 * 1000


def _client() -> UnleashedClient:
    return UnleashedClient()


def _since(last_value_ms: int | None) -> str:
    """Convert the incremental cursor (epoch ms) to an Unleashed modifiedSince string."""
    if not last_value_ms:
        return "2010-01-01T00:00:00"  # first run — full backfill
    ms = max(0, int(last_value_ms) - _BUFFER_MS)
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")


@dlt.resource(name="unleashed_products", write_disposition="merge", primary_key="Guid")
def products_resource(cursor=dlt.sources.incremental("_modified_ms", initial_value=0)):
    yield from _client().get_products(modified_since=_since(cursor.last_value))


@dlt.resource(name="unleashed_stock_on_hand", write_disposition="replace")
def stock_on_hand_resource():
    yield from _client().get_stock_on_hand()


@dlt.resource(name="unleashed_sales_orders", write_disposition="merge", primary_key="Guid")
def sales_orders_resource(cursor=dlt.sources.incremental("_modified_ms", initial_value=0)):
    yield from _client().get_sales_orders(modified_since=_since(cursor.last_value))


@dlt.resource(name="unleashed_purchase_orders", write_disposition="merge", primary_key="Guid")
def purchase_orders_resource(cursor=dlt.sources.incremental("_modified_ms", initial_value=0)):
    yield from _client().get_purchase_orders(modified_since=_since(cursor.last_value))


@dlt.resource(name="unleashed_customers", write_disposition="merge", primary_key="Guid")
def customers_resource(cursor=dlt.sources.incremental("_modified_ms", initial_value=0)):
    yield from _client().get_customers(modified_since=_since(cursor.last_value))


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
