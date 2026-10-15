import json
from datetime import datetime, timezone
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.quotes import fetch_quote


def timestamp(hour, minute=0):
    return int(datetime(2026, 1, 5, hour, minute, tzinfo=timezone.utc).timestamp())


def quote_body():
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": "SOXL", "currency": "USD", "exchangeTimezoneName": "America/New_York",
                 "regularMarketPrice": 120.001, "regularMarketTime": timestamp(20, 59),
                 "currentTradingPeriod": {
                     "regular": {"start": timestamp(14, 30), "end": timestamp(21)},
                     "post": {"start": timestamp(21), "end": timestamp(23)}}},
        "timestamp": [timestamp(20, 58), timestamp(21, 5), timestamp(21, 6)],
        "indicators": {"quote": [{"close": [120.0, 119.8765, None]}]},
    }]}}


NOW = datetime(2026, 1, 5, 22, tzinfo=timezone.utc)


def test_quote_uses_latest_valid_extended_hours_price():
    quote = fetch_quote("soxl", fetcher=lambda url: json.dumps(quote_body()).encode(), now=NOW)
    assert quote["symbol"] == "SOXL"
    assert quote["price"] == 119.8765
    assert quote["as_of"] == "2026-01-05T21:05:00+00:00"
    assert quote["session"] == "post"
    assert quote["currency"] == "USD"
    assert quote["fetched_at"] == NOW.isoformat()


def test_quote_prefers_newer_regular_trade_and_keeps_precision():
    body = quote_body()
    body["chart"]["result"][0]["timestamp"] = [timestamp(20, 58)]
    quote = fetch_quote("SOXL", fetcher=lambda url: json.dumps(body).encode(), now=NOW)
    assert quote["price"] == 120.001
    assert quote["as_of"] == "2026-01-05T20:59:00+00:00"
    assert quote["session"] == "regular"


def test_regular_closing_trade_is_not_labeled_as_after_hours():
    body = quote_body()
    data = body["chart"]["result"][0]
    data["meta"]["regularMarketTime"] = timestamp(21)
    data["timestamp"] = [timestamp(20, 58)]
    quote = fetch_quote("SOXL", fetcher=lambda url: json.dumps(body).encode(), now=NOW)
    assert quote["as_of"] == "2026-01-05T21:00:00+00:00"
    assert quote["session"] == "regular"


def test_quote_retries_provider_and_returns_clear_failure():
    calls = []

    def fetch(url):
        calls.append(url)
        if "query1." in url:
            raise HTTPError(url, 429, "rate limited", {}, None)
        return json.dumps(quote_body()).encode()

    assert fetch_quote("SOXL", fetcher=fetch, now=NOW)["price"] == 119.8765
    assert len(calls) == 2
    assert all("includePrePost=true" in url for url in calls)
    with pytest.raises(ValueError, match="최신 가격 조회 실패"):
        fetch_quote("SOXL", fetcher=lambda url: b"{}", now=NOW)


@pytest.mark.parametrize("field,value", [("symbol", "QLD"), ("currency", ""),
                                        ("regularMarketPrice", float("nan"))])
def test_invalid_quote_is_not_displayed_as_a_price(field, value):
    body = quote_body()
    data = body["chart"]["result"][0]
    data["meta"][field] = value
    data["timestamp"] = []
    with pytest.raises(ValueError):
        fetch_quote("SOXL", fetcher=lambda url: json.dumps(body).encode(), now=NOW)


def test_quote_endpoint_preserves_ledger_and_price_snapshots(tmp_path, monkeypatch):
    monkeypatch.setattr("app.quotes._fetch", lambda url: json.dumps(quote_body()).encode())
    client = TestClient(create_app(tmp_path / "quote.db"), base_url="http://localhost",
                        headers={"x-vr-request": "1"})
    account = client.post("/api/portfolios", json={"name": "시세 검증", "symbol": "SOXL",
                                                 "start": "2026-01-02", "price": 100}).json()
    response = client.get("/api/quotes/SOXL")
    assert response.status_code == 200
    assert response.json()["price"] == 119.8765
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/prices").json() == []
    assert client.get(f"/api/portfolios/{account['id']}").json() == account
    assert client.get("/api/quotes/INVALID!").status_code == 422
