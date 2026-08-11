"""Add per-session message ordinal counter to chat_sessions.

Revision ID: 20260801_0003
Revises: 20260801_0002
"""
import sqlalchemy as sa

from alembic import op

revision = "20260801_0003"
down_revision = "20260801_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("chat_sessions")}
    if "last_message_ordinal" in columns:
        # Already present (fresh installs get the full schema from 0001's
        # metadata.create_all, and existing DBs migrated before this revision).
        return
    op.add_column(
        "chat_sessions",
        sa.Column(
            "last_message_ordinal",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.execute(
        """
        UPDATE chat_sessions s
        SET s.last_message_ordinal = COALESCE(
            (SELECT MAX(m.ordinal) FROM chat_messages m WHERE m.session_id = s.id),
            0
        )
        """
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "last_message_ordinal")
