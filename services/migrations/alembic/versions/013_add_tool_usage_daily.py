"""Add tool_usage_daily materialized view for tool analytics dashboard.

Aggregates tool call data into daily buckets per org/tool/agent for
time-series charts, anomaly detection, and risk heatmap.

Revision ID: 013
Revises: 012
Create Date: 2026-02-20
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW tool_usage_daily AS
        SELECT
            date_trunc('day', tc.timestamp) AS bucket,
            tc.org_id,
            tc.tool_name,
            tc.agent_id,
            COUNT(*) AS call_count,
            AVG(tc.duration_ms) AS avg_duration_ms,
            AVG(CASE WHEN e.action = 'flag' THEN 1.0 ELSE 0.0 END) AS flag_rate,
            AVG(CASE WHEN e.action = 'block' THEN 1.0 ELSE 0.0 END) AS block_rate
        FROM tool_calls tc
        JOIN executions e ON tc.execution_id = e.execution_id
        GROUP BY bucket, tc.org_id, tc.tool_name, tc.agent_id
        WITH NO DATA;
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX ix_tool_usage_daily_bucket_org_tool_agent
        ON tool_usage_daily (bucket, org_id, tool_name, agent_id);
        """
    )

    op.execute(
        """
        CREATE INDEX ix_tool_usage_daily_org_bucket
        ON tool_usage_daily (org_id, bucket);
        """
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS tool_usage_daily CASCADE")
