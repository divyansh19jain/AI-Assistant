"""platform extensions for KB, skills, approvals, workflows, and snapshots

Revision ID: 0002_platform_extensions
Revises: 0001_initial_platform
Create Date: 2026-06-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_platform_extensions"
down_revision: Union[str, None] = "0001_initial_platform"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(table_name):
        return False
    cols = sa.inspect(bind).get_columns(table_name)
    return any(c["name"] == column_name for c in cols)


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(table_name):
        return False
    indexes = sa.inspect(bind).get_indexes(table_name)
    return any(i["name"] == index_name for i in indexes)


def upgrade() -> None:
    if not _has_column("form_sessions", "schema_json"):
        op.add_column("form_sessions", sa.Column("schema_json", sa.Text(), nullable=True))

    if not _has_column("forms", "workflow_json"):
        op.add_column("forms", sa.Column("workflow_json", sa.Text(), nullable=True))

    if not _has_table("kb_documents"):
        op.create_table(
            "kb_documents",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("form_id", sa.String(64), nullable=False),
            sa.Column("doc_key", sa.String(128), nullable=False),
            sa.Column("title", sa.String(256), nullable=False),
            sa.Column("source", sa.String(256), nullable=True),
            sa.Column("mime", sa.String(64), nullable=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("status", sa.String(32), nullable=True),
            sa.Column("checksum", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    if _has_table("kb_documents") and not _has_index("kb_documents", "ix_kb_documents_form_id"):
        op.create_index("ix_kb_documents_form_id", "kb_documents", ["form_id"])

    if not _has_table("kb_chunks"):
        op.create_table(
            "kb_chunks",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("kb_document_id", sa.Integer(), sa.ForeignKey("kb_documents.id"), nullable=False),
            sa.Column("form_id", sa.String(64), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=True),
            sa.Column("chunk_text", sa.Text(), nullable=False),
            sa.Column("embedding", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
    if _has_table("kb_chunks") and not _has_index("kb_chunks", "ix_kb_chunks_form_id"):
        op.create_index("ix_kb_chunks_form_id", "kb_chunks", ["form_id"])

    if not _has_table("form_skills"):
        op.create_table(
            "form_skills",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("form_id", sa.String(64), nullable=False),
            sa.Column("skill_key", sa.String(64), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=True),
            sa.Column("config_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
    if _has_table("form_skills") and not _has_index("form_skills", "ix_form_skills_form_id"):
        op.create_index("ix_form_skills_form_id", "form_skills", ["form_id"])

    if not _has_table("form_approvals"):
        op.create_table(
            "form_approvals",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("session_id", sa.String(64), sa.ForeignKey("form_sessions.id"), nullable=False),
            sa.Column("form_id", sa.String(64), nullable=False),
            sa.Column("approved_by", sa.String(128), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _has_table("workflow_runs"):
        op.create_table(
            "workflow_runs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("session_id", sa.String(64), sa.ForeignKey("form_sessions.id"), nullable=False),
            sa.Column("form_id", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _has_table("workflow_task_runs"):
        op.create_table(
            "workflow_task_runs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("workflow_run_id", sa.Integer(), sa.ForeignKey("workflow_runs.id"), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=True),
            sa.Column("task_type", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=True),
            sa.Column("output_json", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if _has_table("workflow_task_runs"):
        op.drop_table("workflow_task_runs")
    if _has_table("workflow_runs"):
        op.drop_table("workflow_runs")
    if _has_table("form_approvals"):
        op.drop_table("form_approvals")
    if _has_table("form_skills"):
        if _has_index("form_skills", "ix_form_skills_form_id"):
            op.drop_index("ix_form_skills_form_id", table_name="form_skills")
        op.drop_table("form_skills")
    if _has_table("kb_chunks"):
        if _has_index("kb_chunks", "ix_kb_chunks_form_id"):
            op.drop_index("ix_kb_chunks_form_id", table_name="kb_chunks")
        op.drop_table("kb_chunks")
    if _has_table("kb_documents"):
        if _has_index("kb_documents", "ix_kb_documents_form_id"):
            op.drop_index("ix_kb_documents_form_id", table_name="kb_documents")
        op.drop_table("kb_documents")
    if _has_column("forms", "workflow_json"):
        op.drop_column("forms", "workflow_json")
    if _has_column("form_sessions", "schema_json"):
        op.drop_column("form_sessions", "schema_json")
