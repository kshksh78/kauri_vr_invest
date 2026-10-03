import json
from datetime import datetime, timezone

import pytest

from app.db import connect, init_db
from app.prices import list_symbols, read_prices, save_snapshot, sync_prices, validate_symbol


def candles():
    return [dict(date="2026-01-02", open=10, high=11, low=9, close=10, adj_close=9, volume=100)]


def test_snapshot_atomic_and_provenance(tmp_path):
    db = tmp_path / "prices.db"
    init_db(db)
    raw = save_snapshot(db, "QLD", candles(), provider="raw", source="fixture", currency="USD")
    online = save_snapshot(db, "QLD", [{**candles()[0], "adj_close": 8}], provider="yahoo", source="https://example", currency="USD")
    assert read_prices(db, "QLD")[0]["adj_close"] == 8
    assert read_prices(db, "QLD")[0]["snapshot_id"] == online
    with connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == 2
        assert con.execute("SELECT adj_close FROM price_rows WHERE snapshot_id=?", (raw,)).fetchone()[0] == 9
    with pytest.raises(ValueError):
        save_snapshot(db, "QLD", [{**candles()[0], "close": float("nan")}], provider="yahoo", source="bad")
    assert read_prices(db, "QLD")[0]["adj_close"] == 8
    assert list_symbols(db)[0]["currency"] == "USD"


def test_coherent_snapshot_never_fills_gaps_from_old_adjustment_basis(tmp_path):
    db = tmp_path / "prices.db"
    save_snapshot(db, "QLD", [*candles(), {**candles()[0], "date": "2026-01-05"}], provider="raw", source="old file")
    identifier = save_snapshot(db, "QLD", candles(), provider="yahoo", source="new adjustment basis")
    assert [row["date"] for row in read_prices(db, "QLD")] == ["2026-01-02"]
    assert len(read_prices(db, "QLD", snapshot_id=identifier)) == 1
    with pytest.raises(ValueError):
        read_prices(db, "TQQQ", snapshot_id=identifier)


@pytest.mark.parametrize("payload", [b"not json", b"{}", b'{"chart":{"result":[],"error":null}}'])
def test_invalid_fetch_preserves_snapshot_and_records_error(tmp_path, payload):
    db = tmp_path / "prices.db"
    save_snapshot(db, "QLD", candles(), provider="yahoo", source="good")
    def fetch(url):
        return payload
    with pytest.raises(ValueError):
        sync_prices(db, "QLD", fetcher=fetch)
    assert read_prices(db, "QLD")[0]["close"] == 10
    assert list_symbols(db)[0]["last_error"]


@pytest.mark.parametrize("status", [401, 403, 429])
def test_http_failure_retains_cache(tmp_path, status):
    from urllib.error import HTTPError
    db = tmp_path / "prices.db"
    save_snapshot(db, "QLD", candles(), provider="yahoo", source="good")
    def fetch(url):
        raise HTTPError(url, status, "blocked", {}, None)
    with pytest.raises(ValueError):
        sync_prices(db, "QLD", fetcher=fetch)
    assert read_prices(db, "QLD")[0]["adj_close"] == 9


def test_yahoo_exchange_day_finalization_and_currency(tmp_path):
    db = tmp_path / "prices.db"
    timestamps = [int(datetime(2026, 1, day, 14, 30, tzinfo=timezone.utc).timestamp()) for day in (2, 5)]
    payload = {"chart": {"error": None, "result": [{"meta": {"symbol": "XYZ", "currency": "CAD", "exchangeTimezoneName": "America/New_York"}, "timestamp": timestamps, "indicators": {"quote": [{"open": [10, 11], "high": [11, 12], "low": [9, 10], "close": [10, 11], "volume": [100, 200]}], "adjclose": [{"adjclose": [9, 10]}]}}]}}
    report = sync_prices(db, "XYZ", fetcher=lambda url: json.dumps(payload).encode(), now=datetime(2026, 1, 5, 18, tzinfo=timezone.utc))
    assert report["rows"] == 1
    assert report["currency"] == "CAD"
    assert read_prices(db, "XYZ")[0]["date"] == "2026-01-02"


@pytest.mark.parametrize("utc_hour,expected_dates", [(18, ["2026-01-02"]), (22, ["2026-01-02", "2026-01-05"])])
def test_current_day_requires_exchange_regular_session_end(tmp_path, utc_hour, expected_dates):
    db = tmp_path / "prices.db"
    timestamps = [int(datetime(2026, 1, day, 14, 30, tzinfo=timezone.utc).timestamp()) for day in (2, 5)]
    close_time = int(datetime(2026, 1, 5, 21, tzinfo=timezone.utc).timestamp())
    payload = {"chart": {"error": None, "result": [{"meta": {"symbol": "QLD", "currency": "USD", "exchangeTimezoneName": "America/New_York", "currentTradingPeriod": {"regular": {"end": close_time}}}, "timestamp": timestamps, "indicators": {"quote": [{"open": [10, 11], "high": [11, 12], "low": [9, 10], "close": [10, 11], "volume": [100, 200]}], "adjclose": [{"adjclose": [9, 10]}]}}]}}
    sync_prices(db, "QLD", fetcher=lambda url: json.dumps(payload).encode(), now=datetime(2026, 1, 5, utc_hour, tzinfo=timezone.utc))
    assert [row["date"] for row in read_prices(db, "QLD")] == expected_dates


def test_symbol_and_range_guards(tmp_path):
    assert validate_symbol(" brk-b ") == "BRK-B"
    for symbol in ("http://localhost", "../QLD", "QLD?x=1", "", "A" * 40):
        with pytest.raises(ValueError):
            validate_symbol(symbol)
    with pytest.raises(ValueError):
        read_prices(tmp_path / "x.db", "QLD", years=11)
    with pytest.raises(ValueError):
        sync_prices(tmp_path / "x.db", "QLD", years=0)
