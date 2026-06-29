"use client";

import { useEffect, useState } from "react";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    cache: "no-store"
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed with status ${response.status}`);
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
