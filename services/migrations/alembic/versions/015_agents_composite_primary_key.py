"""Change agents primary key from (agent_id) to (agent_id, org_id).

The original schema used agent_id alone as the primary key, preventing
the same agent name from existing under multiple organizations. This
caused auto-provisioning to silently update the wrong org's row instead
of creating a new agent entry when a different org used the same agent_id.

Revision ID: 015
Revises: 014
Create Date: 2026-03-08
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the old single-column primary key
    op.drop_constraint("agents_pkey", "agents", type_="primary")

    # Create the composite primary key
    op.create_primary_key("agents_pkey", "agents", ["agent_id", "org_id"])


def downgrade() -> None:
    op.drop_constraint("agents_pkey", "agents", type_="primary")
    op.create_primary_key("agents_pkey", "agents", ["agent_id"])
