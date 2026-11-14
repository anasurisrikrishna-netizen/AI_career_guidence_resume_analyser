"""add case-insensitive email uniqueness

Revision ID: 7d4a0b9e2c31
Revises: f2ea451f51f3
Create Date: 2026-11-14

"""
from alembic import op
import sqlalchemy as sa


revision = "7d4a0b9e2c31"
down_revision = "f2ea451f51f3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_users_email_lower", table_name="users")
