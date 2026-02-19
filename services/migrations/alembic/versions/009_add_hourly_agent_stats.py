"""Add hourly_agent_stats materialized view.

Creates a standard Postgres materialized view over the executions table,
grouped by org_id and agent_id per hour. Used for plan usage metering
(monthly observation counts) and dashboard analytics.

Compatible with both Neon (standard Postgres) and TimescaleDB.

Revision ID: 009
Revises: 008
Create Date: 2026-02-19
"""

from typing import Sequence, Union

from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW hourly_agent_stats AS
        SELECT
            date_trunc('hour', timestamp) AS bucket,
            org_id,
            agent_id,
            COUNT(*) AS execution_count,
            AVG(confidence) AS avg_confidence,
            COUNT(*) FILTER (WHERE action = 'pass') AS pass_count,
            COUNT(*) FILTER (WHERE action = 'flag') AS flag_count,
            COUNT(*) FILTER (WHERE action = 'block') AS block_count
        FROM executions
        GROUP BY bucket, org_id, agent_id
        WITH NO DATA;
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX ix_hourly_agent_stats_bucket_org_agent
        ON hourly_agent_stats (bucket, org_id, agent_id);
        """
    )

    op.execute(
        """
        CREATE INDEX ix_hourly_agent_stats_org_bucket
        ON hourly_agent_stats (org_id, bucket);
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP MATERIALIZED VIEW IF EXISTS hourly_agent_stats CASCADE"
    )
