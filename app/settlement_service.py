"""
Where the actual ledger update happens. Wrapped in a DB transaction so
either BOTH the debit and credit happen, or neither does.

Account.version gives us optimistic locking — if two threads somehow get
past idempotency and both try to debit the same account, the second one's
commit will raise StaleDataError rather than corrupting the balance. (In a
demo the idempotency layer should always catch this first, but defense in
depth.)
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.models import Account, Transaction, TransactionStatus
from app.schemas import PaymentInstruction

log = logging.getLogger("upimesh.settlement")


class SettlementService:
    def settle(
        self,
        db: Session,
        instruction: PaymentInstruction,
        packet_hash: str,
        bridge_node_id: str,
        hop_count: int,
    ) -> Transaction:
        sender = db.get(Account, instruction.sender_vpa)
        if sender is None:
            raise ValueError(f"Unknown sender VPA: {instruction.sender_vpa}")

        receiver = db.get(Account, instruction.receiver_vpa)
        if receiver is None:
            raise ValueError(f"Unknown receiver VPA: {instruction.receiver_vpa}")

        amount = Decimal(str(instruction.amount))
        if amount <= 0:
            raise ValueError("Amount must be positive")

        if sender.balance < amount:
            log.warning(
                "Insufficient balance: %s has ₹%s, tried to send ₹%s",
                sender.vpa, sender.balance, amount,
            )
            return self._record_rejected(db, instruction, packet_hash, bridge_node_id, hop_count)

        sender.balance -= amount
        receiver.balance += amount

        tx = Transaction(
            packet_hash=packet_hash,
            sender_vpa=instruction.sender_vpa,
            receiver_vpa=instruction.receiver_vpa,
            amount=amount,
            signed_at=datetime.fromtimestamp(instruction.signed_at / 1000, tz=timezone.utc),
            settled_at=datetime.now(timezone.utc),
            bridge_node_id=bridge_node_id,
            hop_count=hop_count,
            status=TransactionStatus.SETTLED,
        )
        db.add(tx)

        try:
            db.commit()
        except StaleDataError:
            db.rollback()
            raise

        db.refresh(tx)
        log.info(
            "SETTLED ₹%s from %s to %s (packetHash=%s..., bridge=%s, hops=%s)",
            amount, sender.vpa, receiver.vpa, packet_hash[:12], bridge_node_id, hop_count,
        )
        return tx

    def _record_rejected(
        self,
        db: Session,
        instruction: PaymentInstruction,
        packet_hash: str,
        bridge_node_id: str,
        hop_count: int,
    ) -> Transaction:
        tx = Transaction(
            packet_hash=packet_hash,
            sender_vpa=instruction.sender_vpa,
            receiver_vpa=instruction.receiver_vpa,
            amount=Decimal(str(instruction.amount)),
            signed_at=datetime.fromtimestamp(instruction.signed_at / 1000, tz=timezone.utc),
            settled_at=datetime.now(timezone.utc),
            bridge_node_id=bridge_node_id,
            hop_count=hop_count,
            status=TransactionStatus.REJECTED,
        )
        db.add(tx)
        db.commit()
        db.refresh(tx)
        return tx
