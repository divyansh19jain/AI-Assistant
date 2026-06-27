"""e-signature + consent columns on form_approvals

Revision ID: 0004_approval_signature
Revises: 0003_session_messages
Create Date: 2026-06-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_approval_signature"
down_revision: Union[str, None] = "0003_session_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(table_name):
        return False
    return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))


def upgrade() -> None:
    if not _has_column("form_approvals", "signature"):
        op.add_column("form_approvals", sa.Column("signature", sa.String(256), nullable=True))
    if not _has_column("form_approvals", "consent_json"):
        op.add_column("form_approvals", sa.Column("consent_json", sa.Text(), nullable=True))


def downgrade() -> None:
    if _has_column("form_approvals", "consent_json"):
        op.drop_column("form_approvals", "consent_json")
    if _has_column("form_approvals", "signature"):
        op.drop_column("form_approvals", "signature")
