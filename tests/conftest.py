import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Account
from decimal import Decimal


@pytest.fixture()
def db_session():
    """A fresh in-memory SQLite DB per test, seeded with the same 4 demo
    accounts the app seeds on startup."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    session.add_all([
        Account(vpa="alice@demo", holder_name="Alice", balance=Decimal("5000.00")),
        Account(vpa="bob@demo", holder_name="Bob", balance=Decimal("1000.00")),
    ])
    session.commit()

    yield session
    session.close()
