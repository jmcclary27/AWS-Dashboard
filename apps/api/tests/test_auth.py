from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth as auth
from app.auth import Principal, get_authorized_connection, require_workspace_role, upsert_principal_user
from app.config import Settings, get_settings
from app.db.base import Base
from app.db.models import Connection, User, Workspace, WorkspaceMembership
from app.db.session import get_db
from app.main import app


def _base64url_integer(value: int) -> str:
    import base64

    return base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).decode().rstrip("=")


@pytest.fixture
def cognito_material(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    monkeypatch.setattr(
        auth,
        "fetch_jwks",
        lambda _: {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": "test-key",
                    "use": "sig",
                    "n": _base64url_integer(numbers.n),
                    "e": _base64url_integer(numbers.e),
                }
            ]
        },
    )
    auth.clear_jwks_cache()
    settings = Settings(
        auth_enabled=True,
        cognito_issuer="https://cognito.example.test/pool",
        cognito_app_client_id="dashboard-client",
        cognito_domain="login.example.test",
    )
    return private_key, settings


def _signed_access_token(private_key, settings: Settings, **overrides: object) -> str:
    claims = {
        "sub": "cognito-subject",
        "iss": settings.resolved_cognito_issuer,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "token_use": "access",
        "client_id": settings.cognito_app_client_id,
        "email": "user@example.test",
        "email_verified": True,
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})


@contextmanager
def cognito_api_client(monkeypatch):
    """Exercise the real HTTP authentication dependency with Cognito enabled."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, class_=Session)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("COGNITO_ISSUER", "https://cognito.example.test/pool")
    monkeypatch.setenv("COGNITO_APP_CLIENT_ID", "dashboard-client")
    get_settings.cache_clear()
    original_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        get_settings.cache_clear()
        engine.dispose()


def test_cognito_access_token_verification_requires_access_token_and_client(cognito_material) -> None:
    private_key, settings = cognito_material
    principal = auth.verify_cognito_access_token(_signed_access_token(private_key, settings), settings)

    assert principal.subject == "cognito-subject"
    assert principal.email == "user@example.test"
    assert principal.email_verified is True

    with pytest.raises(auth.AuthenticationError):
        auth.verify_cognito_access_token(_signed_access_token(private_key, settings, token_use="id"), settings)
    with pytest.raises(auth.AuthenticationError):
        auth.verify_cognito_access_token(_signed_access_token(private_key, settings, client_id="other-client"), settings)
    with pytest.raises(auth.AuthenticationError):
        auth.verify_cognito_access_token(
            _signed_access_token(private_key, settings, iss="https://cognito.example.test/other-pool"),
            settings,
        )
    with pytest.raises(auth.AuthenticationError):
        auth.verify_cognito_access_token("definitely-not-a-jwt", settings)


def test_cognito_enabled_api_returns_401_for_absent_or_malformed_tokens(monkeypatch) -> None:
    with cognito_api_client(monkeypatch) as client:
        absent = client.get("/api/v1/me")
        malformed = client.get("/api/v1/me", headers={"Authorization": "Bearer definitely-not-a-jwt"})

    assert absent.status_code == 401
    assert absent.headers["www-authenticate"] == "Bearer"
    assert malformed.status_code == 401
    assert malformed.headers["www-authenticate"] == "Bearer"


def test_cognito_access_token_verification_rejects_expired_and_wrong_signature(cognito_material) -> None:
    private_key, settings = cognito_material
    with pytest.raises(auth.AuthenticationError):
        auth.verify_cognito_access_token(
            _signed_access_token(private_key, settings, exp=datetime.now(timezone.utc) - timedelta(minutes=2)),
            settings,
        )
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(auth.AuthenticationError):
        auth.verify_cognito_access_token(_signed_access_token(other_key, settings), settings)


def test_cognito_access_token_enriches_standard_access_claims_from_userinfo(cognito_material, monkeypatch) -> None:
    private_key, settings = cognito_material
    observed: list[tuple[str, str]] = []

    def userinfo(access_token: str, endpoint: str) -> dict[str, object]:
        observed.append((access_token, endpoint))
        return {
            "sub": "cognito-subject",
            "email": "Invitee@Example.Test",
            "email_verified": "true",
            "name": "Invitee",
        }

    monkeypatch.setattr(auth, "fetch_cognito_userinfo", userinfo)
    token = _signed_access_token(private_key, settings, email=None, email_verified=None)

    principal = auth.verify_cognito_access_token(token, settings)

    assert principal.email == "invitee@example.test"
    assert principal.email_verified is True
    assert principal.display_name == "Invitee"
    assert observed == [(token, "https://login.example.test/oauth2/userInfo")]


def test_cognito_userinfo_subject_must_match_verified_access_token(cognito_material, monkeypatch) -> None:
    private_key, settings = cognito_material
    monkeypatch.setattr(
        auth,
        "fetch_cognito_userinfo",
        lambda *_: {"sub": "another-subject", "email": "invitee@example.test", "email_verified": True},
    )

    with pytest.raises(auth.AuthenticationError):
        auth.verify_cognito_access_token(
            _signed_access_token(private_key, settings, email=None, email_verified=None),
            settings,
        )


def test_cognito_userinfo_is_not_called_when_signed_claims_are_complete(cognito_material, monkeypatch) -> None:
    private_key, settings = cognito_material

    def unexpected_userinfo(*_: object) -> dict[str, object]:
        pytest.fail("userinfo must not be called when signed claims include verified email")

    monkeypatch.setattr(auth, "fetch_cognito_userinfo", unexpected_userinfo)

    principal = auth.verify_cognito_access_token(_signed_access_token(private_key, settings), settings)
    assert principal.email == "user@example.test"


def test_workspace_authorization_hides_cross_workspace_connections_and_locks_demo() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owner = upsert_principal_user(
            session,
            Principal(subject="owner", issuer="issuer", email="owner@example.test", email_verified=True),
        )
        owner_workspace = session.execute(
            select(Workspace).where(Workspace.created_by_user_id == owner.user_id, Workspace.is_demo.is_(False))
        ).scalar_one()
        private_connection = Connection(
            workspace_id=owner_workspace.id,
            created_by_user_id=owner.user_id,
            name="Private",
            kind="account_role",
        )
        demo_workspace = Workspace(name="Demo Workspace", is_demo=True)
        session.add_all([private_connection, demo_workspace])
        session.flush()
        demo_connection = Connection(workspace_id=demo_workspace.id, name="Demo", kind="demo")
        other_user = User(
            identity_issuer="issuer",
            subject="other",
            email="other@example.test",
            display_name="Other",
        )
        session.add_all([demo_connection, other_user])
        session.commit()

        other = Principal(subject="other", issuer="issuer", email="other@example.test", user_id=other_user.id)
        with pytest.raises(HTTPException) as inaccessible:
            get_authorized_connection(session, other, private_connection.id)
        assert inaccessible.value.status_code == 404

        assert require_workspace_role(session, other, demo_workspace.id).role == "viewer"
        with pytest.raises(HTTPException) as demo_mutation:
            get_authorized_connection(session, other, demo_connection.id, "editor")
        assert demo_mutation.value.status_code == 403


def test_workspace_editor_threshold_and_owner_hierarchy() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owner = User(identity_issuer="issuer", subject="owner", email="owner@example.test", display_name="Owner")
        editor = User(identity_issuer="issuer", subject="editor", email="editor@example.test", display_name="Editor")
        workspace = Workspace(name="Team Workspace", is_demo=False)
        session.add_all([owner, editor, workspace])
        session.flush()
        session.add_all(
            [
                WorkspaceMembership(workspace_id=workspace.id, user_id=owner.id, role="owner"),
                WorkspaceMembership(workspace_id=workspace.id, user_id=editor.id, role="editor"),
            ]
        )
        session.commit()

        assert require_workspace_role(session, Principal(subject="owner", issuer="issuer", user_id=owner.id), workspace.id, "editor").role == "owner"
        with pytest.raises(HTTPException) as owner_only:
            require_workspace_role(session, Principal(subject="editor", issuer="issuer", user_id=editor.id), workspace.id, "owner")
        assert owner_only.value.status_code == 403
