from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # SQLite only
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.models.models import Base  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _run_migrations()


def _run_migrations() -> None:
    """Add missing columns to existing tables (no Alembic)."""
    with engine.connect() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE videos ADD COLUMN libras_scale VARCHAR(10) NOT NULL DEFAULT '25'"
            ))
            conn.commit()
        except Exception:
            pass
