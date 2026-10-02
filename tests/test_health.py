from fastapi.testclient import TestClient

from app.main import create_app


def test_health_and_local_boundary(tmp_path):
    client = TestClient(create_app(tmp_path / "test.sqlite3"), base_url="http://localhost")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ready"
    assert response.json()["version"]
    assert client.get("/api/health", headers={"host": "attacker.example"}).status_code == 400
    assert client.post("/api/missing", headers={"origin": "https://attacker.example"}).status_code == 403
    assert client.post("/api/missing", headers={"origin": "http://localhost", "x-vr-request": "1"}).status_code == 404
