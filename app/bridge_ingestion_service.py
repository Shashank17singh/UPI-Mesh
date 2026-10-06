"""
Bridge ingestion service for UPI-Mesh.
Handles ingestion of mesh packets from internet-connected bridge nodes, performing idempotency checks, decryption, and triggering settlement.
"""
import logging
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.crypto_service import HybridCryptoService
from app.idempotency_service import IdempotencyService
from app.schemas import MeshPacket
from app.settlement_service import SettlementService

log = logging.getLogger("upimesh.bridge")


@dataclass
class IngestResult:
    outcome: str
    packet_hash: str
    reason: str | None = None
    transaction_id: int | None = None

    @staticmethod
    def settled(packet_hash: str, transaction_id: int) -> "IngestResult":
        return IngestResult("SETTLED", packet_hash, None, transaction_id)

    @staticmethod
    def duplicate(packet_hash: str) -> "IngestResult":
        return IngestResult("DUPLICATE_DROPPED", packet_hash, None, None)

    @staticmethod
    def invalid(packet_hash: str, reason: str) -> "IngestResult":
        return IngestResult("INVALID", packet_hash, reason, None)


class BridgeIngestionService:
    def __init__(
        self,
        crypto: HybridCryptoService,
        idempotency: IdempotencyService,
        settlement: SettlementService,
        max_age_seconds: float = 86400,
    ):
        self.crypto = crypto
        self.idempotency = idempotency
        self.settlement = settlement
        self.max_age_seconds = max_age_seconds

    def ingest(
        self, db: Session, packet: MeshPacket, bridge_node_id: str, hop_count: int
    ) -> IngestResult:
        """
        Processes a mesh packet via the bridge. Enforces idempotency to prevent 
        double-spending of retransmitted packets, decrypts the instruction, validates
        time-to-live constraints, and delegates to the settlement ledger.
        """
        try:
            packet_hash = self.crypto.hash_ciphertext(packet.ciphertext)

            if not self.idempotency.claim(packet_hash):
                log.info(
                    "DUPLICATE packet %s... from bridge %s - dropped",
                    packet_hash[:12],
                    bridge_node_id,
                )
                return IngestResult.duplicate(packet_hash)

            try:
                instruction = self.crypto.decrypt(packet.ciphertext)
            except Exception as e:
                log.warning(
                    "Decryption failed for packet %s...: %s", packet_hash[:12], e
                )
                return IngestResult.invalid(packet_hash, "decryption_failed")

            age_seconds = (time.time() * 1000 - instruction.signed_at) / 1000
            if age_seconds > self.max_age_seconds:
                log.warning(
                    "Packet %s... too old (%ss), rejected",
                    packet_hash[:12],
                    age_seconds,
                )
                return IngestResult.invalid(packet_hash, "stale_packet")
            if age_seconds < -300:
                return IngestResult.invalid(packet_hash, "future_dated")

            tx = self.settlement.settle(
                db, instruction, packet_hash, bridge_node_id, hop_count
            )
            return IngestResult.settled(packet_hash, tx.id)
        except Exception as e:
            log.error("Ingestion error: %s", e, exc_info=True)
            return IngestResult.invalid("?", f"internal_error: {e}")
