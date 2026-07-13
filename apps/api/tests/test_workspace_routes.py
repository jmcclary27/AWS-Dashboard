from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import Principal, get_current_principal, require_csrf
from app.db.base import Base
from app.db.models import AuditEvent, Connection, User, Workspace, WorkspaceInvitation, WorkspaceMembership, utcnow
from app.db.seed import ensure_reference_data
from app.db.session import get_db
from app.main import app


class WorkspaceApi:
    def __init__(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, class_=Session, expire_on_commit=False)

    @contextmanager
    def client_as(self, principal: Principal):
        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        original_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_principal] = lambda: principal
        # These route tests supply principals directly, rather than a browser
        # cookie, so the CSRF transport check is covered at the auth helper
        # level and does not obscure authorization assertions here.
        app.dependency_overrides[require_csrf] = lambda: None
        try:
            with TestClient(app) as client:
                yield client
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(original_overrides)

    def close(self) -> None:
        self.engine.dispose()


@pytest.fixture
def workspace_api():
    api = WorkspaceApi()
    try:
        yield api
    finally:
        api.close()


def add_user(session: Session, subject: str, email: str, *, verified: bool = True) -> Principal:
    user = User(
        identity_issuer="tests",
        subject=subject,
        email=email,
        display_name=subject.replace("-", " ").title(),
    )
    session.add(user)
    session.flush()
    return Principal(
        subject=subject,
        issuer="tests",
        email=email,
        email_verified=verified,
        display_name=user.display_name,
        user_id=user.id,
    )


def add_workspace(session: Session, owner: Principal, name: str) -> Workspace:
    workspace = Workspace(name=name, created_by_user_id=owner.user_id)
    session.add(workspace)
    session.flush()
    session.add(WorkspaceMembership(workspace_id=workspace.id, user_id=owner.user_id, role="owner"))
    session.flush()
    return workspace


def add_membership(session: Session, workspace: Workspace, principal: Principal, role: str) -> None:
    session.add(WorkspaceMembership(workspace_id=workspace.id, user_id=principal.user_id, role=role))
    session.flush()


def test_cross_workspace_connections_are_hidden_and_viewers_are_read_only(workspace_api: WorkspaceApi) -> None:
    with workspace_api.session_factory() as session:
        owner = add_user(session, "owner", "owner@example.test")
        viewer = add_user(session, "viewer", "viewer@example.test")
        outsider = add_user(session, "outsider", "outsider@example.test")
        owner_workspace = add_workspace(session, owner, "Owner Workspace")
        add_workspace(session, outsider, "Outsider Workspace")
        add_membership(session, owner_workspace, viewer, "viewer")
        private_connection = Connection(
            workspace_id=owner_workspace.id,
            created_by_user_id=owner.user_id,
            name="Private Org",
            kind="org_management",
            enabled=True,
            team_tag_key="Team",
        )
        session.add(private_connection)
        demo_connection, _, _ = ensure_reference_data(session)
        session.commit()
        private_connection_id = private_connection.id
        owner_workspace_id = owner_workspace.id
        demo_workspace_id = demo_connection.workspace_id
        demo_connection_id = demo_connection.id

    with workspace_api.client_as(outsider) as client:
        connection = client.get(f"/api/v1/connections/{private_connection_id}")
        summary = client.get(f"/api/v1/summary?connection_id={private_connection_id}")
        workspace = client.get(f"/api/v1/connections?workspace_id={owner_workspace_id}")

    assert connection.status_code == 404
    assert summary.status_code == 404
    assert workspace.status_code == 404

    with workspace_api.client_as(viewer) as client:
        me = client.get("/api/v1/me")
        listing = client.get(f"/api/v1/connections?workspace_id={owner_workspace_id}")
        connection_config = client.get(f"/api/v1/connections/{private_connection_id}")
        create = client.post(
            "/api/v1/connections",
            json={"workspace_id": owner_workspace_id, "name": "Viewer Attempt", "kind": "org_management"},
        )

    assert me.status_code == 200
    roles_by_workspace = {item["id"]: item["role"] for item in me.json()["workspaces"]}
    assert roles_by_workspace[owner_workspace_id] == "viewer"
    assert listing.status_code == 200
    assert listing.json()["items"][0]["id"] == private_connection_id
    assert connection_config.status_code == 403
    assert create.status_code == 403

    with workspace_api.client_as(outsider) as client:
        demo_listing = client.get(f"/api/v1/connections?workspace_id={demo_workspace_id}")
        demo_create = client.post(
            "/api/v1/connections",
            json={"workspace_id": demo_workspace_id, "name": "Demo Attempt", "kind": "org_management"},
        )
        demo_validate = client.post(f"/api/v1/connections/{demo_connection_id}/validate")

    assert demo_listing.status_code == 200
    assert demo_listing.json()["read_only"] is True
    assert demo_create.status_code == 403
    assert demo_validate.status_code == 403

    with workspace_api.session_factory() as session:
        denied = session.scalars(
            select(AuditEvent).where(
                AuditEvent.connection_id == private_connection_id,
                AuditEvent.outcome == "denied",
            )
        ).all()
    assert denied


def test_connection_external_id_is_write_only_and_audited(workspace_api: WorkspaceApi) -> None:
    with workspace_api.session_factory() as session:
        owner = add_user(session, "owner", "owner@example.test")
        editor = add_user(session, "editor", "editor@example.test")
        workspace = add_workspace(session, owner, "Team Workspace")
        add_membership(session, workspace, editor, "editor")
        session.commit()
        workspace_id = workspace.id

    original_external_id = "never-return-this-external-id"
    replacement_external_id = "also-never-return-this-external-id"
    with workspace_api.client_as(editor) as client:
        created = client.post(
            "/api/v1/connections",
            json={
                "workspace_id": workspace_id,
                "name": "Editor Org",
                "kind": "org_management",
                "role_arn": "arn:aws:iam::111111111111:role/CostRead",
                "external_id": original_external_id,
            },
        )
        assert created.status_code == 201
        connection_id = created.json()["item"]["id"]
        listed = client.get(f"/api/v1/connections?workspace_id={workspace_id}")
        configured = client.get(f"/api/v1/connections/{connection_id}")
        updated = client.patch(
            f"/api/v1/connections/{connection_id}",
            json={"external_id": replacement_external_id},
        )

    for response in (created, listed, configured, updated):
        assert original_external_id not in response.text
        assert replacement_external_id not in response.text
    assert created.json()["item"]["external_id_configured"] is True
    assert configured.json()["item"]["external_id_configured"] is True
    assert updated.json()["item"]["external_id_configured"] is True

    with workspace_api.session_factory() as session:
        connection = session.get(Connection, connection_id)
        assert connection is not None
        assert connection.workspace_id == workspace_id
        assert connection.created_by_user_id == editor.user_id
        assert connection.external_id == replacement_external_id
        events = session.scalars(
            select(AuditEvent).where(AuditEvent.connection_id == connection_id).order_by(AuditEvent.id)
        ).all()

    assert [event.action for event in events] == ["connection.created", "connection.updated"]
    assert all(original_external_id not in str(event.metadata_json) for event in events)
    assert all(replacement_external_id not in str(event.metadata_json) for event in events)
    assert events[-1].metadata_json["fields"] == ["external_id_configured"]

    with workspace_api.client_as(owner) as client:
        audit = client.get(f"/api/v1/workspaces/{workspace_id}/audit-events?limit=1")
        cursor = audit.json()["next_before_id"]
        next_page = client.get(
            f"/api/v1/workspaces/{workspace_id}/audit-events?limit=1&before_id={cursor}"
        )

    assert audit.status_code == 200
    assert cursor is not None
    assert next_page.status_code == 200
    assert next_page.json()["items"][0]["id"] < cursor
    assert audit.json()["items"][0]["request_id"]
    assert original_external_id not in audit.text
    assert replacement_external_id not in audit.text


def test_invites_are_email_bound_single_use_revocable_and_owner_audited(workspace_api: WorkspaceApi) -> None:
    with workspace_api.session_factory() as session:
        owner = add_user(session, "owner", "owner@example.test")
        invited = add_user(session, "invited", "invitee@example.test")
        wrong_email = add_user(session, "wrong-email", "wrong@example.test")
        unverified = add_user(session, "unverified", "invitee@example.test", verified=False)
        second = add_user(session, "second", "second@example.test")
        workspace = add_workspace(session, owner, "Invite Workspace")
        session.commit()
        workspace_id = workspace.id

    with workspace_api.client_as(owner) as client:
        created = client.post(
            f"/api/v1/workspaces/{workspace_id}/invites",
            json={"email": "Invitee@Example.Test", "role": "viewer"},
        )

    assert created.status_code == 201
    invite = created.json()["item"]
    token = parse_qs(urlparse(invite["invite_url"]).query)["token"][0]
    assert invite["email"] == "invitee@example.test"

    with workspace_api.session_factory() as session:
        invitation = session.get(WorkspaceInvitation, invite["id"])
        assert invitation is not None
        assert invitation.token_hash == sha256(token.encode("utf-8")).hexdigest()
        assert token not in invitation.token_hash
        assert (invitation.expires_at.date() - utcnow().date()).days >= 6

    with workspace_api.client_as(wrong_email) as client:
        wrong_accept = client.post("/api/v1/invites/accept", json={"token": token})
    with workspace_api.client_as(unverified) as client:
        unverified_accept = client.post("/api/v1/invites/accept", json={"token": token})
    with workspace_api.client_as(invited) as client:
        accepted = client.post("/api/v1/invites/accept", json={"token": token})
        second_accept = client.post("/api/v1/invites/accept", json={"token": token})

    assert wrong_accept.status_code == 403
    assert unverified_accept.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json() == {"workspace_id": workspace_id, "role": "viewer"}
    assert second_accept.status_code == 404

    with workspace_api.client_as(owner) as client:
        member_update = client.patch(
            f"/api/v1/workspaces/{workspace_id}/members/{invited.user_id}",
            json={"role": "editor"},
        )
        member_remove = client.delete(f"/api/v1/workspaces/{workspace_id}/members/{invited.user_id}")
        revocable = client.post(
            f"/api/v1/workspaces/{workspace_id}/invites",
            json={"email": "second@example.test", "role": "editor"},
        )
        revocable_id = revocable.json()["item"]["id"]
        revoked = client.delete(f"/api/v1/workspaces/{workspace_id}/invites/{revocable_id}")
        audit = client.get(f"/api/v1/workspaces/{workspace_id}/audit-events?limit=100")

    assert member_update.status_code == 200
    assert member_update.json()["role"] == "editor"
    assert member_remove.status_code == 200
    assert revocable.status_code == 201
    assert revoked.status_code == 200
    assert audit.status_code == 200
    assert token not in audit.text
    actions = {item["action"] for item in audit.json()["items"]}
    assert {
        "workspace.invite_created",
        "workspace.invite_accepted",
        "workspace.member_updated",
        "workspace.member_removed",
        "workspace.invite_revoked",
    } <= actions

    second_token = parse_qs(urlparse(revocable.json()["item"]["invite_url"]).query)["token"][0]
    with workspace_api.client_as(second) as client:
        revoked_accept = client.post("/api/v1/invites/accept", json={"token": second_token})
    with workspace_api.client_as(invited) as client:
        no_longer_member = client.get(f"/api/v1/connections?workspace_id={workspace_id}")
        owner_audit = client.get(f"/api/v1/workspaces/{workspace_id}/audit-events")

    assert revoked_accept.status_code == 404
    assert no_longer_member.status_code == 404
    assert owner_audit.status_code == 404

    expired_token = "x" * 24
    with workspace_api.session_factory() as session:
        session.add(
            WorkspaceInvitation(
                workspace_id=workspace_id,
                email="invitee@example.test",
                role="viewer",
                token_hash=sha256(expired_token.encode("utf-8")).hexdigest(),
                expires_at=utcnow() - timedelta(seconds=1),
                invited_by_user_id=owner.user_id,
            )
        )
        session.commit()

    with workspace_api.client_as(invited) as client:
        expired_accept = client.post("/api/v1/invites/accept", json={"token": expired_token})
    assert expired_accept.status_code == 404
