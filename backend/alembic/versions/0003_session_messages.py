"""session_messages table for the conversational agent transcript

Revision ID: 0003_session_messages
Revises: 0002_platform_extensions
Create Date: 2026-06-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_session_messages"
down_revision: Union[str, None] = "0002_platform_extensions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(table_name):
        return False
    indexes = sa.inspect(bind).get_indexes(table_name)
    return any(i["name"] == index_name for i in indexes)


def upgrade() -> None:
    if not _has_table("session_messages"):
        op.create_table(
            "session_messages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("session_id", sa.String(64), sa.ForeignKey("form_sessions.id"), nullable=False),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
    # Matches the index create_all generates for the model's index=True, keeping
    # models.py, create_all, and the migration chain in parity.
    if _has_table("session_messages") and not _has_index("session_messages", "ix_session_messages_session_id"):
        op.create_index("ix_session_messages_session_id", "session_messages", ["session_id"])


def downgrade() -> None:
    if _has_table("session_messages"):
        if _has_index("session_messages", "ix_session_messages_session_id"):
            op.drop_index("ix_session_messages_session_id", table_name="session_messages")
        op.drop_table("session_messages")
