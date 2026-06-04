from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_compatible_schema()


def _ensure_compatible_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "competitors" not in inspector.get_table_names():
        return
    competitor_columns = {column["name"] for column in inspector.get_columns("competitors")}
    with engine.begin() as connection:
        if "region" not in competitor_columns:
            connection.execute(text("ALTER TABLE competitors ADD COLUMN region VARCHAR"))
        if "relationship_type" not in competitor_columns:
            connection.execute(text("ALTER TABLE competitors ADD COLUMN relationship_type VARCHAR NOT NULL DEFAULT 'direct'"))
        if "relationship_reason" not in competitor_columns:
            connection.execute(text("ALTER TABLE competitors ADD COLUMN relationship_reason TEXT"))
        if "overlap_dimensions_json" not in competitor_columns:
            connection.execute(text("ALTER TABLE competitors ADD COLUMN overlap_dimensions_json TEXT"))
