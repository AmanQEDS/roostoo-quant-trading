import json

import pytest
import requests

from rq.roostoo.client import RoostooClient, RoostooError


class TimeoutSession:
    def __init__(self):
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        raise requests.Timeout("submission response timed out")


class SuccessfulOrderResponse:
    status_code = 200

    def json(self):
        return {
            "Success": True,
            "OrderDetail": {
                "OrderID": 123,
                "Status": "FILLED",
                "FilledQuantity": "0.1",
                "FilledAverPrice": "100",
            },
        }


class SuccessfulOrderSession:
    def request(self, *args, **kwargs):
        return SuccessfulOrderResponse()


def test_place_order_timeout_is_not_retried():
    client = RoostooClient(
        api_key="test-key",
        secret="test-secret",
        journal=None,
        min_interval_s=0,
        max_retries=3,
    )
    session = TimeoutSession()
    client.s = session

    with pytest.raises(RoostooError, match="failed after retries"):
        client.place_order("BTC/USD", "BUY", 0.1)

    assert session.calls == 1


def test_execution_journal_scopes_records_without_logging_api_key(tmp_path):
    api_key = "account-key-must-not-be-written"
    journal = tmp_path / "api_journal.jsonl"
    client = RoostooClient(
        api_key=api_key,
        secret="test-secret",
        journal=journal,
        min_interval_s=0,
    )
    client.s = SuccessfulOrderSession()

    client.place_order("BTC/USD", "BUY", 0.1)

    record = json.loads(journal.read_text(encoding="utf-8").splitlines()[0])
    assert record["account_scope"] == client.journal_scope
    assert api_key not in journal.read_text(encoding="utf-8")


def test_query_order_rejects_unsuccessful_api_response(monkeypatch):
    client = RoostooClient(journal=None)
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: {"Success": False, "ErrMsg": "order not found"},
    )

    with pytest.raises(RoostooError, match="order not found"):
        client.query_order(order_id="123")
