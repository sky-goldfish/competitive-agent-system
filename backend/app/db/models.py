from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("run"))
    title: Mapped[str] = mapped_column(String, default="竞品分析任务")
    user_requirement: Mapped[str] = mapped_column(Text)
    requirement_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirement_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_understanding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="created")
    current_stage: Mapped[str] = mapped_column(String, default="created")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    messages: Mapped[list["Message"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    competitors: Mapped[list["Competitor"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    sources: Mapped[list["Source"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    evidence_items: Mapped[list["Evidence"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    analyses: Mapped[list["Analysis"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    traces: Mapped[list["AgentTrace"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    report: Mapped["Report"] = relationship(back_populates="run", cascade="all, delete-orphan", uselist=False)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("msg"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped[Run] = relationship(back_populates="messages")


class Competitor(Base):
    __tablename__ = "competitors"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("comp"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    name: Mapped[str] = mapped_column(String)
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String, default="unknown")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    discovery_source: Mapped[str] = mapped_column(String, default="mock")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    run: Mapped[Run] = relationship(back_populates="competitors")
    sources: Mapped[list["Source"]] = relationship(back_populates="competitor", cascade="all, delete-orphan")
    analyses: Mapped[list["Analysis"]] = relationship(back_populates="competitor", cascade="all, delete-orphan")


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("src"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    competitor_id: Mapped[str | None] = mapped_column(ForeignKey("competitors.id"), nullable=True)
    title: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    snippet: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String, default="search_result")
    provider: Mapped[str] = mapped_column(String, default="mock")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[Run] = relationship(back_populates="sources")
    competitor: Mapped[Competitor | None] = relationship(back_populates="sources")
    evidence_items: Mapped[list["Evidence"]] = relationship(back_populates="source", cascade="all, delete-orphan")


class Evidence(Base):
    __tablename__ = "evidence_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("ev"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    related_product: Mapped[str] = mapped_column(String)
    related_dimension: Mapped[str] = mapped_column(String)
    quote: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)

    run: Mapped[Run] = relationship(back_populates="evidence_items")
    source: Mapped[Source] = relationship(back_populates="evidence_items")


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("ana"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    competitor_id: Mapped[str] = mapped_column(ForeignKey("competitors.id"))
    positioning: Mapped[str] = mapped_column(Text, default="")
    target_users: Mapped[str] = mapped_column(Text, default="[]")
    core_features_json: Mapped[str] = mapped_column(Text, default="[]")
    pricing_summary: Mapped[str] = mapped_column(Text, default="")
    strengths_json: Mapped[str] = mapped_column(Text, default="[]")
    weaknesses_json: Mapped[str] = mapped_column(Text, default="[]")
    opportunities_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped[Run] = relationship(back_populates="analyses")
    competitor: Mapped[Competitor] = relationship(back_populates="analyses")


class AgentTrace(Base):
    __tablename__ = "agent_traces"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("trace"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    stage: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped[Run] = relationship(back_populates="traces")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("rep"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), unique=True)
    title: Mapped[str] = mapped_column(String)
    markdown_content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    run: Mapped[Run] = relationship(back_populates="report")
