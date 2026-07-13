from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    project_name: str = "AWS Collaboration Dashboard API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://dashboard:dashboard@localhost:5432/aws_dashboard"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    public_app_url: str = "http://localhost:3000"
    seed_days: int = 90

    # Authentication is deliberately opt-in for the existing local demo.  Every
    # deployed environment must set AUTH_ENABLED=true together with the Cognito
    # settings below; when it is enabled the API never falls back to a local
    # identity.
    auth_enabled: bool = False
    cognito_region: str = ""
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""
    cognito_issuer: str = ""
    cognito_jwks_url: str = ""
    # Managed Login has a separate domain from the user-pool issuer.  Access
    # tokens normally omit profile and email claims, so the API uses this
    # endpoint to retrieve the scoped, authenticated user-info response when
    # it needs a verified email for an invite.
    cognito_domain: str = ""
    cognito_userinfo_url: str = ""
    cognito_jwks_cache_seconds: int = 3600
    auth_clock_skew_seconds: int = 60

    # Names must match the Next.js auth handlers.  The access token is sent in
    # an HttpOnly cookie by the browser, while the CSRF token is intentionally
    # readable by JavaScript for the double-submit check on mutating requests.
    auth_access_cookie_name: str = "aws_dashboard_access_token"
    auth_refresh_cookie_name: str = "aws_dashboard_refresh_token"
    auth_csrf_cookie_name: str = "aws_dashboard_csrf"
    auth_csrf_header_name: str = "X-CSRF-Token"

    # This identity exists only while AUTH_ENABLED is false.  It preserves the
    # self-contained local demo and lets tests override get_current_principal
    # explicitly without provisioning Cognito.
    development_identity_issuer: str = "local-development"
    development_subject: str = "local-development-user"
    development_email: str = "developer@localhost"
    development_display_name: str = "Local Developer"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def resolved_cognito_issuer(self) -> str:
        """Return the canonical issuer URL used by Cognito access tokens."""

        if self.cognito_issuer.strip():
            return self.cognito_issuer.strip().rstrip("/")
        if self.cognito_region.strip() and self.cognito_user_pool_id.strip():
            return (
                f"https://cognito-idp.{self.cognito_region.strip()}.amazonaws.com/"
                f"{self.cognito_user_pool_id.strip()}"
            )
        return ""

    @property
    def resolved_cognito_jwks_url(self) -> str:
        """Return the configured JWKS endpoint or Cognito's standard endpoint."""

        if self.cognito_jwks_url.strip():
            return self.cognito_jwks_url.strip()
        issuer = self.resolved_cognito_issuer
        return f"{issuer}/.well-known/jwks.json" if issuer else ""

    @property
    def resolved_cognito_userinfo_url(self) -> str:
        """Return Managed Login's OAuth user-info endpoint when configured."""

        if self.cognito_userinfo_url.strip():
            return self.cognito_userinfo_url.strip().rstrip("/")
        domain = self.cognito_domain.strip().rstrip("/")
        if not domain:
            return ""
        if "://" not in domain:
            domain = f"https://{domain}"
        return f"{domain}/oauth2/userInfo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
