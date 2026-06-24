"""connection-scoped ingestion schema

Revision ID: 0002_connection_scope
Revises: 0001_baseline
Create Date: 2026-06-23 00:10:00.000000
"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "0002_connection_scope"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("role_arn", sa.String(length=255), nullable=True),
        sa.Column("external_id", sa.String(length=120), nullable=True),
        sa.Column("billing_view_arn", sa.String(length=2048), nullable=True),
        sa.Column("team_tag_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_connections_name", "connections", ["name"], unique=True)
    op.create_index("ix_connections_kind", "connections", ["kind"], unique=False)

    now = datetime.now(timezone.utc)
    op.bulk_insert(
        sa.table(
            "connections",
            sa.column("id", sa.Integer()),
            sa.column("name", sa.String()),
            sa.column("kind", sa.String()),
            sa.column("enabled", sa.Boolean()),
            sa.column("role_arn", sa.String()),
            sa.column("external_id", sa.String()),
            sa.column("billing_view_arn", sa.String()),
            sa.column("team_tag_key", sa.String()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": 1,
                "name": "Local Demo",
                "kind": "demo",
                "enabled": True,
                "role_arn": None,
                "external_id": None,
                "billing_view_arn": None,
                "team_tag_key": "Team",
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    op.create_table(
        "connection_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("membership_source", sa.String(length=24), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "account_id", name="uq_connection_accounts"),
    )
    op.create_index("ix_connection_accounts_connection_id", "connection_accounts", ["connection_id"], unique=False)
    op.create_index("ix_connection_accounts_account_id", "connection_accounts", ["account_id"], unique=False)

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO connection_accounts (connection_id, account_id, membership_source, is_primary, enabled, created_at, updated_at)
            SELECT 1, id, 'manual', FALSE, enabled, :now, :now FROM accounts
            """
        ),
        {"now": now},
    )

    with op.batch_alter_table("sync_runs") as batch_op:
        batch_op.add_column(sa.Column("connection_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("window_days", sa.Integer(), nullable=False, server_default="14"))
        batch_op.add_column(sa.Column("accounts_synced", sa.Integer(), nullable=False, server_default="0"))
        batch_op.create_foreign_key("fk_sync_runs_connection_id", "connections", ["connection_id"], ["id"])
        batch_op.create_index("ix_sync_runs_connection_id", ["connection_id"], unique=False)
    conn.execute(sa.text("UPDATE sync_runs SET connection_id = 1, window_days = 14, accounts_synced = CASE WHEN account_id IS NULL THEN 0 ELSE 1 END"))

    _add_connection_scope_to_fact_table("daily_account_costs", ["account_id", "day"], "uq_daily_account_costs")
    _add_connection_scope_to_fact_table("daily_service_costs", ["account_id", "day", "service_name"], "uq_daily_service_costs")
    _add_connection_scope_to_fact_table("daily_team_costs", ["account_id", "day", "team_id"], "uq_daily_team_costs")

    with op.batch_alter_table("forecasts") as batch_op:
        batch_op.add_column(sa.Column("connection_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_forecasts_connection_id", "connections", ["connection_id"], ["id"])
        batch_op.create_index("ix_forecasts_connection_id", ["connection_id"], unique=False)
    conn.execute(sa.text("UPDATE forecasts SET connection_id = 1"))
    with op.batch_alter_table("forecasts") as batch_op:
        batch_op.alter_column("connection_id", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("anomalies") as batch_op:
        batch_op.add_column(sa.Column("connection_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_anomalies_connection_id", "connections", ["connection_id"], ["id"])
        batch_op.create_index("ix_anomalies_connection_id", ["connection_id"], unique=False)
    conn.execute(sa.text("UPDATE anomalies SET connection_id = 1"))
    with op.batch_alter_table("anomalies") as batch_op:
        batch_op.alter_column("connection_id", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.add_column(sa.Column("connection_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_recommendations_connection_id", "connections", ["connection_id"], ["id"])
        batch_op.create_index("ix_recommendations_connection_id", ["connection_id"], unique=False)
    conn.execute(sa.text("UPDATE recommendations SET connection_id = 1"))
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.alter_column("connection_id", existing_type=sa.Integer(), nullable=False)


def _add_connection_scope_to_fact_table(table_name: str, unique_columns: list[str], old_constraint_name: str) -> None:
    conn = op.get_bind()
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(sa.Column("connection_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(f"fk_{table_name}_connection_id", "connections", ["connection_id"], ["id"])
        batch_op.create_index(f"ix_{table_name}_connection_id", ["connection_id"], unique=False)
    conn.execute(sa.text(f"UPDATE {table_name} SET connection_id = 1"))
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.drop_constraint(old_constraint_name, type_="unique")
        batch_op.create_unique_constraint(old_constraint_name, ["connection_id", *unique_columns])
        batch_op.alter_column("connection_id", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.drop_index("ix_recommendations_connection_id")
        batch_op.drop_column("connection_id")

    with op.batch_alter_table("anomalies") as batch_op:
        batch_op.drop_index("ix_anomalies_connection_id")
        batch_op.drop_column("connection_id")

    with op.batch_alter_table("forecasts") as batch_op:
        batch_op.drop_index("ix_forecasts_connection_id")
        batch_op.drop_column("connection_id")

    _drop_connection_scope_from_fact_table("daily_team_costs", ["account_id", "day", "team_id"], "uq_daily_team_costs")
    _drop_connection_scope_from_fact_table("daily_service_costs", ["account_id", "day", "service_name"], "uq_daily_service_costs")
    _drop_connection_scope_from_fact_table("daily_account_costs", ["account_id", "day"], "uq_daily_account_costs")

    with op.batch_alter_table("sync_runs") as batch_op:
        batch_op.drop_index("ix_sync_runs_connection_id")
        batch_op.drop_column("accounts_synced")
        batch_op.drop_column("window_days")
        batch_op.drop_column("connection_id")

    op.drop_index("ix_connection_accounts_account_id", table_name="connection_accounts")
    op.drop_index("ix_connection_accounts_connection_id", table_name="connection_accounts")
    op.drop_table("connection_accounts")

    op.drop_index("ix_connections_kind", table_name="connections")
    op.drop_index("ix_connections_name", table_name="connections")
    op.drop_table("connections")


def _drop_connection_scope_from_fact_table(table_name: str, unique_columns: list[str], constraint_name: str) -> None:
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.drop_index(f"ix_{table_name}_connection_id")
        batch_op.drop_constraint(constraint_name, type_="unique")
        batch_op.create_unique_constraint(constraint_name, unique_columns)
        batch_op.drop_column("connection_id")
