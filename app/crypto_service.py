"""
Hybrid encryption — the same pattern used by TLS, PGP, Signal, etc.

Why hybrid? RSA can only encrypt small data (~245 bytes for a 2048-bit key).
Our payment instruction (JSON) might be ~300 bytes, and in real use we might
include device certificates and signatures pushing it well over.

Solution: generate a fresh AES key per packet, encrypt the JSON with
AES-256-GCM (fast + authenticated), then encrypt JUST the AES key with
RSA-OAEP.

Wire format (after base64 encoding):
    [ 256 bytes RSA-encrypted AES key ][ 12 bytes GCM IV ][ ciphertext + 16-byte tag ]

AES-GCM is authenticated encryption: any single-bit tampering with the
ciphertext causes decryption to fail with an exception. This is what makes
it safe for untrusted intermediates to hold.
"""

import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.schemas import PaymentInstruction

RSA_KEY_BITS = 2048
AES_KEY_BYTES = 32       # AES-256
GCM_IV_BYTES = 12
RSA_ENCRYPTED_KEY_BYTES = 256  # for a 2048-bit RSA key


class ServerKeyHolder:
    """Holds the server's RSA keypair.

    In production, the private key would live in an HSM (Hardware Security
    Module) or at least a KMS like AWS KMS / HashiCorp Vault. NEVER in the
    repo or source. For this demo we generate a fresh keypair on every
    startup. The public key is exposed via /api/server-key so the
    (simulated) sender devices can use it to encrypt payloads.
    """

    def __init__(self):
        self._private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=RSA_KEY_BITS
        )
        self._public_key = self._private_key.public_key()

    @property
    def private_key(self):
        return self._private_key

    @property
    def public_key(self):
        return self._public_key

    def public_key_base64(self) -> str:
        der = self._public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return base64.b64encode(der).decode()


_OAEP_PADDING = padding.OAEP(
    mgf=padding.MGF1(algorithm=hashes.SHA256()),
    algorithm=hashes.SHA256(),
    label=None,
)


class HybridCryptoService:
    def __init__(self, server_key: ServerKeyHolder):
        self.server_key = server_key

    def encrypt(self, instruction: PaymentInstruction, server_public_key=None) -> str:
        """Encrypt a payment instruction with the server's public key.
        Called by the simulated sender device."""
        public_key = server_public_key or self.server_key.public_key
        plaintext = instruction.model_dump_json().encode()

        # 1. Generate a one-time AES key for this packet.
        aes_key = AESGCM.generate_key(bit_length=AES_KEY_BYTES * 8)

        # 2. AES-GCM encrypt the payload.
        iv = os.urandom(GCM_IV_BYTES)
        aesgcm = AESGCM(aes_key)
        aes_ciphertext = aesgcm.encrypt(iv, plaintext, None)  # tag is appended automatically

        # 3. RSA-OAEP encrypt the AES key with the server's public key.
        encrypted_aes_key = public_key.encrypt(aes_key, _OAEP_PADDING)

        # 4. Pack: [encrypted AES key][IV][AES ciphertext + tag]
        packed = encrypted_aes_key + iv + aes_ciphertext
        return base64.b64encode(packed).decode()

    def decrypt(self, base64_ciphertext: str) -> PaymentInstruction:
        """Decrypt with the server's private key. If anything has been
        tampered with — wrong key, modified ciphertext, truncated input —
        this raises."""
        all_bytes = base64.b64decode(base64_ciphertext)

        min_len = RSA_ENCRYPTED_KEY_BYTES + GCM_IV_BYTES + 16  # 16-byte GCM tag
        if len(all_bytes) < min_len:
            raise ValueError("Ciphertext too short")

        encrypted_aes_key = all_bytes[:RSA_ENCRYPTED_KEY_BYTES]
        iv = all_bytes[RSA_ENCRYPTED_KEY_BYTES:RSA_ENCRYPTED_KEY_BYTES + GCM_IV_BYTES]
        aes_ciphertext = all_bytes[RSA_ENCRYPTED_KEY_BYTES + GCM_IV_BYTES:]

        # 1. RSA-decrypt the AES key.
        aes_key = self.server_key.private_key.decrypt(encrypted_aes_key, _OAEP_PADDING)

        # 2. AES-GCM decrypt + verify the tag.
        aesgcm = AESGCM(aes_key)
        plaintext = aesgcm.decrypt(iv, aes_ciphertext, None)

        return PaymentInstruction(**json.loads(plaintext))

    @staticmethod
    def hash_ciphertext(base64_ciphertext: str) -> str:
        """SHA-256 of the ciphertext. THIS is the idempotency key.

        Why ciphertext and not packet_id? Because intermediates can
        rewrite packet_id but cannot forge a valid ciphertext for a
        different payload. Two delivered copies of the same packet have
        identical ciphertexts, hence identical hashes."""
        return hashlib.sha256(base64_ciphertext.encode()).hexdigest()
