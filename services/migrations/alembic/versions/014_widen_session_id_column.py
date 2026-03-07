"""Widen session_id column from VARCHAR(64) to VARCHAR(256).

Composite session IDs (e.g. prefix + nanoid + chatId) can exceed 64 chars,
causing StringDataRightTruncation errors and silent data loss in the
storage-worker pipeline.

Revision ID: 014
Revises: 013
Create Date: 2026-03-08
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "executions",
        "session_id",
        type_=sa.String(256),
        existing_type=sa.String(64),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "executions",
        "session_id",
        type_=sa.String(64),
        existing_type=sa.String(256),
        existing_nullable=True,
    )
