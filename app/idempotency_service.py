"""
In-memory idempotency cache. In production this would be Redis with
SETNX + TTL — exactly the same semantics, just distributed across
instances.

The contract:
  - claim(hash) returns True on first call, False on every call after
    that (within the TTL window)
  - the operation is atomic — even if 100 threads call claim(hash) at the
    same instant, exactly one returns True

This is what kills the "three bridges deliver simultaneously" problem.
A plain dict + threading.Lock is the process-local equivalent of Redis
SETNX — the lock makes the check-then-set atomic, so exactly one caller
ever wins the race for a given hash.
"""

import threading
import time


class IdempotencyService:
    def __init__(self, ttl_seconds: float = 86400):
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()
        self.ttl_seconds = ttl_seconds

    def claim(self, packet_hash: str) -> bool:
        """Try to claim a hash. Returns True if this caller is the first;
        False if someone else already claimed it (i.e. the packet is a
        duplicate)."""
        now = time.time()
        with self._lock:
            if packet_hash in self._seen:
                return False
            self._seen[packet_hash] = now
            return True

    def size(self) -> int:
        with self._lock:
            return len(self._seen)

    def evict_expired(self) -> None:
        """Periodically evict entries past their TTL so the map doesn't
        grow forever. Call this from a background scheduler."""
        cutoff = time.time() - self.ttl_seconds
        with self._lock:
            expired = [k for k, v in self._seen.items() if v < cutoff]
            for k in expired:
                del self._seen[k]

    def clear(self) -> None:
        """Test/demo helper."""
        with self._lock:
            self._seen.clear()
