"""
ORM models for the two tables this service owns: accounts (the simulated
ledger) and transactions (the permanent settlement record).
"""

import enum
from sqlalchemy import Column, String, Integer, Numeric, DateTime, Enum
from app.database import Base


class Account(Base):
    """Simulated bank account. In a real system this would live in the
    bank's core, not in our service. For the demo, we own the ledger."""

    __tablename__ = "accounts"

    vpa = Column(String, primary_key=True)  # Virtual Payment Address, e.g. "alice@demo"
    holder_name = Column(String, nullable=False)
    balance = Column(Numeric(19, 2), nullable=False)

    # SQLAlchemy's version_id_col gives us optimistic locking — a
    # concurrent update to a stale row raises StaleDataError instead of
    # silently corrupting the balance.
    version = Column(Integer, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version}


class TransactionStatus(str, enum.Enum):
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class Transaction(Base):
    """Permanent record of every settled transaction. Once written, never
    modified. packet_hash is the idempotency key — uniqueness is enforced
    at the DB level as a defense-in-depth fallback if the in-memory
    idempotency cache ever fails."""

    __tablename__ = "transactions"

    # Plain Integer (not BigInteger) — on SQLite, only an INTEGER PRIMARY KEY
    # is treated as an alias for the internal rowid and gets autoincrement
    # for free. A BigInteger column silently stays NULL on insert instead.
    id = Column(Integer, primary_key=True, autoincrement=True)
    packet_hash = Column(String(64), nullable=False, unique=True, index=True)
    sender_vpa = Column(String, nullable=False)
    receiver_vpa = Column(String, nullable=False)
    amount = Column(Numeric(19, 2), nullable=False)
    signed_at = Column(DateTime, nullable=False)   # when the sender originally signed it (offline)
    settled_at = Column(DateTime, nullable=False)  # when the backend actually processed it
    bridge_node_id = Column(String, nullable=False)  # which mesh node finally delivered it
    hop_count = Column(Integer, nullable=False)      # how many devices it passed through
    status = Column(Enum(TransactionStatus), nullable=False)
