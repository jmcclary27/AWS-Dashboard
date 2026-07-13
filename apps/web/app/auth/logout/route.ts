import { NextRequest, NextResponse } from "next/server";

import {
  AuthConfigurationError,
  AUTH_COOKIE_NAMES,
  clearOAuthTransactionCookies,
  clearSessionCookies,
  cognitoLogoutUrl,
  getCognitoConfig,
  hasValidCsrfRequest,
  noStore,
  revokeRefreshToken
} from "@/lib/auth";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  if (!hasValidCsrfRequest(request)) {
    return noStore(NextResponse.json({ error: "csrf_validation_failed" }, { status: 403 }));
  }

  const refreshToken = request.cookies.get(AUTH_COOKIE_NAMES.refreshToken)?.value;
  let logoutUrl: string | null = null;

  try {
    const config = getCognitoConfig();
    logoutUrl = cognitoLogoutUrl(config);
    if (refreshToken) {
      await revokeRefreshToken(config, refreshToken);
    }
  } catch (error) {
    if (!(error instanceof AuthConfigurationError)) {
      // A local logout remains valid even if Cognito's optional revoke request fails.
      logoutUrl = null;
    }
  }

  const response = NextResponse.json({ logoutUrl });
  clearSessionCookies(response);
  clearOAuthTransactionCookies(response);
  return noStore(response);
}
