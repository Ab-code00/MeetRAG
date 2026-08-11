"""Add per-meeting chat sessions and messages.

Revision ID: 20260801_0002
Revises: 20260718_0001
"""
import sqlalchemy as sa

from alembic import op

revision = "20260801_0002"
down_revision = "20260718_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    bind = op.get_bind()
    if inspect(bind).has_table("chat_sessions"):
        # Migration 0001 runs Base.metadata.create_all() with the CURRENT
        # models, so a fresh database already contains every table. Guard each
        # later migration so `alembic upgrade head` also works on an empty DB.
        return
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("meeting_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_chat_sessions_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_chat_sessions_user_id_users"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], name="fk_chat_sessions_meeting_id_meetings"),
        sa.PrimaryKeyConstraint("id", name="pk_chat_sessions"),
    )
    op.create_index("ix_chat_sessions_tenant_id", "chat_sessions", ["tenant_id"])
    op.create_index("ix_chat_sessions_tenant_meeting", "chat_sessions", ["tenant_id", "meeting_id"])
    op.create_index("ix_chat_sessions_tenant_user", "chat_sessions", ["tenant_id", "user_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("role", sa.Enum("USER", "ASSISTANT", name="chatrole"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations_json", sa.JSON(), nullable=True),
        sa.Column("evidence_sufficient", sa.Boolean(), nullable=True),
        sa.Column("search_query_id", sa.String(length=36), nullable=True),
        sa.Column("answer_generation_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_chat_messages_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], name="fk_chat_messages_session_id_chat_sessions"),
        sa.ForeignKeyConstraint(["search_query_id"], ["search_queries.id"], name="fk_chat_messages_search_query_id_search_queries"),
        sa.ForeignKeyConstraint(["answer_generation_id"], ["answer_generations.id"], name="fk_chat_messages_answer_generation_id_answer_generations"),
        sa.PrimaryKeyConstraint("id", name="pk_chat_messages"),
        sa.UniqueConstraint("session_id", "ordinal", name="uq_chat_message_session_ordinal"),
    )
    op.create_index("ix_chat_messages_tenant_id", "chat_messages", ["tenant_id"])
    op.create_index("ix_chat_messages_session_created", "chat_messages", ["session_id", "created_at"])
    op.create_index("ix_chat_messages_tenant_created", "chat_messages", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_tenant_created", table_name="chat_messages")
    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages")
    op.drop_index("ix_chat_messages_tenant_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_tenant_user", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_tenant_meeting", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_tenant_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
