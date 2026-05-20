"""dlt pipeline — loads Unleashed data into BigQuery bronze dataset."""

import os

import dlt
from dotenv import load_dotenv

from ingestion.unleashed.client import UnleashedClient

load_dotenv()


def _client() -> UnleashedClient:
    return UnleashedClient()


@dlt.resource(name="unleashed_products", write_disposition="replace")
def products_resource():
    yield from _client().get_products()


@dlt.resource(name="unleashed_stock_on_hand", write_disposition="replace")
def stock_on_hand_resource():
    yield from _client().get_stock_on_hand()


@dlt.resource(name="unleashed_sales_orders", write_disposition="replace")
def sales_orders_resource():
    yield from _client().get_sales_orders()


@dlt.resource(name="unleashed_purchase_orders", write_disposition="replace")
def purchase_orders_resource():
    yield from _client().get_purchase_orders()


@dlt.resource(name="unleashed_customers", write_disposition="replace")
def customers_resource():
    yield from _client().get_customers()


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
