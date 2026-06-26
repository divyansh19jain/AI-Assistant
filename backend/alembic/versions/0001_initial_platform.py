"""initial platform schema (sessions, answers, pdfs, audit, forms)

Baseline migration for a fresh database. Mirrors app/db/models.py at the point the
builder platform was introduced. On an existing DB already created via
Base.metadata.create_all, run `alembic stamp 0001_initial_platform` instead of
upgrading, then apply later migrations normally.

Revision ID: 0001_initial_platform
Revises:
Create Date: 2026-06-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_platform"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "form_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("form_id", sa.String(64), nullable=False),
        sa.Column("patient_external_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("mock_mode", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "form_answers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("form_sessions.id"), nullable=False),
        sa.Column("field_key", sa.String(128), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=True),
        sa.Column("raw_answer", sa.Text(), nullable=True),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "generated_pdfs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("form_sessions.id"), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_name", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("patient_external_id_masked", sa.String(128), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The builder platform's core entity (Phase A). schema_json holds the full field
    # schema as a JSON document so the UI can edit a form as a whole.
    op.create_table(
        "forms",
        sa.Column("form_id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("version", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("output_targets", sa.String(128), nullable=True),
        sa.Column("schema_json", sa.Text(), nullable=False),
        sa.Column("prompt_json", sa.Text(), nullable=True),
        sa.Column("voice_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("forms")
    op.drop_table("audit_logs")
    op.drop_table("generated_pdfs")
    op.drop_table("form_answers")
    op.drop_table("form_sessions")
