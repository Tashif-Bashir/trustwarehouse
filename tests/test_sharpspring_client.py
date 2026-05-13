"""Unit tests for the SharpSpring API client (HTTP layer mocked)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from ingestion.sharpspring.client import SharpSpringClient, SharpSpringError


@pytest.fixture
def client():
    return SharpSpringClient(account_id="test-account", secret_key="test-secret")


def _mock_response(result: dict, status_code: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = {"result": result, "error": None, "id": "test-id"}
    mock.raise_for_status = MagicMock()
    return mock


# --- JSON-RPC body formation ---

def test_correct_jsonrpc_body_formed(client):
    with patch("ingestion.sharpspring.client.requests.post") as mock_post:
        mock_post.return_value = _mock_response({"campaign": []})
        client.get_campaigns()

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
        assert payload["method"] == "getCampaigns"
        assert "params" in payload
        assert "id" in payload


def test_auth_params_sent_in_query_string(client):
    with patch("ingestion.sharpspring.client.requests.post") as mock_post:
        mock_post.return_value = _mock_response({"campaign": []})
        client.get_campaigns()

        url_params = mock_post.call_args.kwargs.get("params") or mock_post.call_args[1].get("params")
        assert url_params["accountID"] == "test-account"
        assert url_params["secretKey"] == "test-secret"


# --- Pagination ---

def test_pagination_fetches_all_pages(client):
    page1 = [{"id": str(i)} for i in range(500)]
    page2 = [{"id": str(i)} for i in range(500, 520)]

    responses = [
        _mock_response({"lead": page1}),
        _mock_response({"lead": page2}),
    ]
    with patch("ingestion.sharpspring.client.requests.post", side_effect=responses):
        leads = client.get_all_leads()

    assert len(leads) == 520


def test_single_page_stops_pagination(client):
    page = [{"id": str(i)} for i in range(10)]
    with patch("ingestion.sharpspring.client.requests.post") as mock_post:
        mock_post.return_value = _mock_response({"lead": page})
        leads = client.get_all_leads()

    assert len(leads) == 10
    assert mock_post.call_count == 1


# --- Retry / backoff ---

def test_429_triggers_backoff_and_retries(client):
    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.raise_for_status = MagicMock()

    success = _mock_response({"campaign": [{"id": "1"}]})

    with patch("ingestion.sharpspring.client.requests.post", side_effect=[rate_limited, success]):
        with patch("ingestion.sharpspring.client.time.sleep") as mock_sleep:
            result = client.get_campaigns()

    assert result == [{"id": "1"}]
    mock_sleep.assert_called()


def test_three_consecutive_429s_raises(client):
    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.raise_for_status = MagicMock()

    with patch("ingestion.sharpspring.client.requests.post", return_value=rate_limited):
        with patch("ingestion.sharpspring.client.time.sleep"):
            with pytest.raises(SharpSpringError, match="Failed after 3 attempts"):
                client.get_campaigns()


# --- Auth failure ---

def test_api_error_payload_raises(client):
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {
        "result": None,
        "error": {"code": 302, "message": "Invalid application credentials"},
        "id": "test",
    }
    mock.raise_for_status = MagicMock()

    with patch("ingestion.sharpspring.client.requests.post", return_value=mock):
        with pytest.raises(SharpSpringError, match="Invalid application credentials"):
            client.get_campaigns()


# --- Missing credentials ---

def test_missing_account_id_raises(monkeypatch):
    monkeypatch.delenv("SHARPSPRING_ACCOUNT_ID", raising=False)
    with pytest.raises(RuntimeError, match="SHARPSPRING_ACCOUNT_ID is not set"):
        SharpSpringClient(secret_key="some-key")


def test_missing_secret_key_raises(monkeypatch):
    monkeypatch.delenv("SHARPSPRING_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SHARPSPRING_SECRET_KEY is not set"):
        SharpSpringClient(account_id="some-id")
