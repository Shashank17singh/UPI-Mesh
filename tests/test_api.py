from fastapi.testclient import TestClient

from app.main import app


def test_markup_in_a_bridge_id_is_refused() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/bridge/ingest",
            headers={"X-Bridge-Node-Id": "<img src=x onerror=alert(1)>"},
            json={"packet_id": "p", "ttl": 1, "created_at": 0, "ciphertext": "AAAA"},
        )

    assert response.status_code == 422


def test_a_normal_bridge_id_reaches_ingestion() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/bridge/ingest",
            headers={"X-Bridge-Node-Id": "phone-bridge"},
            json={"packet_id": "p", "ttl": 1, "created_at": 0, "ciphertext": "!"},
        )

    assert response.status_code == 200
    assert response.json()["reason"] == "malformed_ciphertext"
