"""Add two-level chunking columns to transcript_chunks.

Implements the turn-level / context-level chunking strategy (see
chunking_strategy.md). Existing rows are single-level context-style chunks,
so chunk_type defaults to CONTEXT.

Revision ID: 20260811_0004
Revises: 20260801_0003
"""
import sqlalchemy as sa

from alembic import op

revision = "20260811_0004"
down_revision = "20260801_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("transcript_chunks")}
    if "chunk_type" in columns:
        # Already present (fresh installs get the full schema from 0001's
        # metadata.create_all, and existing DBs migrated before this revision).
        return
    op.add_column(
        "transcript_chunks",
        sa.Column(
            "chunk_type",
            sa.Enum("TURN", "CONTEXT", name="chunktype"),
            nullable=False,
            server_default="CONTEXT",
        ),
    )
    op.add_column("transcript_chunks", sa.Column("turn_start", sa.Integer(), nullable=True))
    op.add_column("transcript_chunks", sa.Column("turn_end", sa.Integer(), nullable=True))
    op.add_column(
        "transcript_chunks",
        sa.Column("parent_chunk_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_chunks_parent_chunk_id_transcript_chunks",
        "transcript_chunks",
        "transcript_chunks",
        ["parent_chunk_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_chunks_meeting_type_active",
        "transcript_chunks",
        ["meeting_id", "chunk_type", "is_active"],
    )
    op.create_index(
        "ix_chunks_parent_chunk_id",
        "transcript_chunks",
        ["parent_chunk_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_parent_chunk_id", table_name="transcript_chunks")
    op.drop_index("ix_chunks_meeting_type_active", table_name="transcript_chunks")
    op.drop_constraint(
        "fk_chunks_parent_chunk_id_transcript_chunks",
        "transcript_chunks",
        type_="foreignkey",
    )
    op.drop_column("transcript_chunks", "parent_chunk_id")
    op.drop_column("transcript_chunks", "turn_end")
    op.drop_column("transcript_chunks", "turn_start")
    op.drop_column("transcript_chunks", "chunk_type")
