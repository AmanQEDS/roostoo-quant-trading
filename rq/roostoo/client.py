"""Roostoo REST client (original implementation of the documented API).

Documented behaviour we rely on (github.com/roostoo/Roostoo-API-Documents):
  * Base URL https://mock-api.roostoo.com
  * Signed endpoints: HMAC-SHA256(secret, sorted "k=v&k=v" of params) in header
    MSG-SIGNATURE, key in header RST-API-KEY, 13-digit ms `timestamp` param,
    request rejected if |server - timestamp| > 60 s.
  * Failed requests still return HTTP 200 -> ALWAYS check the `Success` flag.
  * /v3/ticker is the ONLY market-data endpoint (no candles, no order book).
  * Shorts live under /v6 and are sized by USD `collateral`.
Every request/response is appended to a JSONL journal: judges check trade-log
integrity and "no traces of manually called APIs".
"""
from __future__ import annotations
import hashlib, hmac, json, os, time
from pathlib import Path
from typing import Any
import requests

BASE_URL = "https://mock-api.roostoo.com"


class RoostooError(RuntimeError):
    pass


class RoostooClient:
    def __init__(self, api_key: str | None = None, secret: str | None = None,
                 base_url: str = BASE_URL, journal: str | Path | None = "logs/api_journal.jsonl",
                 min_interval_s: float = 0.4, timeout: float = 10.0, max_retries: int = 3):
        self.key = api_key or os.environ.get("ROOSTOO_API_KEY", "")
        self.secret = secret or os.environ.get("ROOSTOO_API_SECRET", "")
        self.base = base_url.rstrip("/")
        self.journal = Path(journal) if journal else None
        if self.journal:
            self.journal.parent.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval_s       # polite throttle: HFT / request spam is prohibited
        self.timeout, self.max_retries = timeout, max_retries
        self._last_call = 0.0
        self._clock_offset_ms = 0
        self.s = requests.Session()

    # ---- plumbing -----------------------------------------------------------
    def _ts(self) -> str:
        return str(int(time.time() * 1000) + self._clock_offset_ms)

    def _sign(self, params: dict[str, Any]) -> tuple[dict, str]:
        total = "&".join(f"{k}={params[k]}" for k in sorted(params))
        sig = hmac.new(self.secret.encode(), total.encode(), hashlib.sha256).hexdigest()
        return {"RST-API-KEY": self.key, "MSG-SIGNATURE": sig}, total

    def _log(self, rec: dict) -> None:
        if self.journal:
            with open(self.journal, "a") as f:
                f.write(json.dumps(rec, default=str) + "\n")

    def _request(self, method: str, path: str, params: dict | None = None, signed: bool = False,
                 ts_required: bool = False, attempts: int | None = None) -> dict:
        params = dict(params or {})
        if signed or ts_required:
            params["timestamp"] = self._ts()
        headers: dict[str, str] = {}
        body: str | None = None
        query: dict | str | None = None
        if signed:
            headers, total = self._sign(params)
            if method == "POST":
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                body = total
            else:
                query = total
        else:
            query = params or None
        last_err: Exception | None = None
        for attempt in range(attempts or self.max_retries):
            wait = self.min_interval - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()
            t0 = time.time()
            try:
                url = f"{self.base}{path}" + (f"?{query}" if isinstance(query, str) else "")
                r = self.s.request(method, url, headers=headers,
                                   params=None if isinstance(query, str) else query,
                                   data=body, timeout=self.timeout)
                data = r.json()
                self._log({"t": time.time(), "method": method, "path": path,
                           "params": {k: v for k, v in params.items() if k != "timestamp"},
                           "http": r.status_code, "latency_s": round(time.time() - t0, 4),
                           "resp": data})
                if r.status_code >= 500:
                    raise RoostooError(f"HTTP {r.status_code}")
                return data
            except (requests.RequestException, ValueError, RoostooError) as e:
                last_err = e
                self._log({"t": time.time(), "method": method, "path": path, "error": repr(e),
                           "attempt": attempt})
                time.sleep(min(2 ** attempt, 8))
        raise RoostooError(f"{method} {path} failed after retries: {last_err}")

    @staticmethod
    def _ok(resp: dict) -> dict:
        if not resp.get("Success", True):
            raise RoostooError(resp.get("ErrMsg", "unknown error"))
        return resp

    # ---- public -------------------------------------------------------------
    def server_time(self) -> int:
        return int(self._request("GET", "/v3/serverTime")["ServerTime"])

    def sync_clock(self) -> int:
        """Align local clock to the server (60 s tolerance on signed calls)."""
        t0 = int(time.time() * 1000)
        srv = self.server_time()
        self._clock_offset_ms = srv - (t0 + int(time.time() * 1000)) // 2
        return self._clock_offset_ms

    def exchange_info(self) -> dict:
        return self._request("GET", "/v3/exchangeInfo")

    def ticker(self, pair: str | None = None) -> dict:
        return self._ok(self._request("GET", "/v3/ticker", {"pair": pair} if pair else {}, ts_required=True))["Data"]

    # ---- signed -------------------------------------------------------------
    def balance(self) -> dict:
        r = self._ok(self._request("GET", "/v3/balance", signed=True))
        w = r.get("SpotWallet") or r.get("Wallet")
        if w is None:
            raise RoostooError(f"balance response keys: {list(r.keys())}")
        return w

    def pending_count(self) -> dict:
        return self._request("GET", "/v3/pending_count", signed=True)

    def place_order(self, pair: str, side: str, quantity: float, price: float | None = None) -> dict:
        p = {"pair": pair, "side": side.upper(), "quantity": _fmt(quantity),
             "type": "LIMIT" if price is not None else "MARKET"}
        if price is not None:
            p["price"] = _fmt(price)
        return self._ok(self._request("POST", "/v3/place_order", p, signed=True, attempts=1))["OrderDetail"]

    def query_order(self, order_id: str | None = None, pair: str | None = None,
                    pending_only: bool | None = None) -> dict:
        p: dict[str, str] = {}
        if order_id:
            p["order_id"] = str(order_id)
        else:
            if pair:
                p["pair"] = pair
            if pending_only is not None:
                p["pending_only"] = "TRUE" if pending_only else "FALSE"
        return self._request("POST", "/v3/query_order", p, signed=True)

    def cancel_order(self, order_id: str | None = None, pair: str | None = None) -> dict:
        p = {"order_id": str(order_id)} if order_id else ({"pair": pair} if pair else {})
        return self._request("POST", "/v3/cancel_order", p, signed=True)

    def short_open(self, pair: str, collateral: float, price: float | None = None) -> dict:
        p = {"pair": pair, "collateral": _fmt(collateral)}
        if price is not None:
            p.update({"order_type": "LIMIT", "price": _fmt(price)})
        return self._ok(self._request("POST", "/v6/short_open", p, signed=True))

    def short_close(self, pair: str, close_pct: float | None = None, close_qty: float | None = None) -> dict:
        p: dict[str, str] = {"pair": pair}
        if close_qty is not None:
            p["close_qty"] = _fmt(close_qty)
        elif close_pct is not None:
            p["close_pct"] = _fmt(close_pct)
        return self._ok(self._request("POST", "/v6/short_close", p, signed=True))

    def short_positions(self) -> list[dict]:
        return self._ok(self._request("GET", "/v6/short_positions", signed=True)).get("Positions", [])


def _fmt(x: float) -> str:
    return f"{x:.10f}".rstrip("0").rstrip(".")
