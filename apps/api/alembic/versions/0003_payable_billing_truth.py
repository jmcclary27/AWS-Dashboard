"""payable billing truth layer

Revision ID: 0003_payable_billing_truth
Revises: 0002_connection_scope
Create Date: 2026-06-28 01:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_payable_billing_truth"
down_revision = "0002_connection_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("connections") as batch_op:
        batch_op.add_column(sa.Column("billing_mode", sa.String(length=32), nullable=False, server_default="payable_hybrid"))
        batch_op.add_column(sa.Column("billing_export_bucket", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("billing_export_prefix", sa.String(length=1024), nullable=True))
        batch_op.add_column(sa.Column("billing_export_region", sa.String(length=64), nullable=True))

    op.create_table(
        "daily_billing_totals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("gross_usage_usd", sa.Float(), nullable=False),
        sa.Column("credits_usd", sa.Float(), nullable=False),
        sa.Column("savings_discounts_usd", sa.Float(), nullable=False),
        sa.Column("tax_usd", sa.Float(), nullable=False),
        sa.Column("support_usd", sa.Float(), nullable=False),
        sa.Column("marketplace_usd", sa.Float(), nullable=False),
        sa.Column("refunds_usd", sa.Float(), nullable=False),
        sa.Column("other_adjustments_usd", sa.Float(), nullable=False),
        sa.Column("net_due_usd", sa.Float(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "account_id", "day", name="uq_daily_billing_totals"),
    )
    op.create_index("ix_daily_billing_totals_connection_id", "daily_billing_totals", ["connection_id"], unique=False)
    op.create_index("ix_daily_billing_totals_account_id", "daily_billing_totals", ["account_id"], unique=False)
    op.create_index("ix_daily_billing_totals_day", "daily_billing_totals", ["day"], unique=False)

    op.create_table(
        "billing_forecasts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("projected_net_due_usd", sa.Float(), nullable=False),
        sa.Column("projected_adjustments_usd", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "account_id", "day", name="uq_billing_forecasts"),
    )
    op.create_index("ix_billing_forecasts_connection_id", "billing_forecasts", ["connection_id"], unique=False)
    op.create_index("ix_billing_forecasts_account_id", "billing_forecasts", ["account_id"], unique=False)
    op.create_index("ix_billing_forecasts_day", "billing_forecasts", ["day"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_billing_forecasts_day", table_name="billing_forecasts")
    op.drop_index("ix_billing_forecasts_account_id", table_name="billing_forecasts")
    op.drop_index("ix_billing_forecasts_connection_id", table_name="billing_forecasts")
    op.drop_table("billing_forecasts")

    op.drop_index("ix_daily_billing_totals_day", table_name="daily_billing_totals")
    op.drop_index("ix_daily_billing_totals_account_id", table_name="daily_billing_totals")
    op.drop_index("ix_daily_billing_totals_connection_id", table_name="daily_billing_totals")
    op.drop_table("daily_billing_totals")

    with op.batch_alter_table("connections") as batch_op:
        batch_op.drop_column("billing_export_region")
        batch_op.drop_column("billing_export_prefix")
        batch_op.drop_column("billing_export_bucket")
        batch_op.drop_column("billing_mode")
