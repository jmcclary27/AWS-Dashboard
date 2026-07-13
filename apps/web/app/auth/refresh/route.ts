import { NextRequest, NextResponse } from "next/server";

import {
  AuthConfigurationError,
  AUTH_COOKIE_NAMES,
  CognitoTokenExchangeError,
  clearSessionCookies,
  getCognitoConfig,
  hasValidCsrfRequest,
  noStore,
  refreshAccessToken,
  setSessionCookies
} from "@/lib/auth";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  if (!hasValidCsrfRequest(request)) {
    return noStore(NextResponse.json({ error: "csrf_validation_failed" }, { status: 403 }));
  }

  const refreshToken = request.cookies.get(AUTH_COOKIE_NAMES.refreshToken)?.value;
  if (!refreshToken) {
    return noStore(NextResponse.json({ error: "authentication_required" }, { status: 401 }));
  }

  try {
    const tokenSet = await refreshAccessToken(getCognitoConfig(), refreshToken);
    const response = NextResponse.json({ authenticated: true });
    setSessionCookies(response, tokenSet, refreshToken);
    return noStore(response);
  } catch (error) {
    if (error instanceof CognitoTokenExchangeError && error.invalidGrant) {
      const response = NextResponse.json({ error: "authentication_required" }, { status: 401 });
      clearSessionCookies(response);
      return noStore(response);
    }
    if (error instanceof AuthConfigurationError) {
      return noStore(NextResponse.json({ error: "authentication_not_configured" }, { status: 503 }));
    }
    return noStore(NextResponse.json({ error: "authentication_unavailable" }, { status: 502 }));
  }
}
