import { NextRequest, NextResponse } from "next/server";

import {
  AuthConfigurationError,
  AUTH_COOKIE_NAMES,
  clearOAuthTransactionCookies,
  exchangeAuthorizationCode,
  getCognitoConfig,
  noStore,
  safeReturnTo,
  setCsrfCookie,
  setSessionCookies,
  timingSafeTokenEqual
} from "@/lib/auth";

export const runtime = "nodejs";

function callbackRedirect(request: NextRequest, returnTo: string, errorCode?: string) {
  const target = new URL(safeReturnTo(returnTo), request.nextUrl.origin);
  if (errorCode) {
    target.searchParams.set("auth_error", errorCode);
  }
  return NextResponse.redirect(target, 303);
}

export async function GET(request: NextRequest) {
  const returnedState = request.nextUrl.searchParams.get("state") ?? undefined;
  const code = request.nextUrl.searchParams.get("code");
  const expectedState = request.cookies.get(AUTH_COOKIE_NAMES.oauthState)?.value;
  const verifier = request.cookies.get(AUTH_COOKIE_NAMES.pkceVerifier)?.value;
  const returnTo = request.cookies.get(AUTH_COOKIE_NAMES.returnTo)?.value;

  if (request.nextUrl.searchParams.has("error")) {
    const response = callbackRedirect(request, returnTo ?? "/dashboard", "sign_in_cancelled");
    clearOAuthTransactionCookies(response);
    return noStore(response);
  }

  if (!code || !verifier || !timingSafeTokenEqual(returnedState, expectedState)) {
    const response = callbackRedirect(request, returnTo ?? "/dashboard", "invalid_callback");
    clearOAuthTransactionCookies(response);
    return noStore(response);
  }

  try {
    const config = getCognitoConfig();
    const tokenSet = await exchangeAuthorizationCode(config, code, verifier);
    const response = callbackRedirect(request, returnTo ?? "/dashboard");

    setSessionCookies(response, tokenSet);
    setCsrfCookie(response);
    clearOAuthTransactionCookies(response);
    return noStore(response);
  } catch (error) {
    const response = callbackRedirect(
      request,
      returnTo ?? "/dashboard",
      error instanceof AuthConfigurationError ? "authentication_not_configured" : "sign_in_failed"
    );
    clearOAuthTransactionCookies(response);
    return noStore(response);
  }
}
