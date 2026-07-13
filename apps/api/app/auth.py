"""Cognito authentication and workspace authorization primitives.

Routes intentionally call the authorization helpers in this module instead of
trusting a selected connection or workspace supplied by the browser.  The
helpers are also plain functions (rather than route-specific dependencies),
which makes them straightforward to use in tests and background entrypoints.
"""

from __future__ import annotations

import json
import hashlib
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_db

if TYPE_CHECKING:
    from app.db.models import Connection, Workspace


WorkspaceRole = Literal["owner", "editor", "viewer"]
VALID_WORKSPACE_ROLES: frozenset[str] = frozenset({"owner", "editor", "viewer"})
_ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}


class AuthenticationError(Exception):
    """A token is absent, malformed, or not valid for this API."""


class AuthenticationUnavailable(AuthenticationError):
    """Cognito/JWKS configuration or transport is unavailable."""


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated Cognito identity plus the matching local user id."""

    subject: str
    issuer: str
    email: str | None = None
    email_verified: bool = False
    display_name: str | None = None
    user_id: int | None = None
    claims: Mapping[str, Any] = field(default_factory=dict, repr=False)
    is_development: bool = False


@dataclass(frozen=True, slots=True)
class WorkspaceAccess:
    """An authorized workspace and the effective role for the principal."""

    workspace: Workspace
    role: WorkspaceRole
    is_demo: bool = False
    is_virtual_membership: bool = False


_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_cache_lock = threading.Lock()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not forward a bearer token to a redirect target."""

    def redirect_request(self, *_: Any, **__: Any) -> None:
        return None


def clear_jwks_cache() -> None:
    """Clear the process-local JWKS cache (primarily useful in tests)."""

    with _jwks_cache_lock:
        _jwks_cache.clear()


def fetch_jwks(jwks_url: str) -> dict[str, Any]:
    """Fetch one Cognito JWKS document without exposing response details."""

    request = urllib.request.Request(jwks_url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310 - URL is deployment config
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuthenticationUnavailable("Unable to retrieve Cognito signing keys.") from error

    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
        raise AuthenticationUnavailable("Cognito signing keys are malformed.")
    return payload


def fetch_cognito_userinfo(access_token: str, userinfo_url: str) -> dict[str, Any]:
    """Fetch the scoped Cognito user-info document for a verified access token.

    Cognito access tokens intentionally do not ordinarily contain profile and
    email attributes.  The OAuth user-info endpoint is the authoritative
    source for those requested scopes.  Neither the token nor a provider
    response is ever included in an exception, log message, or audit event.
    """

    parsed = urllib.parse.urlparse(userinfo_url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise AuthenticationUnavailable("Cognito user information endpoint is not configured safely.")

    request = urllib.request.Request(
        userinfo_url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Cache-Control": "no-store",
        },
    )
    try:
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=5) as response:  # nosec B310 - URL is deployment config
            raw_payload = response.read(65_537)
    except urllib.error.HTTPError as error:
        # The access token was already signature-verified.  Cognito may still
        # reject it when it has been revoked or lacks the required scopes.
        if error.code in {400, 401, 403}:
            raise AuthenticationError("Cognito rejected the access token.") from error
        raise AuthenticationUnavailable("Unable to retrieve Cognito user information.") from error
    except (OSError, urllib.error.URLError) as error:
        raise AuthenticationUnavailable("Unable to retrieve Cognito user information.") from error

    if len(raw_payload) > 65_536:
        raise AuthenticationUnavailable("Cognito user information response is malformed.")
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuthenticationUnavailable("Cognito user information response is malformed.") from error
    if not isinstance(payload, dict):
        raise AuthenticationUnavailable("Cognito user information response is malformed.")
    return payload


def _jwks_for(url: str, cache_seconds: int, *, force_refresh: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    with _jwks_cache_lock:
        cached = _jwks_cache.get(url)
        if not force_refresh and cached and cached[0] > now:
            return cached[1]

    document = fetch_jwks(url)
    with _jwks_cache_lock:
        _jwks_cache[url] = (now + max(cache_seconds, 0), document)
    return document


class CognitoAccessTokenVerifier:
    """Verify Cognito *access* JWTs against the user pool's JWKS."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def issuer(self) -> str:
        return self.settings.resolved_cognito_issuer

    @property
    def jwks_url(self) -> str:
        return self.settings.resolved_cognito_jwks_url

    def _validate_configuration(self) -> None:
        if not self.issuer or not self.jwks_url or not self.settings.cognito_app_client_id.strip():
            raise AuthenticationUnavailable("Cognito authentication is not configured.")

    def _signing_key(self, header: Mapping[str, Any]) -> Any:
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise AuthenticationError("Unsupported token header.")

        def key_for(document: Mapping[str, Any]) -> dict[str, Any] | None:
            for key in document.get("keys", []):
                if (
                    isinstance(key, dict)
                    and key.get("kid") == header["kid"]
                    and key.get("kty") == "RSA"
                    and key.get("use", "sig") == "sig"
                ):
                    return key
            return None

        key = key_for(_jwks_for(self.jwks_url, self.settings.cognito_jwks_cache_seconds))
        # Cognito rotates keys.  A fresh fetch before rejecting an unknown kid
        # prevents a stale cache from causing a false authentication failure.
        if key is None:
            key = key_for(
                _jwks_for(
                    self.jwks_url,
                    self.settings.cognito_jwks_cache_seconds,
                    force_refresh=True,
                )
            )
        if key is None:
            raise AuthenticationError("Unknown token signing key.")
        try:
            return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
        except (TypeError, ValueError, jwt.PyJWTError) as error:
            raise AuthenticationUnavailable("Cognito signing key is invalid.") from error

    def verify(self, token: str) -> dict[str, Any]:
        self._validate_configuration()
        try:
            header = jwt.get_unverified_header(token)
            signing_key = self._signing_key(header)
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                issuer=self.issuer,
                leeway=max(self.settings.auth_clock_skew_seconds, 0),
                options={
                    "verify_aud": False,
                    "require": ["exp", "iss", "sub", "token_use", "client_id"],
                },
            )
        except AuthenticationUnavailable:
            raise
        except (jwt.PyJWTError, TypeError, ValueError) as error:
            raise AuthenticationError("Invalid access token.") from error

        if claims.get("token_use") != "access":
            raise AuthenticationError("Token is not an access token.")
        if claims.get("client_id") != self.settings.cognito_app_client_id:
            raise AuthenticationError("Token was issued for another client.")
        return claims


def _claim_string(claims: Mapping[str, Any], name: str) -> str | None:
    value = claims.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _claim_bool(claims: Mapping[str, Any], name: str) -> bool:
    value = claims.get(name)
    return value is True or (isinstance(value, str) and value.lower() == "true")


def principal_from_claims(claims: Mapping[str, Any]) -> Principal:
    """Build a principal only after a JWT has already been signature-verified."""

    subject = _claim_string(claims, "sub")
    issuer = _claim_string(claims, "iss")
    if not subject or not issuer:
        raise AuthenticationError("Access token is missing a subject or issuer.")
    email = _claim_string(claims, "email")
    if email:
        email = email.lower()
    display_name = (
        _claim_string(claims, "name")
        or _claim_string(claims, "preferred_username")
        or _claim_string(claims, "username")
        or email
    )
    return Principal(
        subject=subject,
        issuer=issuer,
        email=email,
        email_verified=_claim_bool(claims, "email_verified"),
        display_name=display_name,
        claims=dict(claims),
    )


def enrich_principal_from_userinfo(
    principal: Principal,
    access_token: str,
    settings: Settings,
) -> Principal:
    """Fill absent email/profile claims from Cognito's authenticated endpoint.

    The user-info response is accepted only when its subject exactly matches
    the already signature-verified JWT subject.  A response can supplement,
    but never replace, the JWT identity or issuer.
    """

    if principal.email and principal.email_verified:
        return principal

    userinfo_url = settings.resolved_cognito_userinfo_url
    if not userinfo_url:
        raise AuthenticationUnavailable("Cognito user information endpoint is not configured.")
    userinfo = fetch_cognito_userinfo(access_token, userinfo_url)
    response_subject = userinfo.get("sub")
    if not isinstance(response_subject, str) or not secrets.compare_digest(response_subject, principal.subject):
        raise AuthenticationError("Cognito user information subject does not match the access token.")

    userinfo_email = _claim_string(userinfo, "email")
    email = (userinfo_email or principal.email)
    if email:
        email = email.lower()
    # Preserve a signed affirmative JWT claim if a provider omits the optional
    # field from user-info, but never turn an absent/false claim into true.
    email_verified = principal.email_verified or _claim_bool(userinfo, "email_verified")
    display_name = principal.display_name or (
        _claim_string(userinfo, "name")
        or _claim_string(userinfo, "preferred_username")
        or _claim_string(userinfo, "username")
        or email
    )
    return replace(
        principal,
        email=email,
        email_verified=email_verified,
        display_name=display_name,
    )


def verify_cognito_access_token(token: str, settings: Settings | None = None) -> Principal:
    """Verify an access token and return its safe, normalized principal."""

    resolved_settings = settings or get_settings()
    principal = principal_from_claims(CognitoAccessTokenVerifier(resolved_settings).verify(token))
    return enrich_principal_from_userinfo(principal, token, resolved_settings)


def _development_principal(settings: Settings) -> Principal:
    return Principal(
        subject=settings.development_subject,
        issuer=settings.development_identity_issuer,
        email=settings.development_email.lower() or None,
        email_verified=True,
        display_name=settings.development_display_name,
        is_development=True,
    )


def extract_access_token(request: Request, settings: Settings | None = None) -> str | None:
    """Prefer an explicit Bearer token; otherwise use the HttpOnly session cookie."""

    resolved_settings = settings or get_settings()
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip() or " " in token.strip():
            raise AuthenticationError("Malformed Authorization header.")
        return token.strip()
    token = request.cookies.get(resolved_settings.auth_access_cookie_name)
    return token.strip() if token and token.strip() else None


def _tenancy_models() -> tuple[Any, Any, Any, Any]:
    """Delay imports so this module stays importable during migrations/tests."""

    from app.db.models import Connection, User, Workspace, WorkspaceMembership

    return Connection, User, Workspace, WorkspaceMembership


def _personal_workspace_name(display_name: str | None) -> str:
    base = (display_name or "My").strip()[:100] or "My"
    return f"{base}'s Workspace"[:120]


def _stored_email(principal: Principal) -> str:
    """Use a non-deliverable placeholder when an access token lacks email."""

    if principal.email:
        return principal.email
    digest = hashlib.sha256(f"{principal.issuer}:{principal.subject}".encode("utf-8")).hexdigest()[:32]
    return f"unknown-{digest}@identity.invalid"


def _stored_display_name(principal: Principal) -> str:
    return (principal.display_name or "Cognito User").strip()[:120] or "Cognito User"


def upsert_principal_user(db: Session, principal: Principal) -> Principal:
    """Persist the identity and ensure its first login receives an owner workspace."""

    _, User, Workspace, WorkspaceMembership = _tenancy_models()
    user = db.execute(
        select(User).where(User.identity_issuer == principal.issuer, User.subject == principal.subject)
    ).scalar_one_or_none()
    changed = False
    if user is None:
        user = User(
            identity_issuer=principal.issuer,
            subject=principal.subject,
            email=_stored_email(principal),
            display_name=_stored_display_name(principal),
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            # Concurrent first requests can race on the issuer/subject unique
            # key.  Roll back the failed insert and reuse the winning row.
            db.rollback()
            user = db.execute(
                select(User).where(User.identity_issuer == principal.issuer, User.subject == principal.subject)
            ).scalar_one_or_none()
            if user is None:
                raise AuthenticationUnavailable("Unable to initialize user identity.")
        else:
            changed = True
    else:
        if principal.email and principal.email != user.email:
            user.email = principal.email
            changed = True
        if principal.display_name and principal.display_name != user.display_name:
            user.display_name = principal.display_name
            changed = True

    owns_workspace = db.execute(
        select(Workspace.id)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.role == "owner",
            Workspace.is_demo.is_(False),
        )
        .limit(1)
    ).scalar_one_or_none()
    if owns_workspace is None:
        workspace = Workspace(
            name=_personal_workspace_name(principal.display_name or getattr(user, "display_name", None)),
            is_demo=False,
            created_by_user_id=user.id,
        )
        db.add(workspace)
        db.flush()
        db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role="owner"))
        changed = True

    if changed:
        try:
            db.commit()
        except SQLAlchemyError as error:
            db.rollback()
            raise AuthenticationUnavailable("Unable to initialize user identity.") from error
    return replace(principal, user_id=user.id)


def _authentication_http_error(error: AuthenticationError) -> HTTPException:
    if isinstance(error, AuthenticationUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication is unavailable.")
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    """FastAPI dependency that authenticates and initializes the local principal."""

    settings = get_settings()
    try:
        if settings.auth_enabled:
            token = extract_access_token(request, settings)
            if not token:
                raise AuthenticationError("Missing access token.")
            principal = verify_cognito_access_token(token, settings)
        else:
            principal = _development_principal(settings)
        principal = upsert_principal_user(db, principal)
    except AuthenticationError as error:
        raise _authentication_http_error(error) from error
    except SQLAlchemyError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication is unavailable.") from error

    request.state.principal = principal
    return principal


def _normalize_minimum_role(minimum_role: str) -> WorkspaceRole:
    if minimum_role not in VALID_WORKSPACE_ROLES:
        raise ValueError(f"Unknown workspace role: {minimum_role}")
    return minimum_role  # type: ignore[return-value]


def require_workspace_role(
    db: Session,
    principal: Principal,
    workspace_id: int,
    minimum_role: WorkspaceRole = "viewer",
) -> WorkspaceAccess:
    """Load a workspace and enforce a minimum role without leaking membership."""

    _, _, Workspace, WorkspaceMembership = _tenancy_models()
    minimum_role = _normalize_minimum_role(minimum_role)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    if bool(workspace.is_demo):
        effective_role: WorkspaceRole = "viewer"
        is_virtual = True
    else:
        if principal.user_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        membership = db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == principal.user_id,
            )
        ).scalar_one_or_none()
        if membership is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        effective_role = _normalize_minimum_role(membership.role)
        is_virtual = False

    if _ROLE_RANK[effective_role] < _ROLE_RANK[minimum_role]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient workspace permissions")
    return WorkspaceAccess(
        workspace=workspace,
        role=effective_role,
        is_demo=bool(workspace.is_demo),
        is_virtual_membership=is_virtual,
    )


def get_authorized_connection(
    db: Session,
    principal: Principal,
    connection_id: int,
    minimum_role: WorkspaceRole = "viewer",
) -> Connection:
    """Load a connection only after its containing workspace is authorized."""

    Connection, _, _, _ = _tenancy_models()
    connection = db.get(Connection, connection_id)
    if connection is None or getattr(connection, "workspace_id", None) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    try:
        require_workspace_role(db, principal, connection.workspace_id, minimum_role)
    except HTTPException as error:
        # A caller may know an id but not learn whether the inaccessible object
        # belongs to an existing workspace.  Insufficient privileges inside a
        # workspace they can see remain a normal 403.
        if error.status_code == status.HTTP_404_NOT_FOUND:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found") from error
        raise
    return connection


def workspace_role_dependency(minimum_role: WorkspaceRole = "viewer") -> Callable[..., WorkspaceAccess]:
    """Create a FastAPI dependency for routes with a ``workspace_id`` parameter."""

    def dependency(
        workspace_id: int,
        principal: Principal = Depends(get_current_principal),
        db: Session = Depends(get_db),
    ) -> WorkspaceAccess:
        return require_workspace_role(db, principal, workspace_id, minimum_role)

    return dependency


def connection_role_dependency(minimum_role: WorkspaceRole = "viewer") -> Callable[..., Connection]:
    """Create a FastAPI dependency for routes with a ``connection_id`` parameter."""

    def dependency(
        connection_id: int,
        principal: Principal = Depends(get_current_principal),
        db: Session = Depends(get_db),
    ) -> Connection:
        return get_authorized_connection(db, principal, connection_id, minimum_role)

    return dependency


def request_id_for(request: Request) -> str:
    """Return a safe correlation id without trusting arbitrary client input."""

    existing = getattr(request.state, "request_id", None)
    if (
        isinstance(existing, str)
        and 1 <= len(existing) <= 128
        and existing.isascii()
        and existing.replace("-", "").replace("_", "").isalnum()
    ):
        return existing
    supplied = request.headers.get("x-request-id", "")
    if 1 <= len(supplied) <= 128 and supplied.isascii() and supplied.replace("-", "").replace("_", "").isalnum():
        request_id = supplied
    else:
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    return request_id


async def enforce_csrf(request: Request) -> None:
    """Protect cookie-authenticated unsafe requests with origin + CSRF checks.

    Routes opt into this dependency for mutations.  Bearer-token clients are
    intentionally exempt because browsers cannot attach that token cross-site.
    """

    settings = get_settings()
    if not settings.auth_enabled or request.method.upper() in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return
    if request.headers.get("authorization"):
        return
    origin = request.headers.get("origin")
    if not origin or origin.rstrip("/") not in {item.rstrip("/") for item in settings.cors_origin_list}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid request origin")
    expected = request.cookies.get(settings.auth_csrf_cookie_name)
    provided = request.headers.get(settings.auth_csrf_header_name)
    if not expected or not provided or not secrets.compare_digest(expected, provided):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")


# Backwards-friendly name for route code that reads better in Depends(...).
require_csrf = enforce_csrf
