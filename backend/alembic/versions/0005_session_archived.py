"""archived flag on form_sessions

Revision ID: 0005_session_archived
Revises: 0004_approval_signature
Create Date: 2026-06-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_session_archived"
down_revision: Union[str, None] = "0004_approval_signature"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(table_name):
        return False
    return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))


def upgrade() -> None:
    if not _has_column("form_sessions", "archived"):
        op.add_column(
            "form_sessions",
            sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    if _has_column("form_sessions", "archived"):
        op.drop_column("form_sessions", "archived")
