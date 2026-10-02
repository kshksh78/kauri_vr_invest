from fastapi.testclient import TestClient

from app.main import create_app


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
