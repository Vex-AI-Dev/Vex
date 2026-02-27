"""No-op: continuous aggregate policies replaced by standard materialized view.

The original migration adjusted TimescaleDB continuous aggregate refresh
policies, but the schema now uses a standard materialized view that is
refreshed via REFRESH MATERIALIZED VIEW CONCURRENTLY.  This migration is
kept as a no-op to preserve the revision chain.

Revision ID: 002
Revises: 001
Create Date: 2026-02-11
"""

from collections.abc import Sequence
from typing import Union

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
