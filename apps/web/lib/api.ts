"use client";

import { useEffect, useState } from "react";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
const CSRF_COOKIE_NAME = "aws_dashboard_csrf";

let pendingRefresh: Promise<boolean> | null = null;

export class AuthRequiredError extends Error {
  readonly status = 401;

  constructor(message = "Your session has expired. Please sign in again.") {
    super(message);
    this.name = "AuthRequiredError";
  }
}

export function isAuthRequiredError(error: unknown): error is AuthRequiredError {
  return error instanceof AuthRequiredError;
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") {
    return null;
  }

  const prefix = `${encodeURIComponent(name)}=`;
  const cookie = document.cookie.split("; ").find((value) => value.startsWith(prefix));
  if (!cookie) {
    return null;
  }

  try {
    return decodeURIComponent(cookie.slice(prefix.length));
  } catch {
    return null;
  }
}

function isMutation(method: string | undefined): boolean {
  const normalizedMethod = (method ?? "GET").toUpperCase();
  return !["GET", "HEAD", "OPTIONS"].includes(normalizedMethod);
}

function requestHeaders(init?: RequestInit): Headers {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (isMutation(init?.method)) {
    const csrfToken = readCookie(CSRF_COOKIE_NAME);
    if (csrfToken) {
      headers.set("X-CSRF-Token", csrfToken);
    }
  }
  return headers;
}

async function sendApiRequest(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: requestHeaders(init),
    credentials: "include",
    cache: "no-store"
  });
}

export async function refreshAuthSession(): Promise<boolean> {
  if (pendingRefresh) {
    return pendingRefresh;
  }

  pendingRefresh = (async () => {
    const csrfToken = readCookie(CSRF_COOKIE_NAME);
    if (!csrfToken) {
      return false;
    }

    try {
      const response = await fetch("/auth/refresh", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
        credentials: "same-origin",
        cache: "no-store"
      });
      return response.ok;
    } catch {
      return false;
    }
  })();

  try {
    return await pendingRefresh;
  } finally {
    pendingRefresh = null;
  }
}

export function redirectToLogin(): void {
  if (typeof window === "undefined" || window.location.pathname.startsWith("/auth/")) {
    return;
  }

  const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  window.location.assign(`/auth/login?returnTo=${encodeURIComponent(returnTo)}`);
}

async function failedResponseMessage(response: Response): Promise<string> {
  const message = await response.text();
  return message || `Request failed with status ${response.status}`;
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response = await sendApiRequest(path, init);

  if (response.status === 401 && (await refreshAuthSession())) {
    response = await sendApiRequest(path, init);
  }

  if (!response.ok) {
    if (response.status === 401) {
      const error = new AuthRequiredError();
      redirectToLogin();
      throw error;
    }
    throw new Error(await failedResponseMessage(response));
  }

  return response.json() as Promise<T>;
}

export function withConnectionId(path: string, connectionId: number | null | undefined) {
  if (!connectionId) {
    return path;
  }
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}connection_id=${connectionId}`;
}

export function useApiData<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);

  useEffect(() => {
    if (!path) {
      setLoading(false);
      setError(null);
      setData(null);
      return;
    }

    let active = true;
    const requestPath = path;

    async function load() {
      setLoading(true);
      setError(null);

      try {
        const nextData = await apiRequest<T>(requestPath);
        if (active) {
          setData(nextData);
        }
      } catch (nextError) {
        if (active) {
          setError(nextError instanceof Error ? nextError.message : "Unknown error");
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    load();
    return () => {
      active = false;
    };
  }, [path, refreshIndex]);

  return {
    data,
    loading,
    error,
    refresh: () => setRefreshIndex((value) => value + 1)
  };
}
