"""
Pydantic models for the wire format: the payment instruction itself, the
encrypted mesh packet that carries it, and the small request DTOs used by
the demo endpoints.
"""

from typing import Optional
from pydantic import BaseModel, Field


class PaymentInstruction(BaseModel):
    """The actual payment instruction. After the server decrypts
    MeshPacket.ciphertext, it gets one of these.

    Critical fields for security:
      - nonce: a UUID unique to this payment. Even if everything else were
        identical for two legitimate payments (alice sends bob 100 twice),
        the nonces differ, so the resulting ciphertexts and their hashes
        also differ.
      - signed_at: lets the server reject stale packets ("freshness
        window"). Without this, an attacker who got the ciphertext could
        replay it weeks later.
      - pin_hash: in a real system the user enters a UPI PIN; we'd verify
        it against a hash held by the bank. Here we just record it for
        realism.
    """

    sender_vpa: str
    receiver_vpa: str
    amount: float
    pin_hash: str
    nonce: str          # UUID, unique per payment intent
    signed_at: int       # epoch millis, when sender signed


class MeshPacket(BaseModel):
    """The over-the-wire format. This is what hops from phone to phone via
    Bluetooth.

    Intermediate phones can read the OUTER fields (packet_id, ttl,
    created_at) because they need them for routing and dedup. They CANNOT
    read `ciphertext` — that's encrypted with the server's public key.

    NOTE on outer-field tampering: a malicious intermediate could change
    packet_id or created_at. That's why we use the ciphertext's hash (not
    packet_id) as the idempotency key on the server. The ciphertext is
    authenticated by hybrid encryption, so any tampering inside the
    encrypted blob is detected on decryption.
    """

    packet_id: str                 # UUID, used by intermediates for gossip dedup
    ttl: int = Field(ge=0)          # hops remaining; intermediates decrement it
    created_at: int                 # epoch millis, when sender created the packet
    ciphertext: str                 # base64(RSA-encrypted AES key + AES-GCM ciphertext)


class DemoSendRequest(BaseModel):
    sender_vpa: str
    receiver_vpa: str
    amount: float
    pin: str
    ttl: Optional[int] = 5
    start_device: Optional[str] = "phone-alice"
