import { createHash, randomBytes, timingSafeEqual } from "node:crypto";

import type { NextRequest, NextResponse } from "next/server";

/**
 * These names are also part of the API integration contract.  The API reads
 * the access-token and CSRF cookies directly because it is served behind the
 * same public host as the web application.
 */
export const AUTH_COOKIE_NAMES = {
  accessToken: "aws_dashboard_access_token",
  refreshToken: "aws_dashboard_refresh_token",
  csrfToken: "aws_dashboard_csrf",
  oauthState: "aws_dashboard_oauth_state",
  pkceVerifier: "aws_dashboard_pkce_verifier",
  returnTo: "aws_dashboard_auth_return_to"
} as const;

const OAUTH_TRANSACTION_TTL_SECONDS = 10 * 60;
const DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 60 * 60;
const DEFAULT_REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60;
const MAX_ACCESS_TOKEN_TTL_SECONDS = 24 * 60 * 60;

export type CognitoConfig = {
  authorizationEndpoint: string;
  tokenEndpoint: string;
  logoutEndpoint: string;
  revokeEndpoint: string;
  clientId: string;
  redirectUri: string;
  logoutUri: string;
  scopes: string[];
};

export type CognitoTokenSet = {
  accessToken: string;
  refreshToken: string | null;
  expiresIn: number;
};

export class AuthConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthConfigurationError";
  }
}

export class CognitoTokenExchangeError extends Error {
  constructor(
    public readonly status: number,
    public readonly invalidGrant: boolean
  ) {
    super("Cognito token exchange failed.");
    this.name = "CognitoTokenExchangeError";
  }
}

function requireEnvironmentValue(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new AuthConfigurationError(`${name} must be configured.`);
  }
  return value;
}

function parseUrl(value: string, name: string): URL {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" && url.protocol !== "http:") {
      throw new Error("unsupported protocol");
    }
    return url;
  } catch {
    throw new AuthConfigurationError(`${name} must be an absolute HTTP(S) URL.`);
  }
}

function cognitoDomainUrl(): URL {
  const configuredDomain = requireEnvironmentValue("COGNITO_DOMAIN");
  const value = configuredDomain.includes("://") ? configuredDomain : `https://${configuredDomain}`;
  const url = parseUrl(value, "COGNITO_DOMAIN");

  if (url.search || url.hash) {
    throw new AuthConfigurationError("COGNITO_DOMAIN cannot include a query string or fragment.");
  }

  return url;
}

function endpointFromEnvironment(name: string, domain: URL, path: string): string {
  const configuredEndpoint = process.env[name]?.trim();
  if (configuredEndpoint) {
    return parseUrl(configuredEndpoint, name).toString();
  }

  return new URL(path, domain).toString();
}

function configuredScopes(): string[] {
  const configured = process.env.COGNITO_SCOPES?.trim() || "openid email profile";
  const scopes = configured.split(/\s+/).filter(Boolean);
  if (!scopes.includes("openid")) {
    throw new AuthConfigurationError("COGNITO_SCOPES must include openid.");
  }
  return scopes;
}

export function getCognitoConfig(): CognitoConfig {
  const domain = cognitoDomainUrl();
  const redirectUri = parseUrl(requireEnvironmentValue("COGNITO_REDIRECT_URI"), "COGNITO_REDIRECT_URI");
  const configuredLogoutUri = process.env.COGNITO_LOGOUT_URI?.trim();
  const logoutUri = configuredLogoutUri
    ? parseUrl(configuredLogoutUri, "COGNITO_LOGOUT_URI")
    : new URL("/", redirectUri);

  return {
    authorizationEndpoint: endpointFromEnvironment("COGNITO_AUTHORIZATION_ENDPOINT", domain, "/oauth2/authorize"),
    tokenEndpoint: endpointFromEnvironment("COGNITO_TOKEN_ENDPOINT", domain, "/oauth2/token"),
    logoutEndpoint: endpointFromEnvironment("COGNITO_LOGOUT_ENDPOINT", domain, "/logout"),
    revokeEndpoint: endpointFromEnvironment("COGNITO_REVOKE_ENDPOINT", domain, "/oauth2/revoke"),
    clientId: requireEnvironmentValue("COGNITO_CLIENT_ID"),
    redirectUri: redirectUri.toString(),
    logoutUri: logoutUri.toString(),
    scopes: configuredScopes()
  };
}

function configuredBoolean(name: string): boolean | null {
  const value = process.env[name]?.trim().toLowerCase();
  if (!value) {
    return null;
  }
  if (value === "true" || value === "1") {
    return true;
  }
  if (value === "false" || value === "0") {
    return false;
  }
  throw new AuthConfigurationError(`${name} must be true or false.`);
}

function isLocalHttpCallback(): boolean {
  const redirectUri = process.env.COGNITO_REDIRECT_URI?.trim();
  if (!redirectUri) {
    return false;
  }
  try {
    const url = new URL(redirectUri);
    return (
      url.protocol === "http:" &&
      ["localhost", "127.0.0.1", "::1"].includes(url.hostname.toLowerCase())
    );
  } catch {
    return false;
  }
}

function secureCookies(): boolean {
  // Production session cookies must never be downgraded by configuration. A
  // Compose image also runs with NODE_ENV=production, so permit the explicitly
  // local HTTP callback URI to use non-Secure cookies for Cognito development.
  if (process.env.NODE_ENV === "production" && !isLocalHttpCallback()) {
    return true;
  }
  return configuredBoolean("AUTH_COOKIE_SECURE") ?? false;
}

function configuredPositiveInteger(name: string, fallback: number, maximum?: number): number {
  const rawValue = process.env[name]?.trim();
  if (!rawValue) {
    return fallback;
  }

  const value = Number(rawValue);
  if (!Number.isSafeInteger(value) || value <= 0 || (maximum !== undefined && value > maximum)) {
    throw new AuthConfigurationError(`${name} must be a positive integer${maximum ? ` no greater than ${maximum}` : ""}.`);
  }
  return value;
}

function baseCookieOptions(httpOnly: boolean) {
  return {
    httpOnly,
    path: "/",
    sameSite: "lax" as const,
    secure: secureCookies()
  };
}

function setCookie(response: NextResponse, name: string, value: string, maxAge: number, httpOnly: boolean) {
  response.cookies.set({
    name,
    value,
    maxAge,
    ...baseCookieOptions(httpOnly)
  });
}

function clearCookie(response: NextResponse, name: string, httpOnly: boolean) {
  response.cookies.set({
    name,
    value: "",
    maxAge: 0,
    ...baseCookieOptions(httpOnly)
  });
}

export function generateRandomToken(bytes = 32): string {
  return randomBytes(bytes).toString("base64url");
}

export function createPkceChallenge(verifier: string): string {
  return createHash("sha256").update(verifier).digest("base64url");
}

export function safeReturnTo(candidate: string | null | undefined): string {
  if (!candidate) {
    return "/dashboard";
  }

  try {
    const base = new URL("https://dashboard.invalid");
    const target = new URL(candidate, base);
    if (target.origin !== base.origin) {
      return "/dashboard";
    }
    return `${target.pathname}${target.search}${target.hash}`;
  } catch {
    return "/dashboard";
  }
}

export function timingSafeTokenEqual(left: string | undefined, right: string | undefined): boolean {
  if (!left || !right) {
    return false;
  }

  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer);
}

export function setOAuthTransactionCookies(
  response: NextResponse,
  transaction: { state: string; verifier: string; returnTo: string }
) {
  setCookie(response, AUTH_COOKIE_NAMES.oauthState, transaction.state, OAUTH_TRANSACTION_TTL_SECONDS, true);
  setCookie(response, AUTH_COOKIE_NAMES.pkceVerifier, transaction.verifier, OAUTH_TRANSACTION_TTL_SECONDS, true);
  setCookie(response, AUTH_COOKIE_NAMES.returnTo, transaction.returnTo, OAUTH_TRANSACTION_TTL_SECONDS, true);
}

export function clearOAuthTransactionCookies(response: NextResponse) {
  clearCookie(response, AUTH_COOKIE_NAMES.oauthState, true);
  clearCookie(response, AUTH_COOKIE_NAMES.pkceVerifier, true);
  clearCookie(response, AUTH_COOKIE_NAMES.returnTo, true);
}

export function setCsrfCookie(response: NextResponse) {
  setCookie(
    response,
    AUTH_COOKIE_NAMES.csrfToken,
    generateRandomToken(),
    configuredPositiveInteger("COGNITO_REFRESH_TOKEN_MAX_AGE_SECONDS", DEFAULT_REFRESH_TOKEN_TTL_SECONDS),
    false
  );
}

export function setSessionCookies(
  response: NextResponse,
  tokenSet: CognitoTokenSet,
  existingRefreshToken?: string | null
) {
  const accessTokenTtl = Math.min(
    Math.max(1, tokenSet.expiresIn || DEFAULT_ACCESS_TOKEN_TTL_SECONDS),
    MAX_ACCESS_TOKEN_TTL_SECONDS
  );
  setCookie(response, AUTH_COOKIE_NAMES.accessToken, tokenSet.accessToken, accessTokenTtl, true);

  const refreshToken = tokenSet.refreshToken ?? existingRefreshToken;
  if (refreshToken) {
    const refreshTtl = configuredPositiveInteger(
      "COGNITO_REFRESH_TOKEN_MAX_AGE_SECONDS",
      DEFAULT_REFRESH_TOKEN_TTL_SECONDS
    );
    setCookie(response, AUTH_COOKIE_NAMES.refreshToken, refreshToken, refreshTtl, true);
  }
}

export function clearSessionCookies(response: NextResponse) {
  clearCookie(response, AUTH_COOKIE_NAMES.accessToken, true);
  clearCookie(response, AUTH_COOKIE_NAMES.refreshToken, true);
  clearCookie(response, AUTH_COOKIE_NAMES.csrfToken, false);
}

function tokenExpiry(token: string | undefined): number | null {
  if (!token) {
    return null;
  }

  try {
    const segments = token.split(".");
    if (segments.length !== 3) {
      return null;
    }
    const payload = JSON.parse(Buffer.from(segments[1], "base64url").toString("utf8")) as { exp?: unknown };
    return typeof payload.exp === "number" && Number.isFinite(payload.exp) ? payload.exp : null;
  } catch {
    return null;
  }
}

export function accessSessionFromRequest(request: NextRequest): { authenticated: boolean; expiresAt: string | null } {
  const expiresAtEpoch = tokenExpiry(request.cookies.get(AUTH_COOKIE_NAMES.accessToken)?.value);
  if (!expiresAtEpoch || expiresAtEpoch * 1000 <= Date.now()) {
    return { authenticated: false, expiresAt: null };
  }
  return { authenticated: true, expiresAt: new Date(expiresAtEpoch * 1000).toISOString() };
}

function configuredAppOrigin(): string | null {
  const redirectUri = process.env.COGNITO_REDIRECT_URI?.trim();
  if (!redirectUri) {
    return null;
  }
  try {
    return new URL(redirectUri).origin;
  } catch {
    return null;
  }
}

/**
 * State-changing auth handlers require both a double-submit CSRF token and an
 * Origin matching the configured application callback origin.
 */
export function hasTrustedMutationOrigin(request: NextRequest): boolean {
  const configuredOrigin = configuredAppOrigin();
  const requestOrigin = request.headers.get("origin");
  return Boolean(configuredOrigin && requestOrigin && configuredOrigin === requestOrigin);
}

export function hasValidCsrfRequest(request: NextRequest): boolean {
  return (
    hasTrustedMutationOrigin(request) &&
    timingSafeTokenEqual(
      request.headers.get("x-csrf-token") ?? undefined,
      request.cookies.get(AUTH_COOKIE_NAMES.csrfToken)?.value
    )
  );
}

function tokenResponseField(payload: Record<string, unknown>, field: string): string | null {
  const value = payload[field];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function tokenResponseExpiresIn(payload: Record<string, unknown>): number {
  const value = payload.expires_in;
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return Math.floor(value);
  }
  if (typeof value === "string" && /^\d+$/.test(value) && Number(value) > 0) {
    return Number(value);
  }
  return DEFAULT_ACCESS_TOKEN_TTL_SECONDS;
}

async function postTokenRequest(config: CognitoConfig, body: URLSearchParams): Promise<CognitoTokenSet> {
  let response: Response;
  try {
    response = await fetch(config.tokenEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
      cache: "no-store"
    });
  } catch {
    throw new CognitoTokenExchangeError(502, false);
  }

  let payload: Record<string, unknown> = {};
  try {
    const parsed = (await response.json()) as unknown;
    if (parsed && typeof parsed === "object") {
      payload = parsed as Record<string, unknown>;
    }
  } catch {
    // Treat a non-JSON response as an upstream failure below.
  }

  if (!response.ok) {
    const oauthError = tokenResponseField(payload, "error");
    throw new CognitoTokenExchangeError(response.status >= 500 ? 502 : response.status, oauthError === "invalid_grant");
  }

  const accessToken = tokenResponseField(payload, "access_token");
  if (!accessToken) {
    throw new CognitoTokenExchangeError(502, false);
  }

  return {
    accessToken,
    refreshToken: tokenResponseField(payload, "refresh_token"),
    expiresIn: tokenResponseExpiresIn(payload)
  };
}

export async function exchangeAuthorizationCode(
  config: CognitoConfig,
  code: string,
  verifier: string
): Promise<CognitoTokenSet> {
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: config.clientId,
    code,
    redirect_uri: config.redirectUri,
    code_verifier: verifier
  });
  return postTokenRequest(config, body);
}

export async function refreshAccessToken(config: CognitoConfig, refreshToken: string): Promise<CognitoTokenSet> {
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    client_id: config.clientId,
    refresh_token: refreshToken
  });
  return postTokenRequest(config, body);
}

export async function revokeRefreshToken(config: CognitoConfig, refreshToken: string): Promise<void> {
  try {
    await fetch(config.revokeEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ token: refreshToken, client_id: config.clientId }).toString(),
      cache: "no-store"
    });
  } catch {
    // Local logout must still succeed when Cognito is temporarily unavailable.
  }
}

export function cognitoAuthorizeUrl(config: CognitoConfig, state: string, challenge: string): string {
  const url = new URL(config.authorizationEndpoint);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("redirect_uri", config.redirectUri);
  url.searchParams.set("scope", config.scopes.join(" "));
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("code_challenge", challenge);
  return url.toString();
}

export function cognitoLogoutUrl(config: CognitoConfig): string {
  const url = new URL(config.logoutEndpoint);
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("logout_uri", config.logoutUri);
  return url.toString();
}

export function noStore(response: NextResponse): NextResponse {
  response.headers.set("Cache-Control", "no-store, private");
  return response;
}
