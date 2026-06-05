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
    run_columns = {column["name"] for column in inspector.get_columns("runs")}
    with engine.begin() as connection:
        if "feedback_loop_count" not in run_columns:
            connection.execute(text("ALTER TABLE runs ADD COLUMN feedback_loop_count INTEGER NOT NULL DEFAULT 0"))
    if "analyses" in inspector.get_table_names():
        analysis_columns = {column["name"] for column in inspector.get_columns("analyses")}
        with engine.begin() as connection:
            if "analysis_iteration" not in analysis_columns:
                connection.execute(text("ALTER TABLE analyses ADD COLUMN analysis_iteration INTEGER NOT NULL DEFAULT 0"))
    if "reports" in inspector.get_table_names():
        report_columns = {column["name"] for column in inspector.get_columns("reports")}
        with engine.begin() as connection:
            if "iteration" not in report_columns:
                _recreate_reports_table_without_unique(connection)
            else:
                _drop_reports_unique_if_exists(connection)
    if "qa_results" in inspector.get_table_names():
        qa_columns = {column["name"] for column in inspector.get_columns("qa_results")}
        with engine.begin() as connection:
            if "check_phase" not in qa_columns:
                connection.execute(text("ALTER TABLE qa_results ADD COLUMN check_phase VARCHAR NOT NULL DEFAULT 'full_check'"))
            if "dimension_scores_json" not in qa_columns:
                connection.execute(text("ALTER TABLE qa_results ADD COLUMN dimension_scores_json TEXT NOT NULL DEFAULT '{}'"))
            if "issue_checklist_json" not in qa_columns:
                connection.execute(text("ALTER TABLE qa_results ADD COLUMN issue_checklist_json TEXT NOT NULL DEFAULT '[]'"))
            if "retry_queries_json" not in qa_columns:
                connection.execute(text("ALTER TABLE qa_results ADD COLUMN retry_queries_json TEXT NOT NULL DEFAULT '[]'"))


def _has_reports_unique(connection) -> bool:
    row = connection.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='reports'")).fetchone()
    if not row or not row[0]:
        return False
    return "UNIQUE" in row[0].upper() and "RUN_ID" in row[0].upper()


def _drop_reports_unique_if_exists(connection) -> None:
    if not _has_reports_unique(connection):
        return
    _recreate_reports_table_without_unique(connection)


def _recreate_reports_table_without_unique(connection) -> None:
    connection.execute(text("CREATE TABLE IF NOT EXISTS reports_new ("
        "id VARCHAR NOT NULL PRIMARY KEY, "
        "run_id VARCHAR NOT NULL REFERENCES runs(id), "
        "iteration INTEGER NOT NULL DEFAULT 0, "
        "title VARCHAR NOT NULL, "
        "markdown_content TEXT NOT NULL, "
        "summary TEXT NOT NULL DEFAULT '', "
        "created_at DATETIME, "
        "updated_at DATETIME"
    ")"))
    connection.execute(text("INSERT INTO reports_new (id, run_id, iteration, title, markdown_content, summary, created_at, updated_at) "
        "SELECT id, run_id, COALESCE(iteration, 0), title, markdown_content, summary, created_at, updated_at FROM reports"))
    connection.execute(text("DROP TABLE reports"))
    connection.execute(text("ALTER TABLE reports_new RENAME TO reports"))
