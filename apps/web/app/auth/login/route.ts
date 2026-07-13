import { NextRequest, NextResponse } from "next/server";

import {
  AuthConfigurationError,
  cognitoAuthorizeUrl,
  createPkceChallenge,
  generateRandomToken,
  getCognitoConfig,
  noStore,
  safeReturnTo,
  setOAuthTransactionCookies
} from "@/lib/auth";

export const runtime = "nodejs";

export function GET(request: NextRequest) {
  try {
    const config = getCognitoConfig();
    const state = generateRandomToken();
    const verifier = generateRandomToken(48);
    const returnTo = safeReturnTo(request.nextUrl.searchParams.get("returnTo"));
    const response = NextResponse.redirect(cognitoAuthorizeUrl(config, state, createPkceChallenge(verifier)), 302);

    setOAuthTransactionCookies(response, { state, verifier, returnTo });
    return noStore(response);
  } catch (error) {
    if (error instanceof AuthConfigurationError) {
      return noStore(NextResponse.json({ error: "authentication_not_configured" }, { status: 503 }));
    }
    return noStore(NextResponse.json({ error: "authentication_unavailable" }, { status: 502 }));
  }
}
