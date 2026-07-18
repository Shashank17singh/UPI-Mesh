"""
Database setup. We use SQLite in-memory, kept alive for the whole process
via StaticPool (SQLite's normal behaviour is one DB per connection, which
would make each request see an empty database — StaticPool reuses a single
connection so the schema and data survive across requests for the life of
the process).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

DATABASE_URL = "sqlite://"  # in-memory

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency — yields one session per request and always
    closes it afterward, even if the request raised."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
