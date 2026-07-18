"""
Helper service that seeds demo accounts on startup and simulates the
"sender phone creates an encrypted packet" flow.
"""

import hashlib
import logging
import time
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.crypto_service import HybridCryptoService
from app.models import Account
from app.schemas import MeshPacket, PaymentInstruction

log = logging.getLogger("upimesh.demo")


class DemoService:
    def __init__(self, crypto: HybridCryptoService):
        self.crypto = crypto

    def seed_accounts(self, db: Session) -> None:
        if db.query(Account).count() == 0:
            db.add_all([
                Account(vpa="alice@demo", holder_name="Alice", balance=Decimal("5000.00")),
                Account(vpa="bob@demo", holder_name="Bob", balance=Decimal("1000.00")),
                Account(vpa="carol@demo", holder_name="Carol", balance=Decimal("2500.00")),
                Account(vpa="dave@demo", holder_name="Dave", balance=Decimal("500.00")),
            ])
            db.commit()
            log.info("Seeded 4 demo accounts")

    def create_packet(
        self, sender_vpa: str, receiver_vpa: str, amount: float, pin: str, ttl: int
    ) -> MeshPacket:
        """Simulates the sender's phone:
          1. Build a PaymentInstruction with a fresh nonce + signed_at timestamp.
          2. Encrypt with the server's public key (hybrid RSA+AES).
          3. Wrap in a MeshPacket with TTL.

        In a real Android app, this exact code (minus the server-side
        reference) would run on the phone. The phone would have already
        cached the server's public key during a previous online session.
        """
        instruction = PaymentInstruction(
            sender_vpa=sender_vpa,
            receiver_vpa=receiver_vpa,
            amount=amount,
            pin_hash=self._sha256_hex(pin),
            nonce=str(uuid.uuid4()),           # nonce — guarantees uniqueness
            signed_at=int(time.time() * 1000),  # signed_at — for freshness check
        )

        ciphertext = self.crypto.encrypt(instruction)

        return MeshPacket(
            packet_id=str(uuid.uuid4()),
            ttl=ttl,
            created_at=int(time.time() * 1000),
            ciphertext=ciphertext,
        )

    @staticmethod
    def _sha256_hex(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()
