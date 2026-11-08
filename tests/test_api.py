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


def test_settled_time_is_sent_as_utc(db_session) -> None:
    """SQLite hands datetimes back without a zone; the API must still mark
    them as UTC, or the browser reads them as local time."""
    from datetime import datetime, timezone
    from decimal import Decimal

    from app.database import get_db
    from app.models import Transaction, TransactionStatus

    settled = datetime(2026, 11, 8, 15, 19, 19, tzinfo=timezone.utc)
    db_session.add(
        Transaction(
            packet_hash="h" * 64, nonce="n", sender_vpa="alice@demo",
            receiver_vpa="bob@demo", amount=Decimal("500.00"), signed_at=settled,
            settled_at=settled, bridge_node_id="phone-bridge", hop_count=1,
            status=TransactionStatus.SETTLED,
        )
    )
    db_session.commit()
    db_session.expire_all()

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            sent = client.get("/api/transactions").json()[0]["settledAt"]
    finally:
        app.dependency_overrides.clear()

    assert datetime.fromisoformat(sent) == settled
