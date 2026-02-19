"""Add plan-based data retention enforcement.

Creates a PL/pgSQL function that deletes execution and check_result
data older than the specified retention window for a given organisation.

The function accepts explicit parameters (org ID and retention days)
rather than reading plan data from the organisations table. Plan data
now lives in Supabase, so the Python retention cron script is responsible
for querying Supabase for each org's plan, resolving the corresponding
retention period, and invoking this function once per organisation.

  enforce_plan_retention(p_org_id TEXT, p_retention_days INT)

Designed to be called by the Python retention cron script.

Revision ID: 008
Revises: 007
Create Date: 2026-02-19
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_plan_retention(
            p_org_id TEXT,
            p_retention_days INT
        )
        RETURNS void AS $$
        BEGIN
            DELETE FROM check_results cr
            USING executions e
            WHERE cr.execution_id = e.execution_id
              AND e.org_id = p_org_id
              AND cr.timestamp < NOW() - (p_retention_days || ' days')::INTERVAL;

            DELETE FROM executions
            WHERE org_id = p_org_id
              AND timestamp < NOW() - (p_retention_days || ' days')::INTERVAL;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS enforce_plan_retention(TEXT, INT);")
