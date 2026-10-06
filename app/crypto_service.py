"""
Cryptographic service implementing a hybrid RSA-AES encryption scheme.
Provides packet encryption and decryption to secure offline mesh transactions.
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
AES_KEY_BYTES = 32
GCM_IV_BYTES = 12
RSA_ENCRYPTED_KEY_BYTES = 256


class ServerKeyHolder:
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
        public_key = server_public_key or self.server_key.public_key
        plaintext = instruction.model_dump_json().encode()
        aes_key = AESGCM.generate_key(bit_length=AES_KEY_BYTES * 8)
        iv = os.urandom(GCM_IV_BYTES)
        aesgcm = AESGCM(aes_key)
        aes_ciphertext = aesgcm.encrypt(iv, plaintext, None)
        encrypted_aes_key = public_key.encrypt(aes_key, _OAEP_PADDING)
        packed = encrypted_aes_key + iv + aes_ciphertext
        return base64.b64encode(packed).decode()

    def decrypt(self, base64_ciphertext: str) -> PaymentInstruction:
        all_bytes = base64.b64decode(base64_ciphertext)
        min_len = RSA_ENCRYPTED_KEY_BYTES + GCM_IV_BYTES + 16
        if len(all_bytes) < min_len:
            raise ValueError("Ciphertext too short")
        encrypted_aes_key = all_bytes[:RSA_ENCRYPTED_KEY_BYTES]
        iv = all_bytes[RSA_ENCRYPTED_KEY_BYTES : RSA_ENCRYPTED_KEY_BYTES + GCM_IV_BYTES]
        aes_ciphertext = all_bytes[RSA_ENCRYPTED_KEY_BYTES + GCM_IV_BYTES :]
        aes_key = self.server_key.private_key.decrypt(encrypted_aes_key, _OAEP_PADDING)
        aesgcm = AESGCM(aes_key)
        plaintext = aesgcm.decrypt(iv, aes_ciphertext, None)
        return PaymentInstruction(**json.loads(plaintext))

    @staticmethod
    def hash_ciphertext(base64_ciphertext: str) -> str:
        return hashlib.sha256(base64_ciphertext.encode()).hexdigest()
