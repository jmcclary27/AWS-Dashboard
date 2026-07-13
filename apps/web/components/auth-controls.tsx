"use client";

import { useEffect, useState } from "react";

const authRequired = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";
const csrfCookieName = "aws_dashboard_csrf";

function csrfToken(): string | null {
  const prefix = `${csrfCookieName}=`;
  const cookie = document.cookie.split("; ").find((value) => value.startsWith(prefix));
  return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : null;
}

export function AuthControls({ displayName }: { displayName: string | null }) {
  const [signingOut, setSigningOut] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);

  useEffect(() => {
    if (!authRequired) {
      return;
    }
    fetch("/auth/session", { credentials: "same-origin", cache: "no-store" })
      .then(async (response) => (response.ok ? response.json() : { authenticated: false }))
      .then((session: { authenticated?: boolean }) => setAuthenticated(session.authenticated === true))
      .catch(() => setAuthenticated(false));
  }, []);

  if (!authRequired) {
    return <span className="text-xs text-slate-500">Local development mode</span>;
  }

  async function logout() {
    setSigningOut(true);
    try {
      const response = await fetch("/auth/logout", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken() ?? "" },
        credentials: "same-origin"
      });
      const payload = response.ok ? ((await response.json()) as { logoutUrl?: string | null }) : null;
      window.location.assign(payload?.logoutUrl || "/");
    } finally {
      setSigningOut(false);
    }
  }

  if (!authenticated) {
    return <a href="/auth/login?returnTo=%2Fdashboard" className="rounded-full border border-slate-300 px-3 py-2 text-xs font-medium">Sign in</a>;
  }

  return (
    <div className="flex items-center gap-2">
      {displayName ? <span className="hidden text-xs text-slate-500 sm:inline">{displayName}</span> : null}
      <button
        onClick={logout}
        disabled={signingOut}
        className="rounded-full border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 disabled:text-slate-400"
      >
        {signingOut ? "Signing out…" : "Sign out"}
      </button>
    </div>
  );
}
