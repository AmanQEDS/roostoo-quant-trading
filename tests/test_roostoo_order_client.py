import requests
import pytest

from rq.roostoo.client import RoostooClient, RoostooError


class TimeoutSession:
    def __init__(self):
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        raise requests.Timeout("submission response timed out")


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


def test_query_order_rejects_unsuccessful_api_response(monkeypatch):
    client = RoostooClient(journal=None)
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: {"Success": False, "ErrMsg": "order not found"},
    )

    with pytest.raises(RoostooError, match="order not found"):
        client.query_order(order_id="123")
