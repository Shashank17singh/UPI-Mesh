import pytest

from app.crypto_service import HybridCryptoService, ServerKeyHolder
from app.schemas import PaymentInstruction


@pytest.fixture()
def crypto():
    return HybridCryptoService(ServerKeyHolder())


def _sample_instruction() -> PaymentInstruction:
    return PaymentInstruction(
        sender_vpa="alice@demo",
        receiver_vpa="bob@demo",
        amount=500.0,
        pin_hash="deadbeef",
        nonce="test-nonce-1",
        signed_at=1_700_000_000_000,
    )


def test_encrypt_decrypt_round_trip(crypto):
    instruction = _sample_instruction()
    ciphertext = crypto.encrypt(instruction)
    decrypted = crypto.decrypt(ciphertext)

    assert decrypted.sender_vpa == instruction.sender_vpa
    assert decrypted.receiver_vpa == instruction.receiver_vpa
    assert decrypted.amount == instruction.amount
    assert decrypted.nonce == instruction.nonce


def test_same_payload_encrypted_twice_has_different_ciphertext(crypto):
    """Fresh IV + fresh AES key per call means identical plaintext should
    never produce identical ciphertext — this is what makes the
    ciphertext hash a safe idempotency key."""
    instruction = _sample_instruction()
    c1 = crypto.encrypt(instruction)
    c2 = crypto.encrypt(instruction)
    assert c1 != c2


def test_tampered_ciphertext_fails_to_decrypt(crypto):
    ciphertext = crypto.encrypt(_sample_instruction())
    tampered = ciphertext[:-4] + ("AAAA" if ciphertext[-4:] != "AAAA" else "BBBB")
    with pytest.raises(Exception):
        crypto.decrypt(tampered)


def test_hash_ciphertext_is_deterministic(crypto):
    ciphertext = crypto.encrypt(_sample_instruction())
    assert crypto.hash_ciphertext(ciphertext) == crypto.hash_ciphertext(ciphertext)


def test_hash_ciphertext_differs_for_different_input(crypto):
    c1 = crypto.encrypt(_sample_instruction())
    c2 = crypto.encrypt(_sample_instruction())
    assert crypto.hash_ciphertext(c1) != crypto.hash_ciphertext(c2)
