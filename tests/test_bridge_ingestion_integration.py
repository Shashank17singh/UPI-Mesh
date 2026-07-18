import time
import uuid

from app.bridge_ingestion_service import BridgeIngestionService
from app.crypto_service import HybridCryptoService, ServerKeyHolder
from app.idempotency_service import IdempotencyService
from app.schemas import MeshPacket, PaymentInstruction
from app.settlement_service import SettlementService


def _make_pipeline():
    crypto = HybridCryptoService(ServerKeyHolder())
    idempotency = IdempotencyService()
    settlement = SettlementService()
    bridge = BridgeIngestionService(crypto, idempotency, settlement, max_age_seconds=86400)
    return crypto, bridge


def _packet_for(crypto, amount=500.0, signed_at=None):
    instruction = PaymentInstruction(
        sender_vpa="alice@demo",
        receiver_vpa="bob@demo",
        amount=amount,
        pin_hash="deadbeef",
        nonce=str(uuid.uuid4()),
        signed_at=signed_at if signed_at is not None else int(time.time() * 1000),
    )
    ciphertext = crypto.encrypt(instruction)
    return MeshPacket(packet_id=str(uuid.uuid4()), ttl=5, created_at=int(time.time() * 1000), ciphertext=ciphertext)


def test_ingest_settles_a_fresh_valid_packet(db_session):
    crypto, bridge = _make_pipeline()
    packet = _packet_for(crypto, amount=500.0)

    result = bridge.ingest(db_session, packet, "phone-bridge", hop_count=2)

    assert result.outcome == "SETTLED"
    assert result.transaction_id is not None


def test_ingest_drops_exact_duplicate(db_session):
    crypto, bridge = _make_pipeline()
    packet = _packet_for(crypto, amount=500.0)

    first = bridge.ingest(db_session, packet, "phone-bridge", hop_count=1)
    second = bridge.ingest(db_session, packet, "phone-bridge-2", hop_count=3)

    assert first.outcome == "SETTLED"
    assert second.outcome == "DUPLICATE_DROPPED"


def test_ingest_rejects_stale_packet(db_session):
    crypto, bridge = _make_pipeline()
    two_days_ago_ms = int((time.time() - 2 * 86400) * 1000)
    packet = _packet_for(crypto, amount=500.0, signed_at=two_days_ago_ms)

    result = bridge.ingest(db_session, packet, "phone-bridge", hop_count=1)

    assert result.outcome == "INVALID"
    assert result.reason == "stale_packet"


def test_ingest_rejects_garbage_ciphertext(db_session):
    _, bridge = _make_pipeline()
    packet = MeshPacket(packet_id=str(uuid.uuid4()), ttl=5, created_at=int(time.time() * 1000), ciphertext="bm90LXJlYWwtY2lwaGVydGV4dA==")

    result = bridge.ingest(db_session, packet, "phone-bridge", hop_count=0)

    assert result.outcome == "INVALID"
    assert result.reason == "decryption_failed"
