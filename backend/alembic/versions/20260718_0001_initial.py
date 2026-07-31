"""Create the initial MeetAI system-of-record schema.

Revision ID: 20260718_0001
Revises:
"""
from alembic import op

from app.db.base import Base
from app.models import entities  # noqa: F401

revision = "20260718_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    op.execute(
        """
        CREATE TRIGGER prevent_transcripts_raw_update
        BEFORE UPDATE ON transcripts_raw FOR EACH ROW
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Raw transcripts are immutable'
        """
    )
    op.execute(
        """
        CREATE TRIGGER prevent_transcripts_raw_delete
        BEFORE DELETE ON transcripts_raw FOR EACH ROW
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Raw transcripts are immutable'
        """
    )
    op.execute(
        """
        CREATE TRIGGER prevent_segments_raw_update
        BEFORE UPDATE ON transcript_segments_raw FOR EACH ROW
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Raw transcript segments are immutable'
        """
    )
    op.execute(
        """
        CREATE TRIGGER prevent_segments_raw_delete
        BEFORE DELETE ON transcript_segments_raw FOR EACH ROW
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Raw transcript segments are immutable'
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS prevent_segments_raw_delete")
    op.execute("DROP TRIGGER IF EXISTS prevent_segments_raw_update")
    op.execute("DROP TRIGGER IF EXISTS prevent_transcripts_raw_delete")
    op.execute("DROP TRIGGER IF EXISTS prevent_transcripts_raw_update")
    Base.metadata.drop_all(bind=op.get_bind())

