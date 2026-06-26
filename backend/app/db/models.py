from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FormSession(Base):
    __tablename__ = "form_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    form_id: Mapped[str] = mapped_column(String(64), nullable=False)
    patient_external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    mock_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    answers: Mapped[list["FormAnswer"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    pdfs: Mapped[list["GeneratedPdf"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class FormAnswer(Base):
    __tablename__ = "form_answers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("form_sessions.id"), nullable=False)
    field_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="user")
    confidence: Mapped[float] = mapped_column(default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    session: Mapped["FormSession"] = relationship(back_populates="answers")


class GeneratedPdf(Base):
    __tablename__ = "generated_pdfs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("form_sessions.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped["FormSession"] = relationship(back_populates="pdfs")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    patient_external_id_masked: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KbDocument(Base):
    """A per-form knowledgebase document (PHI-free guidance the AI uses to help).

    The extracted ``text`` is chunked + embedded into :class:`KbChunk` for retrieval.
    Embeddings are stored as JSON text (cross-DB; cosine similarity computed in Python)
    so no pgvector extension is required — see app/ai/kb.py.

    🔒 No PHI: KB documents are general, form-level guidance only.
    """

    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    form_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    doc_key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[str | None] = mapped_column(String(256), nullable=True)
    mime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|embedded|failed
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    chunks: Mapped[list["KbChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class KbChunk(Base):
    """A chunk of a KB document with its embedding (JSON-encoded vector)."""

    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kb_document_id: Mapped[int] = mapped_column(ForeignKey("kb_documents.id"), nullable=False)
    form_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(default=0)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list[float]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped["KbDocument"] = relationship(back_populates="chunks")


class FormSkill(Base):
    """Attaches a built-in skill (reusable AI capability) to a form.

    The capability *catalog* is code (app/skills/registry.py BUILTINS); this row just
    records that a form uses ``skill_key`` (plus optional config). 🔒 No PHI.
    """

    __tablename__ = "form_skills"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    form_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    skill_key: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Form(Base):
    """DB-authoritative record for a form (the builder platform's core entity).

    The entire field schema is stored as a JSON **document** in ``schema_json`` so
    the builder UI can edit a form as a whole and the form engine
    (``app/forms/*``) can keep consuming a plain schema dict, unchanged. Prompts and
    voice config travel alongside as JSON. Forms are **seeded from bundled
    filesystem packs** on first boot (see ``app/forms/seed.py``); thereafter the DB
    is the source of truth and the filesystem packs are only an import/export/seed
    format.

    Columns are deliberately cross-database (Text-encoded JSON, comma-joined lists)
    so the same models work on Postgres (prod) and in-memory SQLite (tests).

    🔒 No PHI: a form definition is static, form-level metadata only — never patient
    data. Patient answers live in ``form_answers``, never here.
    """

    __tablename__ = "forms"

    # The stable form identifier used everywhere (e.g. "ODM_07216").
    form_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0")
    # Lifecycle: draft (editing) | published (usable in the patient flow) | archived.
    status: Mapped[str] = mapped_column(String(32), default="published")
    # Comma-separated completion targets, e.g. "pdf" or "pdf,web".
    output_targets: Mapped[str] = mapped_column(String(128), default="pdf")
    # The full field schema as a JSON string (sections -> fields, validation,
    # depends_on, sensitive flags, and the folded-in "prefill" block).
    schema_json: Mapped[str] = mapped_column(Text, nullable=False)
    # Per-form prompt pack (system persona + per-field overrides) as JSON. Optional.
    prompt_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-form voice config (voice_id, persona, stt_vocabulary) as JSON. Optional.
    voice_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
