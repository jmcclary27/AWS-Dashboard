"""workspace tenancy, ownership, invitations, and audit events

Revision ID: 0004_workspace_tenancy
Revises: 0003_payable_billing_truth
Create Date: 2026-07-13 00:00:00.000000

Existing synthetic data is placed in a system-owned Demo Workspace.  A
database that contains non-demo connections must be bootstrapped with an
owner so those connections never become unowned during the migration:

    AUTH_BOOTSTRAP_OWNER_SUB=<Cognito subject>
    AUTH_BOOTSTRAP_OWNER_EMAIL=<verified email>

AUTH_BOOTSTRAP_OWNER_ISSUER (or COGNITO_ISSUER) should also be set so the
bootstrap identity matches the issuer used by the API. The migration can
derive it from COGNITO_REGION and COGNITO_USER_POOL_ID, but never guesses a
fallback issuer for existing private data.

AUTH_BOOTSTRAP_WORKSPACE_NAME optionally controls the workspace name used for
those migrated non-demo connections.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "0004_workspace_tenancy"
down_revision = "0003_payable_billing_truth"
branch_labels = None
depends_on = None


DEMO_WORKSPACE_NAME = "Demo Workspace"
DEMO_CONNECTION_KIND = "demo"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _bootstrap_owner() -> tuple[str, str, str, str] | None:
    """Read the optional deployment bootstrap identity without importing app config."""

    subject = (os.getenv("AUTH_BOOTSTRAP_OWNER_SUB") or "").strip()
    email = (os.getenv("AUTH_BOOTSTRAP_OWNER_EMAIL") or "").strip().lower()
    if not subject and not email:
        return None
    if not subject or not email:
        raise RuntimeError(
            "AUTH_BOOTSTRAP_OWNER_SUB and AUTH_BOOTSTRAP_OWNER_EMAIL must both be set "
            "when migrating existing non-demo connections."
        )

    issuer = (os.getenv("AUTH_BOOTSTRAP_OWNER_ISSUER") or os.getenv("COGNITO_ISSUER") or "").strip()
    if not issuer:
        region = (os.getenv("COGNITO_REGION") or "").strip()
        user_pool_id = (os.getenv("COGNITO_USER_POOL_ID") or "").strip()
        if region and user_pool_id:
            issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        else:
            raise RuntimeError(
                "AUTH_BOOTSTRAP_OWNER_ISSUER (or COGNITO_ISSUER, or both COGNITO_REGION and "
                "COGNITO_USER_POOL_ID) must be set when migrating existing non-demo connections."
            )
    display_name = (os.getenv("AUTH_BOOTSTRAP_OWNER_DISPLAY_NAME") or email.split("@", 1)[0] or "Bootstrap owner").strip()
    field_limits = {
        "AUTH_BOOTSTRAP_OWNER_ISSUER": (issuer, 255),
        "AUTH_BOOTSTRAP_OWNER_SUB": (subject, 255),
        "AUTH_BOOTSTRAP_OWNER_EMAIL": (email, 320),
        "AUTH_BOOTSTRAP_OWNER_DISPLAY_NAME": (display_name, 120),
    }
    for field_name, (value, max_length) in field_limits.items():
        if len(value) > max_length:
            raise RuntimeError(f"{field_name} exceeds the maximum supported length of {max_length} characters.")
    return issuer, subject, email, display_name


def _legacy_non_demo_connection_count(bind: sa.Connection) -> int:
    return int(
        bind.execute(
            sa.text("SELECT COUNT(*) FROM connections WHERE kind IS NULL OR kind <> :demo_kind"),
            {"demo_kind": DEMO_CONNECTION_KIND},
        ).scalar_one()
    )


def _global_connection_name_constraint(bind: sa.Connection) -> str | None:
    """Return the old unique constraint name across PostgreSQL and SQLite."""

    for constraint in sa.inspect(bind).get_unique_constraints("connections"):
        if constraint.get("column_names") == ["name"]:
            # SQLite reflects anonymous constraints without a name.  The batch
            # naming convention below gives it this stable generated name.
            return constraint.get("name") or "uq_connections_name"
    return None


def upgrade() -> None:
    bind = op.get_bind()
    non_demo_connection_count = _legacy_non_demo_connection_count(bind)
    bootstrap_owner = _bootstrap_owner()
    if non_demo_connection_count and bootstrap_owner is None:
        raise RuntimeError(
            "Cannot migrate existing non-demo connections without an owner. Set "
            "AUTH_BOOTSTRAP_OWNER_SUB and AUTH_BOOTSTRAP_OWNER_EMAIL before retrying."
        )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_issuer", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identity_issuer", "subject", name="uq_users_identity_issuer_subject"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspaces_is_demo", "workspaces", ["is_demo"], unique=False)
    op.create_index("ix_workspaces_created_by_user_id", "workspaces", ["created_by_user_id"], unique=False)

    now = _utcnow()
    workspaces = sa.table(
        "workspaces",
        sa.column("name", sa.String()),
        sa.column("is_demo", sa.Boolean()),
        sa.column("created_by_user_id", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        workspaces,
        [
            {
                "name": DEMO_WORKSPACE_NAME,
                "is_demo": True,
                "created_by_user_id": None,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    demo_workspace_id = int(
        bind.execute(
            sa.text("SELECT id FROM workspaces WHERE is_demo = :is_demo ORDER BY id LIMIT 1"),
            {"is_demo": True},
        ).scalar_one()
    )

    bootstrap_user_id: int | None = None
    bootstrap_workspace_id: int | None = None
    if non_demo_connection_count:
        assert bootstrap_owner is not None
        issuer, subject, email, display_name = bootstrap_owner
        users = sa.table(
            "users",
            sa.column("identity_issuer", sa.String()),
            sa.column("subject", sa.String()),
            sa.column("email", sa.String()),
            sa.column("display_name", sa.String()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        op.bulk_insert(
            users,
            [
                {
                    "identity_issuer": issuer,
                    "subject": subject,
                    "email": email,
                    "display_name": display_name,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )
        bootstrap_user_id = int(
            bind.execute(
                sa.text(
                    "SELECT id FROM users WHERE identity_issuer = :issuer AND subject = :subject"
                ),
                {"issuer": issuer, "subject": subject},
            ).scalar_one()
        )
        workspace_name = (
            os.getenv("AUTH_BOOTSTRAP_WORKSPACE_NAME") or f"{display_name}'s Workspace"
        ).strip()
        if not workspace_name:
            workspace_name = "Bootstrap Workspace"
        if len(workspace_name) > 120:
            raise RuntimeError("AUTH_BOOTSTRAP_WORKSPACE_NAME exceeds the maximum supported length of 120 characters.")
        op.bulk_insert(
            workspaces,
            [
                {
                    "name": workspace_name,
                    "is_demo": False,
                    "created_by_user_id": bootstrap_user_id,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )
        bootstrap_workspace_id = int(
            bind.execute(
                sa.text(
                    "SELECT id FROM workspaces WHERE created_by_user_id = :user_id "
                    "AND is_demo = :is_demo ORDER BY id LIMIT 1"
                ),
                {"user_id": bootstrap_user_id, "is_demo": False},
            ).scalar_one()
        )

    op.create_table(
        "workspace_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_workspace_memberships_role"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_memberships_workspace_user"),
    )
    op.create_index("ix_workspace_memberships_workspace_id", "workspace_memberships", ["workspace_id"], unique=False)
    op.create_index("ix_workspace_memberships_user_id", "workspace_memberships", ["user_id"], unique=False)

    if bootstrap_user_id is not None and bootstrap_workspace_id is not None:
        memberships = sa.table(
            "workspace_memberships",
            sa.column("workspace_id", sa.Integer()),
            sa.column("user_id", sa.Integer()),
            sa.column("role", sa.String()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        op.bulk_insert(
            memberships,
            [
                {
                    "workspace_id": bootstrap_workspace_id,
                    "user_id": bootstrap_user_id,
                    "role": "owner",
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )

    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invited_by_user_id", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('editor', 'viewer')", name="ck_workspace_invitations_role"),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_workspace_invitations_token_hash"),
    )
    op.create_index("ix_workspace_invitations_workspace_id", "workspace_invitations", ["workspace_id"], unique=False)
    op.create_index("ix_workspace_invitations_email", "workspace_invitations", ["email"], unique=False)
    op.create_index("ix_workspace_invitations_expires_at", "workspace_invitations", ["expires_at"], unique=False)
    op.create_index("ix_workspace_invitations_invited_by_user_id", "workspace_invitations", ["invited_by_user_id"], unique=False)
    op.create_index("ix_workspace_invitations_accepted_by_user_id", "workspace_invitations", ["accepted_by_user_id"], unique=False)
    op.create_index("ix_workspace_invitations_revoked_by_user_id", "workspace_invitations", ["revoked_by_user_id"], unique=False)

    # Add nullable columns first, populate every existing connection, then make
    # workspace_id mandatory.  This keeps the operation safe for both SQLite
    # batch migrations and PostgreSQL.
    with op.batch_alter_table("connections") as batch_op:
        batch_op.add_column(sa.Column("workspace_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("created_by_user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_connections_workspace_id", "workspaces", ["workspace_id"], ["id"])
        batch_op.create_foreign_key("fk_connections_created_by_user_id", "users", ["created_by_user_id"], ["id"])
        batch_op.create_index("ix_connections_workspace_id", ["workspace_id"], unique=False)
        batch_op.create_index("ix_connections_created_by_user_id", ["created_by_user_id"], unique=False)

    bind.execute(
        sa.text(
            "UPDATE connections SET workspace_id = :workspace_id, created_by_user_id = NULL "
            "WHERE kind = :demo_kind"
        ),
        {"workspace_id": demo_workspace_id, "demo_kind": DEMO_CONNECTION_KIND},
    )
    if bootstrap_workspace_id is not None and bootstrap_user_id is not None:
        bind.execute(
            sa.text(
                "UPDATE connections SET workspace_id = :workspace_id, created_by_user_id = :user_id "
                "WHERE kind IS NULL OR kind <> :demo_kind"
            ),
            {
                "workspace_id": bootstrap_workspace_id,
                "user_id": bootstrap_user_id,
                "demo_kind": DEMO_CONNECTION_KIND,
            },
        )

    unassigned_connection_count = int(
        bind.execute(sa.text("SELECT COUNT(*) FROM connections WHERE workspace_id IS NULL")).scalar_one()
    )
    if unassigned_connection_count:
        raise RuntimeError("Refusing to complete tenancy migration with unassigned connections.")

    global_name_constraint = _global_connection_name_constraint(bind)
    existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("connections")}
    with op.batch_alter_table(
        "connections",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
    ) as batch_op:
        if global_name_constraint:
            batch_op.drop_constraint(global_name_constraint, type_="unique")
        if "ix_connections_name" in existing_indexes:
            batch_op.drop_index("ix_connections_name")
        batch_op.create_unique_constraint("uq_connections_workspace_name", ["workspace_id", "name"])
        batch_op.alter_column("workspace_id", existing_type=sa.Integer(), nullable=False)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=255), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"], unique=False)
    op.create_index("ix_audit_events_workspace_id", "audit_events", ["workspace_id"], unique=False)
    op.create_index("ix_audit_events_connection_id", "audit_events", ["connection_id"], unique=False)
    op.create_index("ix_audit_events_action", "audit_events", ["action"], unique=False)
    op.create_index("ix_audit_events_outcome", "audit_events", ["outcome"], unique=False)
    op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"], unique=False)
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    duplicate_name = bind.execute(
        sa.text("SELECT name FROM connections GROUP BY name HAVING COUNT(*) > 1 LIMIT 1")
    ).scalar_one_or_none()
    if duplicate_name is not None:
        raise RuntimeError(
            "Cannot downgrade workspace tenancy while connection names overlap across workspaces: "
            f"{duplicate_name!r}."
        )

    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_request_id", table_name="audit_events")
    op.drop_index("ix_audit_events_outcome", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_connection_id", table_name="audit_events")
    op.drop_index("ix_audit_events_workspace_id", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_table("audit_events")

    with op.batch_alter_table("connections") as batch_op:
        batch_op.drop_constraint("uq_connections_workspace_name", type_="unique")
        batch_op.drop_index("ix_connections_created_by_user_id")
        batch_op.drop_index("ix_connections_workspace_id")
        batch_op.drop_constraint("fk_connections_created_by_user_id", type_="foreignkey")
        batch_op.drop_constraint("fk_connections_workspace_id", type_="foreignkey")
        batch_op.create_unique_constraint("uq_connections_name", ["name"])
        batch_op.create_index("ix_connections_name", ["name"], unique=True)
        batch_op.drop_column("created_by_user_id")
        batch_op.drop_column("workspace_id")

    op.drop_index("ix_workspace_invitations_revoked_by_user_id", table_name="workspace_invitations")
    op.drop_index("ix_workspace_invitations_accepted_by_user_id", table_name="workspace_invitations")
    op.drop_index("ix_workspace_invitations_invited_by_user_id", table_name="workspace_invitations")
    op.drop_index("ix_workspace_invitations_expires_at", table_name="workspace_invitations")
    op.drop_index("ix_workspace_invitations_email", table_name="workspace_invitations")
    op.drop_index("ix_workspace_invitations_workspace_id", table_name="workspace_invitations")
    op.drop_table("workspace_invitations")

    op.drop_index("ix_workspace_memberships_user_id", table_name="workspace_memberships")
    op.drop_index("ix_workspace_memberships_workspace_id", table_name="workspace_memberships")
    op.drop_table("workspace_memberships")

    op.drop_index("ix_workspaces_created_by_user_id", table_name="workspaces")
    op.drop_index("ix_workspaces_is_demo", table_name="workspaces")
    op.drop_table("workspaces")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
