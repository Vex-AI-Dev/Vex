"""Add check_score_hourly materialized view for per-check score trends.

Aggregates avg score per check_type per agent per hour from check_results
joined with executions (for agent_id and org_id). Used by the agent detail
dashboard to render per-check score trend line charts.

Revision ID: 012
Revises: 011
Create Date: 2026-02-20
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-check score trends (agent detail page)
    op.execute(
        """
        CREATE MATERIALIZED VIEW check_score_hourly AS
        SELECT
            date_trunc('hour', cr.timestamp) AS bucket,
            e.org_id,
            e.agent_id,
            cr.check_type,
            AVG(cr.score) AS avg_score,
            COUNT(*) AS check_count,
            COUNT(*) FILTER (WHERE cr.passed = true) AS passed_count,
            COUNT(*) FILTER (WHERE cr.passed = false) AS failed_count
        FROM check_results cr
        JOIN executions e ON cr.execution_id = e.execution_id
        GROUP BY bucket, e.org_id, e.agent_id, cr.check_type
        WITH NO DATA;
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX ix_check_score_hourly_bucket_org_agent_type
        ON check_score_hourly (bucket, org_id, agent_id, check_type);
        """
    )

    op.execute(
        """
        CREATE INDEX ix_check_score_hourly_agent_bucket
        ON check_score_hourly (agent_id, bucket);
        """
    )

    # Correction effectiveness aggregate
    op.execute(
        """
        CREATE MATERIALIZED VIEW correction_stats_daily AS
        SELECT
            date_trunc('day', timestamp) AS bucket,
            org_id,
            agent_id,
            COUNT(*) FILTER (WHERE corrected = true) AS corrected_count,
            COUNT(*) FILTER (WHERE action != 'pass') AS failed_count,
            COUNT(*) AS total_count
        FROM executions
        GROUP BY bucket, org_id, agent_id
        WITH NO DATA;
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX ix_correction_stats_daily_bucket_org_agent
        ON correction_stats_daily (bucket, org_id, agent_id);
        """
    )

    op.execute(
        """
        CREATE INDEX ix_correction_stats_daily_agent_bucket
        ON correction_stats_daily (agent_id, bucket);
        """
    )

    # Failure clustering aggregate
    op.execute(
        """
        CREATE MATERIALIZED VIEW failure_patterns_daily AS
        SELECT
            date_trunc('day', cr.timestamp) AS bucket,
            e.org_id,
            e.agent_id,
            cr.check_type,
            COUNT(*) AS failure_count
        FROM check_results cr
        JOIN executions e ON cr.execution_id = e.execution_id
        WHERE cr.passed = false
        GROUP BY bucket, e.org_id, e.agent_id, cr.check_type
        WITH NO DATA;
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX ix_failure_patterns_daily_bucket_org_agent_type
        ON failure_patterns_daily (bucket, org_id, agent_id, check_type);
        """
    )

    op.execute(
        """
        CREATE INDEX ix_failure_patterns_daily_org_bucket
        ON failure_patterns_daily (org_id, bucket);
        """
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS failure_patterns_daily CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS correction_stats_daily CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS check_score_hourly CASCADE")
