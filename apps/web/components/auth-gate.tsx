"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { refreshAuthSession } from "@/lib/api";

const authRequired = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";

export function AuthGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [ready, setReady] = useState(!authRequired);
  const [authenticated, setAuthenticated] = useState(!authRequired);

  useEffect(() => {
    if (!authRequired) {
      return;
    }
    let active = true;
    async function restoreSession() {
      try {
        const response = await fetch("/auth/session", { credentials: "same-origin", cache: "no-store" });
        const session = (response.ok ? await response.json() : { authenticated: false }) as { authenticated?: boolean };
        const restored = session.authenticated === true || (await refreshAuthSession());
        if (active) {
          setAuthenticated(restored);
          setReady(true);
        }
      } catch {
        if (active) {
          setAuthenticated(false);
          setReady(true);
        }
      }
    }
    restoreSession();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!authRequired || !ready || authenticated) {
      return;
    }
    const suffix = searchParams.toString();
    const returnTo = `${pathname}${suffix ? `?${suffix}` : ""}`;
    window.location.replace(`/auth/login?returnTo=${encodeURIComponent(returnTo)}`);
  }, [authenticated, pathname, ready, searchParams]);

  if (!ready || (authRequired && !authenticated)) {
    return <div className="page-loading">Checking your secure session…</div>;
  }
  return <>{children}</>;
}
