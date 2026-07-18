import time

from app.idempotency_service import IdempotencyService


def test_first_claim_succeeds():
    svc = IdempotencyService()
    assert svc.claim("hash-1") is True


def test_duplicate_claim_fails():
    svc = IdempotencyService()
    svc.claim("hash-1")
    assert svc.claim("hash-1") is False


def test_different_hashes_both_claim():
    svc = IdempotencyService()
    assert svc.claim("hash-1") is True
    assert svc.claim("hash-2") is True


def test_size_reflects_claims():
    svc = IdempotencyService()
    svc.claim("hash-1")
    svc.claim("hash-2")
    svc.claim("hash-1")  # duplicate, shouldn't grow size
    assert svc.size() == 2


def test_clear_resets_cache():
    svc = IdempotencyService()
    svc.claim("hash-1")
    svc.clear()
    assert svc.size() == 0
    assert svc.claim("hash-1") is True


def test_evict_expired_removes_old_entries():
    svc = IdempotencyService(ttl_seconds=0.05)
    svc.claim("hash-1")
    time.sleep(0.1)
    svc.evict_expired()
    assert svc.size() == 0
    assert svc.claim("hash-1") is True
