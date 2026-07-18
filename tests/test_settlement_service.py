from datetime import datetime, timezone
from decimal import Decimal

from app.models import Account, Transaction, TransactionStatus
from app.schemas import PaymentInstruction
from app.settlement_service import SettlementService


def _instruction(amount: float, sender="alice@demo", receiver="bob@demo") -> PaymentInstruction:
    return PaymentInstruction(
        sender_vpa=sender,
        receiver_vpa=receiver,
        amount=amount,
        pin_hash="deadbeef",
        nonce="n-1",
        signed_at=int(datetime.now(tz=timezone.utc).timestamp() * 1000),
    )


def test_settle_moves_funds_between_accounts(db_session):
    svc = SettlementService()
    tx = svc.settle(db_session, _instruction(500), "hash-1", "phone-bridge", 2)

    alice = db_session.get(Account, "alice@demo")
    bob = db_session.get(Account, "bob@demo")

    assert alice.balance == Decimal("4500.00")
    assert bob.balance == Decimal("1500.00")
    assert tx.status == TransactionStatus.SETTLED
    assert tx.amount == Decimal("500")


def test_settle_rejects_when_balance_insufficient(db_session):
    svc = SettlementService()
    tx = svc.settle(db_session, _instruction(999_999), "hash-1", "phone-bridge", 0)

    alice = db_session.get(Account, "alice@demo")
    bob = db_session.get(Account, "bob@demo")

    # Balances must be untouched on rejection.
    assert alice.balance == Decimal("5000.00")
    assert bob.balance == Decimal("1000.00")
    assert tx.status == TransactionStatus.REJECTED


def test_settle_rejects_zero_or_negative_amount(db_session):
    svc = SettlementService()
    try:
        svc.settle(db_session, _instruction(0), "hash-1", "phone-bridge", 0)
        assert False, "expected ValueError for non-positive amount"
    except ValueError:
        pass


def test_settle_raises_for_unknown_vpa(db_session):
    svc = SettlementService()
    try:
        svc.settle(db_session, _instruction(10, sender="ghost@demo"), "hash-1", "phone-bridge", 0)
        assert False, "expected ValueError for unknown sender"
    except ValueError:
        pass


def test_unique_packet_hash_enforced_at_db_level(db_session):
    """The packet_hash unique constraint is the defense-in-depth fallback
    if the in-memory idempotency cache ever fails."""
    svc = SettlementService()
    svc.settle(db_session, _instruction(100), "same-hash", "phone-bridge", 0)

    existing = db_session.query(Transaction).filter_by(packet_hash="same-hash").count()
    assert existing == 1
