"""Add tool_calls hypertable for relational tool call storage.

Stores individual tool calls extracted from agent step traces, enabling
tool usage analytics, loop detection queries, and per-tool performance
tracking.

Revision ID: 010
Revises: 009
Create Date: 2026-02-20
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("execution_id", sa.String(64), nullable=False),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(128), nullable=False),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("input", sa.JSON(), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )

    # Convert to TimescaleDB hypertable (no-op on standard Postgres)
    op.execute("SELECT create_hypertable('tool_calls', 'timestamp', migrate_data => true, if_not_exists => true)")

    # Indexes for analytics queries
    op.create_index(
        "ix_tool_calls_agent_tool_ts",
        "tool_calls",
        ["agent_id", "tool_name", "timestamp"],
    )
    op.create_index(
        "ix_tool_calls_org_ts",
        "tool_calls",
        ["org_id", "timestamp"],
    )
    op.create_index(
        "ix_tool_calls_execution",
        "tool_calls",
        ["execution_id"],
    )


def downgrade() -> None:
    op.drop_table("tool_calls")
