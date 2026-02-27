"""Run plan-based data retention enforcement.

Reads plan data from Supabase (source of truth), then enforces
retention in TimescaleDB per organization.

Usage:
    python -m scripts.run_retention

    Or schedule via cron:
    0 3 * * * cd /path/to/services && python -m scripts.run_retention

Environment:
    DATABASE_URL: TimescaleDB connection string
    SUPABASE_DATABASE_URL: Supabase Postgres connection string
"""

import json
import logging
import os
import sys
import time

from sqlalchemy import create_engine, text

# When the shared package is not installed, add its source root to sys.path
# so that `from shared.plan_limits import ...` resolves to
# services/shared/shared/plan_limits.py.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
from shared.plan_limits import get_plan_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("retention")


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    supabase_url = os.environ.get("SUPABASE_DATABASE_URL")

    if not database_url:
        logger.error("DATABASE_URL environment variable is required")
        sys.exit(1)
    if not supabase_url:
        logger.error("SUPABASE_DATABASE_URL environment variable is required")
        sys.exit(1)

    tsdb_engine = create_engine(database_url, pool_pre_ping=True)
    supa_engine = create_engine(supabase_url, pool_pre_ping=True)

    logger.info("Starting plan-based data retention enforcement...")
    start = time.monotonic()

    try:
        # 1. Read all team accounts with plan data from Supabase
        with supa_engine.connect() as supa_conn:
            accounts = supa_conn.execute(
                text(
                    "SELECT slug, vex_plan, vex_plan_overrides FROM accounts "
                    "WHERE is_personal_account = false AND slug IS NOT NULL"
                )
            ).fetchall()

        # 2. For each account, resolve retention days and enforce in TimescaleDB
        with tsdb_engine.connect() as tsdb_conn:
            for row in accounts:
                slug, plan, overrides_raw = row[0], row[1] or "free", row[2]
                overrides = json.loads(overrides_raw) if isinstance(overrides_raw, str) else overrides_raw
                config = get_plan_config(plan, overrides)

                # Find org_id in TimescaleDB by account_slug
                org_row = tsdb_conn.execute(
                    text("SELECT org_id FROM organizations WHERE account_slug = :slug"),
                    {"slug": slug},
                ).fetchone()

                if org_row is None:
                    continue

                org_id = org_row[0]
                tsdb_conn.execute(
                    text("SELECT enforce_plan_retention(:org_id, :days)"),
                    {"org_id": org_id, "days": config.retention_days},
                )
                logger.info(
                    "Enforced %d-day retention for org=%s plan=%s",
                    config.retention_days,
                    org_id,
                    plan,
                )

            tsdb_conn.commit()

    except Exception:
        logger.exception("Retention enforcement failed")
        sys.exit(1)
    finally:
        tsdb_engine.dispose()
        supa_engine.dispose()

    elapsed = time.monotonic() - start
    logger.info("Retention enforcement completed in %.2f seconds", elapsed)


if __name__ == "__main__":
    main()
