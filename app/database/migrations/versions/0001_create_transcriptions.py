"""Create transcriptions table and indexes.

Revision ID: 0001_create_transcriptions
Revises: 
Create Date: 2026-11-25 15:00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_create_transcriptions"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transcriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("transcription_text", sa.Text(), nullable=False),
        sa.Column("detected_language", sa.String(length=32), nullable=True),
        sa.Column(
            "script_mix",
            sa.String(length=16),
            server_default="other",
            nullable=False,
        ),
        sa.Column("audio_filename", sa.String(length=255), nullable=True),
        sa.Column("audio_format", sa.String(length=32), nullable=True),
        sa.Column("audio_duration", sa.Float(), nullable=True),
        sa.Column(
            "transcription_status",
            sa.String(length=32),
            server_default="completed",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_index(
        "ix_transcriptions_created_at", "transcriptions", ["created_at"], unique=False
    )
    op.create_index(
        "ix_transcriptions_script_mix", "transcriptions", ["script_mix"], unique=False
    )
    op.create_index(
        "ix_transcriptions_session_id", "transcriptions", ["session_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_transcriptions_session_id", table_name="transcriptions")
    op.drop_index("ix_transcriptions_script_mix", table_name="transcriptions")
    op.drop_index("ix_transcriptions_created_at", table_name="transcriptions")
    op.drop_table("transcriptions")
