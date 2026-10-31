import time
import uuid
from decimal import Decimal

import pytest

from app.bridge_ingestion_service import BridgeIngestionService
from app.crypto_service import HybridCryptoService, ServerKeyHolder
from app.idempotency_service import IdempotencyService
from app.models import Account
from app.schemas import MeshPacket, PaymentInstruction
from app.settlement_service import SettlementService


def _make_pipeline():
    crypto = HybridCryptoService(ServerKeyHolder())
    idempotency = IdempotencyService()
    settlement = SettlementService()
    bridge = BridgeIngestionService(
        crypto, idempotency, settlement, max_age_seconds=86400
    )
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
    return MeshPacket(
        packet_id=str(uuid.uuid4()),
        ttl=5,
        created_at=int(time.time() * 1000),
        ciphertext=ciphertext,
    )


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
    packet = MeshPacket(
        packet_id=str(uuid.uuid4()),
        ttl=5,
        created_at=int(time.time() * 1000),
        ciphertext="bm90LXJlYWwtY2lwaGVydGV4dA==",
    )
    result = bridge.ingest(db_session, packet, "phone-bridge", hop_count=0)
    assert result.outcome == "INVALID"
    assert result.reason == "decryption_failed"


def _balances(db_session):
    db_session.expire_all()
    return (
        db_session.get(Account, "alice@demo").balance,
        db_session.get(Account, "bob@demo").balance,
    )


@pytest.mark.parametrize(
    "respell",
    [
        lambda text: text + "\n",
        lambda text: text[:8] + " " + text[8:],
        lambda text: text[:8] + "!" + text[8:],
    ],
)
def test_a_relay_cannot_replay_a_payment_by_respelling_it(db_session, respell):
    crypto, bridge = _make_pipeline()
    packet = _packet_for(crypto, amount=500.0)
    assert bridge.ingest(db_session, packet, "phone-bridge", 1).outcome == "SETTLED"

    replay = packet.model_copy(update={"ciphertext": respell(packet.ciphertext)})
    result = bridge.ingest(db_session, replay, "evil-relay", 1)

    assert result.outcome == "INVALID"
    assert result.reason == "malformed_ciphertext"
    assert _balances(db_session) == (Decimal("4500.00"), Decimal("1500.00"))


def test_a_cleared_cache_does_not_allow_a_replay(db_session):
    crypto, bridge = _make_pipeline()
    packet = _packet_for(crypto, amount=500.0)
    bridge.ingest(db_session, packet, "phone-bridge", 1)

    bridge.idempotency.clear()
    result = bridge.ingest(db_session, packet, "phone-bridge", 1)

    assert result.outcome == "DUPLICATE_DROPPED"
    assert _balances(db_session) == (Decimal("4500.00"), Decimal("1500.00"))


def test_a_payment_nonce_settles_only_once(db_session):
    crypto, bridge = _make_pipeline()
    instruction = PaymentInstruction(
        sender_vpa="alice@demo",
        receiver_vpa="bob@demo",
        amount=500.0,
        pin_hash="deadbeef",
        nonce=str(uuid.uuid4()),
        signed_at=int(time.time() * 1000),
    )

    def packet():
        return MeshPacket(
            packet_id=str(uuid.uuid4()),
            ttl=5,
            created_at=int(time.time() * 1000),
            ciphertext=crypto.encrypt(instruction),
        )

    assert bridge.ingest(db_session, packet(), "phone-bridge", 1).outcome == "SETTLED"
    result = bridge.ingest(db_session, packet(), "phone-bridge", 1)

    assert result.outcome == "DUPLICATE_DROPPED"
    assert _balances(db_session) == (Decimal("4500.00"), Decimal("1500.00"))
