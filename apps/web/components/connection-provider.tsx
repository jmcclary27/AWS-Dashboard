"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, startTransition, useContext, useEffect, useMemo, type ReactNode } from "react";

import { useApiData } from "@/lib/api";
import type { ConnectionItem, ConnectionsResponse } from "@/lib/types";

type ConnectionContextValue = {
  connections: ConnectionItem[];
  selectedConnectionId: number | null;
  selectedConnection: ConnectionItem | null;
  loading: boolean;
  error: string | null;
  setSelectedConnectionId: (connectionId: number) => void;
  refreshConnections: () => void;
};

const ConnectionContext = createContext<ConnectionContextValue | null>(null);

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const connections = useApiData<ConnectionsResponse>("/connections");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const connectionIdValue = searchParams.get("connection_id");
  const queryConnectionId = connectionIdValue && !Number.isNaN(Number(connectionIdValue)) ? Number(connectionIdValue) : null;

  const preferredConnection = useMemo(
    () =>
      connections.data?.items.find((item) => item.enabled && item.kind !== "demo") ??
      connections.data?.items.find((item) => item.enabled) ??
      connections.data?.items[0] ??
      null,
    [connections.data]
  );

  const selectedConnectionId = queryConnectionId ?? preferredConnection?.id ?? null;

  const selectedConnection = useMemo(
    () => connections.data?.items.find((item) => item.id === selectedConnectionId) ?? null,
    [connections.data, selectedConnectionId]
  );

  function setSelectedConnectionId(connectionId: number) {
    const nextParams = new URLSearchParams(searchParams.toString());
    nextParams.set("connection_id", String(connectionId));
    startTransition(() => {
      router.replace(`${pathname}?${nextParams.toString()}`);
    });
  }

  useEffect(() => {
    if (connections.loading || !connections.data || !preferredConnection) {
      return;
    }

    const queryMatchesKnownConnection = queryConnectionId
      ? connections.data.items.some((item) => item.id === queryConnectionId)
      : false;

    if (!queryConnectionId || !queryMatchesKnownConnection) {
      setSelectedConnectionId(preferredConnection.id);
    }
  }, [connections.data, connections.loading, preferredConnection, queryConnectionId, pathname, router, searchParams]);

  const value = useMemo(
    () => ({
      connections: connections.data?.items ?? [],
      selectedConnectionId,
      selectedConnection,
      loading: connections.loading,
      error: connections.error,
      setSelectedConnectionId,
      refreshConnections: connections.refresh
    }),
    [connections.data, connections.error, connections.loading, connections.refresh, selectedConnection, selectedConnectionId]
  );

  return <ConnectionContext.Provider value={value}>{children}</ConnectionContext.Provider>;
}

export function useConnection() {
  const context = useContext(ConnectionContext);
  if (!context) {
    throw new Error("useConnection must be used within ConnectionProvider");
  }
  return context;
}
