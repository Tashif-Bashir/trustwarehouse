"""Motherduck connection helper."""

import os

import duckdb
from dotenv import load_dotenv

load_dotenv()


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return an open connection to the Motherduck warehouse.

    Reads MOTHERDUCK_TOKEN and MOTHERDUCK_DATABASE from the environment.
    Raises a descriptive RuntimeError if either is missing.
    """
    token = os.getenv("MOTHERDUCK_TOKEN")
    database = os.getenv("MOTHERDUCK_DATABASE")

    if not token:
        raise RuntimeError(
            "MOTHERDUCK_TOKEN is not set. "
            "Add it to your .env file or GitHub Secrets."
        )
    if not database:
        raise RuntimeError(
            "MOTHERDUCK_DATABASE is not set. "
            "Add it to your .env file or GitHub Secrets."
        )

    connection_string = f"md:{database}?motherduck_token={token}"
    return duckdb.connect(connection_string)
