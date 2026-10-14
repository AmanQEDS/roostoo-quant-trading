import logging

import requests

from rq.live.bot import Feed


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def kline(timestamp_ms):
    return [
        timestamp_ms,
        "1",
        "1",
        "1",
        "1",
        "10",
        timestamp_ms + 299999,
        "10",
        1,
        "5",
        "5",
        "0",
    ]


def test_feed_paginates_requested_history_and_advances_start_time(monkeypatch):
    starts = []
    limits = []

    def fake_get(_url, *, params, timeout):
        assert timeout == 15.0
        starts.append(params.get("startTime"))
        limits.append(params["limit"])
        first = params["startTime"]
        count = params["limit"]
        return FakeResponse([kline(first + i * Feed.interval_ms) for i in range(count)])

    monkeypatch.setattr("rq.live.bot.requests.get", fake_get)
    feed = Feed(["BTC"], warm_bars=2001)

    feed.update()

    assert limits == [1000, 1000, 1]
    assert starts[1] == starts[0] + 1000 * Feed.interval_ms
    assert starts[2] == starts[1] + 1000 * Feed.interval_ms
    assert len(feed.d["BTC"]) == 2001
    assert feed.d["BTC"].index.is_monotonic_increasing


def test_feed_keeps_full_9000_bar_strategy_warmup_and_logs_progress(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    calls = []

    def fake_get(_url, *, params, timeout):
        first = params["startTime"]
        calls.append(params["limit"])
        return FakeResponse(
            [kline(first + i * Feed.interval_ms) for i in range(params["limit"])]
        )

    monkeypatch.setattr("rq.live.bot.requests.get", fake_get)
    feed = Feed(["BTC"], warm_bars=9000)

    feed.update()

    assert calls == [1000] * 9
    assert len(feed.d["BTC"]) == 9000
    assert "batch=9/9" in caplog.text
    assert "requests=9" in caplog.text


def test_feed_empty_initial_page_stops_without_looping(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "rq.live.bot.requests.get",
        lambda *_args, **_kwargs: (calls.append(1) or FakeResponse([])),
    )
    feed = Feed(["BTC"], warm_bars=2000)

    feed.update()

    assert len(calls) == 1
    assert feed.d["BTC"].empty


def test_feed_stops_if_pagination_does_not_advance(monkeypatch):
    now_ms = int(__import__("time").time() * 1000)
    repeated = [kline(now_ms - 1000 * Feed.interval_ms + i * Feed.interval_ms) for i in range(1000)]
    calls = []

    def fake_get(*_args, **_kwargs):
        calls.append(1)
        return FakeResponse(repeated)

    monkeypatch.setattr("rq.live.bot.requests.get", fake_get)
    monkeypatch.setattr("rq.live.bot.time.sleep", lambda *_args: None)
    feed = Feed(["BTC"], warm_bars=3000)

    feed.update()

    assert len(calls) == 2
    assert len(feed.d["BTC"]) <= 1000


def test_feed_retries_request_failures_a_bounded_number_of_times(monkeypatch):
    calls = []

    def failing_get(*_args, **_kwargs):
        calls.append(1)
        raise requests.Timeout("simulated timeout")

    monkeypatch.setattr("rq.live.bot.requests.get", failing_get)
    monkeypatch.setattr("rq.live.bot.time.sleep", lambda *_args: None)
    feed = Feed(["BTC"], warm_bars=1000, max_retries=3)

    feed.update()

    assert len(calls) == 3
    assert "BTC" not in feed.d
