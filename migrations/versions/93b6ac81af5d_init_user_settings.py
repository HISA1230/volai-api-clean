"""init user_settings (constraints & indexes only; non-destructive)

Revision ID: 93b6ac81af5d
Revises: 
Create Date: 2025-09-11 21:02:19.709618
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "93b6ac81af5d"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add/ensure constraint & indexes for user_settings (idempotent)."""
    # CHECK constraint: owner <> '??'  （PostgresはIF NOT EXISTS不可のためDOブロックで回避）
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'owner_not_placeholder'
                  AND conrelid = 'user_settings'::regclass
            ) THEN
                ALTER TABLE user_settings
                ADD CONSTRAINT owner_not_placeholder
                CHECK (btrim(owner) <> '??');
            END IF;
        END $$;
        """
    )

    # Indexes（既にあってもOK）
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_settings_email ON user_settings (email);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_settings_owner ON user_settings (owner);"
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_user_settings_email_ts
        ON user_settings (email, COALESCE(updated_at, created_at) DESC, id DESC);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_user_settings_owner_email_ts
        ON user_settings (owner, email, COALESCE(updated_at, created_at) DESC, id DESC);
        """
    )


def downgrade() -> None:
    """Revert only what we add in upgrade()."""
    op.execute("DROP INDEX IF EXISTS ix_user_settings_owner_email_ts;")
    op.execute("DROP INDEX IF EXISTS ix_user_settings_email_ts;")
    op.execute("DROP INDEX IF EXISTS ix_user_settings_owner;")
    op.execute("DROP INDEX IF EXISTS ix_user_settings_email;")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'owner_not_placeholder'
                  AND conrelid = 'user_settings'::regclass
            ) THEN
                ALTER TABLE user_settings
                DROP CONSTRAINT owner_not_placeholder;
            END IF;
        END $$;
        """
    )