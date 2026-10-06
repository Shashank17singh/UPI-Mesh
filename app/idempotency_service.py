"""
Idempotency cache service for deduplicating mesh packets.
Prevents replay attacks and redundant processing of gossip-propagated packets.
"""
import threading
import time


class IdempotencyService:
    def __init__(self, ttl_seconds: float = 86400):
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()
        self.ttl_seconds = ttl_seconds

    def claim(self, packet_hash: str) -> bool:
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
        cutoff = time.time() - self.ttl_seconds
        with self._lock:
            expired = [k for k, v in self._seen.items() if v < cutoff]
            for k in expired:
                del self._seen[k]

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()
