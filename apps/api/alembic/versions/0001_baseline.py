"""baseline schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-23 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("aws_account_id", sa.String(length=12), nullable=False),
        sa.Column("role_arn", sa.String(length=255), nullable=True),
        sa.Column("external_id", sa.String(length=120), nullable=True),
        sa.Column("team_tag_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_accounts_aws_account_id", "accounts", ["aws_account_id"], unique=True)

    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("is_protected", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "team_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alias"),
    )
    op.create_index("ix_team_aliases_team_id", "team_aliases", ["team_id"], unique=False)
    op.create_index("ix_team_aliases_alias", "team_aliases", ["alias"], unique=True)

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("sync_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_written", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_runs_account_id", "sync_runs", ["account_id"], unique=False)

    op.create_table(
        "daily_account_costs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "day", name="uq_daily_account_costs"),
    )
    op.create_index("ix_daily_account_costs_account_id", "daily_account_costs", ["account_id"], unique=False)
    op.create_index("ix_daily_account_costs_day", "daily_account_costs", ["day"], unique=False)

    op.create_table(
        "daily_service_costs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("service_name", sa.String(length=96), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "day", "service_name", name="uq_daily_service_costs"),
    )
    op.create_index("ix_daily_service_costs_account_id", "daily_service_costs", ["account_id"], unique=False)
    op.create_index("ix_daily_service_costs_day", "daily_service_costs", ["day"], unique=False)
    op.create_index("ix_daily_service_costs_service_name", "daily_service_costs", ["service_name"], unique=False)

    op.create_table(
        "daily_team_costs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "day", "team_id", name="uq_daily_team_costs"),
    )
    op.create_index("ix_daily_team_costs_account_id", "daily_team_costs", ["account_id"], unique=False)
    op.create_index("ix_daily_team_costs_team_id", "daily_team_costs", ["team_id"], unique=False)
    op.create_index("ix_daily_team_costs_day", "daily_team_costs", ["day"], unique=False)

    op.create_table(
        "forecasts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("projected_cost_usd", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_forecasts_account_id", "forecasts", ["account_id"], unique=False)
    op.create_index("ix_forecasts_day", "forecasts", ["day"], unique=False)

    op.create_table(
        "anomalies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False),
        sa.Column("detected_on", sa.Date(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("service_name", sa.String(length=96), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("amount_delta_usd", sa.Float(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_anomalies_kind", "anomalies", ["kind"], unique=False)
    op.create_index("ix_anomalies_detected_on", "anomalies", ["detected_on"], unique=False)
    op.create_index("ix_anomalies_account_id", "anomalies", ["account_id"], unique=False)
    op.create_index("ix_anomalies_team_id", "anomalies", ["team_id"], unique=False)

    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("impact_level", sa.String(length=24), nullable=False),
        sa.Column("estimated_monthly_savings_usd", sa.Float(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("service_name", sa.String(length=96), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recommendations_account_id", "recommendations", ["account_id"], unique=False)

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_index("ix_recommendations_account_id", table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_index("ix_anomalies_team_id", table_name="anomalies")
    op.drop_index("ix_anomalies_account_id", table_name="anomalies")
    op.drop_index("ix_anomalies_detected_on", table_name="anomalies")
    op.drop_index("ix_anomalies_kind", table_name="anomalies")
    op.drop_table("anomalies")
    op.drop_index("ix_forecasts_day", table_name="forecasts")
    op.drop_index("ix_forecasts_account_id", table_name="forecasts")
    op.drop_table("forecasts")
    op.drop_index("ix_daily_team_costs_day", table_name="daily_team_costs")
    op.drop_index("ix_daily_team_costs_team_id", table_name="daily_team_costs")
    op.drop_index("ix_daily_team_costs_account_id", table_name="daily_team_costs")
    op.drop_table("daily_team_costs")
    op.drop_index("ix_daily_service_costs_service_name", table_name="daily_service_costs")
    op.drop_index("ix_daily_service_costs_day", table_name="daily_service_costs")
    op.drop_index("ix_daily_service_costs_account_id", table_name="daily_service_costs")
    op.drop_table("daily_service_costs")
    op.drop_index("ix_daily_account_costs_day", table_name="daily_account_costs")
    op.drop_index("ix_daily_account_costs_account_id", table_name="daily_account_costs")
    op.drop_table("daily_account_costs")
    op.drop_index("ix_sync_runs_account_id", table_name="sync_runs")
    op.drop_table("sync_runs")
    op.drop_index("ix_team_aliases_alias", table_name="team_aliases")
    op.drop_index("ix_team_aliases_team_id", table_name="team_aliases")
    op.drop_table("team_aliases")
    op.drop_table("teams")
    op.drop_index("ix_accounts_aws_account_id", table_name="accounts")
    op.drop_table("accounts")
