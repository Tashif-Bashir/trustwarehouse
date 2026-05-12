"""Integration test for Motherduck connection — skipped if token not set."""

import os

import pytest
from dotenv import load_dotenv

# Load .env before the skipif decorator is evaluated
load_dotenv()


@pytest.mark.skipif(
    not os.getenv("MOTHERDUCK_TOKEN"),
    reason="MOTHERDUCK_TOKEN not set — skipping live connection test",
)
def test_motherduck_connection():
    from shared.motherduck import get_connection

    conn = get_connection()
    result = conn.sql("SELECT 1 AS test").fetchone()
    assert result == (1,), f"Expected (1,) but got {result}"


def test_motherduck_missing_token(monkeypatch):
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    monkeypatch.delenv("MOTHERDUCK_DATABASE", raising=False)

    from shared.motherduck import get_connection

    with pytest.raises(RuntimeError, match="MOTHERDUCK_TOKEN is not set"):
        get_connection()


def test_motherduck_missing_database(monkeypatch):
    monkeypatch.setenv("MOTHERDUCK_TOKEN", "fake-token")
    monkeypatch.delenv("MOTHERDUCK_DATABASE", raising=False)

    from shared.motherduck import get_connection

    with pytest.raises(RuntimeError, match="MOTHERDUCK_DATABASE is not set"):
        get_connection()
