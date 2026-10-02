from fastapi.testclient import TestClient

from app.main import create_app
from app.prices import save_snapshot


def test_account_lifecycle_and_errors(tmp_path):
    client = TestClient(create_app(tmp_path / "api.db"), base_url="http://localhost",
                        headers={"x-vr-request": "1"})
    response = client.post("/api/portfolios", json={"name": "QLD 테스트", "symbol": "QLD", "capital": 15000,
                                                   "allocation": 0.5, "price": 100, "start": "2026-01-02"})
    assert response.status_code == 201
    account = response.json()
    assert account["state"]["qty"] == 74
    response = client.post(f"/api/portfolios/{account['id']}/events",
                           json={"revision": account["revision"], "date": "2026-01-03", "kind": "buy",
                                 "qty": 99999, "price": 100})
    assert response.status_code == 422
    assert client.get(f"/api/portfolios/{account['id']}").json()["events"] == []
    assert client.get("/api/portfolios/missing").status_code == 404
    assert client.post("/api/prices/sync", json={"symbol": "http://localhost", "years": 11}).status_code == 422


def test_backtest_api_same_price_different_modes(tmp_path):
    path = tmp_path / "api.db"
    rows = [{"date": day, "open": 100, "high": 100, "low": 100, "close": 100, "adj_close": 100}
            for day in ["2026-01-02", "2026-01-15", "2026-01-16", "2026-01-30"]]
    save_snapshot(path, "QLD", rows, provider="yahoo", source="fixture")
    client = TestClient(create_app(path), base_url="http://localhost", headers={"x-vr-request": "1"})
    response = client.post("/api/backtests", json={"symbols": ["QLD"], "modes": ["basic", "skilled"],
                                                  "start": "2026-01-02", "end": "2026-01-30",
                                                  "settings": {"fee": 0},
                                                  "flows": [{"date": "2026-01-16", "amount": 5000}]})
    assert response.status_code == 200
    assert len(response.json()["results"]) == 2
    for result in response.json()["results"]:
        assert result["summary"]["twr"] == 0
        assert result["summary"]["equity"] == 20000


def test_existing_holdings_contract_through_api(tmp_path):
    path = tmp_path / "api.db"
    save_snapshot(path, "QLD", [{"date": "2026-01-02", "close": 80, "adj_close": 80}],
                  provider="yahoo", source="fixture")
    client = TestClient(create_app(path), base_url="http://localhost", headers={"x-vr-request": "1"})
    response = client.post("/api/portfolios", json={"symbol": "QLD", "start": "2026-01-02", "price": 80,
                           "initialization_mode": "existing_holdings", "qty_override": 100, "pool_override": 7000})
    assert response.status_code == 201
    assert response.json()["seed"]["capital"] == 15000
    assert response.json()["seed"]["initial_fee"] == 0
    response = client.post("/api/backtests", json={"symbols": ["QLD"], "start": "2026-01-02",
                           "end": "2026-01-02", "initial_holdings": {"qty": 100, "pool": 7000}})
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["daily"][0]["trade"] is None
    assert result["summary"]["equity"] == 15000
    assert result["summary"]["twr"] == 0
