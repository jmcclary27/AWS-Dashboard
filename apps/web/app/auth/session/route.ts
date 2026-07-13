import { NextRequest, NextResponse } from "next/server";

import { accessSessionFromRequest, noStore } from "@/lib/auth";

export const runtime = "nodejs";

export function GET(request: NextRequest) {
  return noStore(NextResponse.json(accessSessionFromRequest(request)));
}
