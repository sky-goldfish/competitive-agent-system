from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

settings = get_settings()
connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if settings.database_url.startswith("sqlite")
    else {}
)
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
    _configure_sqlite_pragmas()
    _ensure_compatible_schema()


def _configure_sqlite_pragmas() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        connection.execute(text("PRAGMA journal_mode=WAL"))
        connection.execute(text("PRAGMA busy_timeout=30000"))


def _ensure_compatible_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "competitors" not in inspector.get_table_names():
        return
    competitor_columns = {
        column["name"] for column in inspector.get_columns("competitors")
    }
    with engine.begin() as connection:
        if "region" not in competitor_columns:
            connection.execute(
                text("ALTER TABLE competitors ADD COLUMN region VARCHAR")
            )
        if "relationship_type" not in competitor_columns:
            connection.execute(
                text(
                    "ALTER TABLE competitors ADD COLUMN relationship_type VARCHAR NOT NULL DEFAULT 'direct'"
                )
            )
        if "relationship_reason" not in competitor_columns:
            connection.execute(
                text("ALTER TABLE competitors ADD COLUMN relationship_reason TEXT")
            )
        if "overlap_dimensions_json" not in competitor_columns:
            connection.execute(
                text("ALTER TABLE competitors ADD COLUMN overlap_dimensions_json TEXT")
            )
    run_columns = {column["name"] for column in inspector.get_columns("runs")}
    with engine.begin() as connection:
        if "feedback_loop_count" not in run_columns:
            connection.execute(
                text(
                    "ALTER TABLE runs ADD COLUMN feedback_loop_count INTEGER NOT NULL DEFAULT 0"
                )
            )
        if "active_revision_id" not in run_columns:
            connection.execute(
                text("ALTER TABLE runs ADD COLUMN active_revision_id VARCHAR")
            )
    if "analyses" in inspector.get_table_names():
        analysis_columns = {
            column["name"] for column in inspector.get_columns("analyses")
        }
        with engine.begin() as connection:
            if "analysis_iteration" not in analysis_columns:
                connection.execute(
                    text(
                        "ALTER TABLE analyses ADD COLUMN analysis_iteration INTEGER NOT NULL DEFAULT 0"
                    )
                )
            if "custom_focus_analysis_json" not in analysis_columns:
                connection.execute(
                    text(
                        "ALTER TABLE analyses ADD COLUMN custom_focus_analysis_json TEXT NOT NULL DEFAULT '[]'"
                    )
                )
    if "reports" in inspector.get_table_names():
        report_columns = {column["name"] for column in inspector.get_columns("reports")}
        with engine.begin() as connection:
            needs_recreate = False
            if "iteration" not in report_columns:
                needs_recreate = True
            elif not _has_reports_unique(connection):
                needs_recreate = True

            if needs_recreate:
                _recreate_reports_table_with_unique(connection)

            report_columns = _sqlite_columns(connection, "reports")
            if "competitor_names_json" not in report_columns:
                connection.execute(
                    text("ALTER TABLE reports ADD COLUMN competitor_names_json TEXT")
                )
            if "is_qa_intermediate" not in report_columns:
                connection.execute(
                    text(
                        "ALTER TABLE reports ADD COLUMN is_qa_intermediate BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
    if "qa_results" in inspector.get_table_names():
        qa_columns = {column["name"] for column in inspector.get_columns("qa_results")}
        with engine.begin() as connection:
            if "check_phase" not in qa_columns:
                connection.execute(
                    text(
                        "ALTER TABLE qa_results ADD COLUMN check_phase VARCHAR NOT NULL DEFAULT 'full_check'"
                    )
                )
            if "dimension_scores_json" not in qa_columns:
                connection.execute(
                    text(
                        "ALTER TABLE qa_results ADD COLUMN dimension_scores_json TEXT NOT NULL DEFAULT '{}'"
                    )
                )
            if "issue_checklist_json" not in qa_columns:
                connection.execute(
                    text(
                        "ALTER TABLE qa_results ADD COLUMN issue_checklist_json TEXT NOT NULL DEFAULT '[]'"
                    )
                )
            if "retry_queries_json" not in qa_columns:
                connection.execute(
                    text(
                        "ALTER TABLE qa_results ADD COLUMN retry_queries_json TEXT NOT NULL DEFAULT '[]'"
                    )
                )
    if "sources" in inspector.get_table_names():
        source_columns = {column["name"] for column in inspector.get_columns("sources")}
        with engine.begin() as connection:
            if "reference_id" not in source_columns:
                connection.execute(
                    text("ALTER TABLE sources ADD COLUMN reference_id INTEGER")
                )
                connection.execute(
                    text(
                        "UPDATE sources SET reference_id = json_extract(metadata_json, '$.reference_id') "
                        "WHERE metadata_json IS NOT NULL AND json_extract(metadata_json, '$.reference_id') IS NOT NULL"
                    )
                )
    if "evidence_items" in inspector.get_table_names():
        evidence_columns = {
            column["name"] for column in inspector.get_columns("evidence_items")
        }
        with engine.begin() as connection:
            if "reference_id" not in evidence_columns:
                connection.execute(
                    text("ALTER TABLE evidence_items ADD COLUMN reference_id INTEGER")
                )
                connection.execute(
                    text(
                        "UPDATE evidence_items SET reference_id = ("
                        "  SELECT json_extract(s.metadata_json, '$.reference_id') "
                        "  FROM sources s WHERE s.id = evidence_items.source_id"
                        ") WHERE reference_id IS NULL"
                    )
                )
    if "knowledge_items" in inspector.get_table_names():
        knowledge_columns = {
            column["name"] for column in inspector.get_columns("knowledge_items")
        }
        with engine.begin() as connection:
            if "source_title" not in knowledge_columns:
                connection.execute(
                    text("ALTER TABLE knowledge_items ADD COLUMN source_title VARCHAR")
                )
            if "source_url" not in knowledge_columns:
                connection.execute(
                    text("ALTER TABLE knowledge_items ADD COLUMN source_url VARCHAR")
                )
            if "metadata_json" not in knowledge_columns:
                connection.execute(
                    text("ALTER TABLE knowledge_items ADD COLUMN metadata_json TEXT")
                )


def _sqlite_columns(connection, table_name: str) -> set[str]:
    return {
        row[1] for row in connection.execute(text(f"PRAGMA table_info({table_name})"))
    }


def _has_reports_unique(connection) -> bool:
    row = connection.execute(
        text("SELECT sql FROM sqlite_master WHERE type='table' AND name='reports'")
    ).fetchone()
    if not row or not row[0]:
        return False
    return "UNIQUE" in row[0].upper() and "RUN_ID" in row[0].upper()


def _recreate_reports_table_with_unique(connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS reports_new ("
            "id VARCHAR NOT NULL PRIMARY KEY, "
            "run_id VARCHAR NOT NULL REFERENCES runs(id), "
            "iteration INTEGER NOT NULL DEFAULT 0, "
            "title VARCHAR NOT NULL, "
            "markdown_content TEXT NOT NULL, "
            "summary TEXT NOT NULL DEFAULT '', "
            "competitor_names_json TEXT, "
            "is_qa_intermediate BOOLEAN NOT NULL DEFAULT 0, "
            "created_at DATETIME, "
            "updated_at DATETIME, "
            "UNIQUE(run_id, iteration)"
            ")"
        )
    )
    existing_cols = [
        row[1]
        for row in connection.execute(text("PRAGMA table_info(reports)")).fetchall()
    ]
    target_cols = [
        "id",
        "run_id",
        "iteration",
        "title",
        "markdown_content",
        "summary",
        "competitor_names_json",
        "is_qa_intermediate",
        "created_at",
        "updated_at",
    ]
    select_exprs = []
    insert_cols = []
    for col in target_cols:
        if col in existing_cols:
            select_exprs.append(f"r.{col}")
            insert_cols.append(col)
        elif col == "is_qa_intermediate":
            select_exprs.append("0")
            insert_cols.append("is_qa_intermediate")
        elif col == "competitor_names_json":
            select_exprs.append("NULL")
            insert_cols.append("competitor_names_json")
    insert_col_str = ", ".join(insert_cols)
    select_expr_str = ", ".join(select_exprs)
    connection.execute(
        text(
            f"INSERT INTO reports_new ({insert_col_str}) "
            f"SELECT {select_expr_str} FROM reports r "
            f"WHERE r.rowid IN ("
            f"  SELECT MAX(r2.rowid) FROM reports r2 GROUP BY r2.run_id, r2.iteration"
            f")"
        )
    )
    connection.execute(text("DROP TABLE reports"))
    connection.execute(text("ALTER TABLE reports_new RENAME TO reports"))
