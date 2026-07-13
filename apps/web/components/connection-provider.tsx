"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, startTransition, useContext, useEffect, useMemo, type ReactNode } from "react";

import { useApiData } from "@/lib/api";
import type { ConnectionItem, ConnectionsResponse, MeResponse, WorkspaceItem } from "@/lib/types";

type ConnectionContextValue = {
  user: MeResponse["user"] | null;
  workspaces: WorkspaceItem[];
  selectedWorkspaceId: number | null;
  selectedWorkspace: WorkspaceItem | null;
  workspaceRole: "owner" | "editor" | "viewer" | null;
  canEditWorkspace: boolean;
  isWorkspaceOwner: boolean;
  connections: ConnectionItem[];
  selectedConnectionId: number | null;
  selectedConnection: ConnectionItem | null;
  loading: boolean;
  error: string | null;
  setSelectedWorkspaceId: (workspaceId: number) => void;
  setSelectedConnectionId: (connectionId: number) => void;
  refreshConnections: () => void;
  refreshWorkspace: () => void;
};

const ConnectionContext = createContext<ConnectionContextValue | null>(null);

function numericSearchParam(value: string | null): number | null {
  return value && /^\d+$/.test(value) ? Number(value) : null;
}

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const me = useApiData<MeResponse>("/me");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryWorkspaceId = numericSearchParam(searchParams.get("workspace_id"));
  const queryConnectionId = numericSearchParam(searchParams.get("connection_id"));

  const preferredWorkspace = useMemo(() => {
    const workspaces = me.data?.workspaces ?? [];
    // The unauthenticated local-development path is deliberately a demo-first
    // experience. A real Cognito user receives a private personal workspace
    // on first use and should land there instead.
    if (process.env.NEXT_PUBLIC_AUTH_ENABLED !== "true") {
      return workspaces.find((workspace) => workspace.is_demo) ?? workspaces[0] ?? null;
    }
    return workspaces.find((workspace) => !workspace.is_demo) ?? workspaces[0] ?? null;
  }, [me.data]);
  const selectedWorkspaceId = queryWorkspaceId ?? preferredWorkspace?.id ?? null;
  const selectedWorkspace = useMemo(
    () => me.data?.workspaces.find((workspace) => workspace.id === selectedWorkspaceId) ?? null,
    [me.data, selectedWorkspaceId]
  );
  const connections = useApiData<ConnectionsResponse>(
    selectedWorkspaceId ? `/connections?workspace_id=${selectedWorkspaceId}` : null
  );
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

  function replaceSearch(next: URLSearchParams) {
    startTransition(() => {
      const suffix = next.toString();
      router.replace(suffix ? `${pathname}?${suffix}` : pathname);
    });
  }

  function setSelectedWorkspaceId(workspaceId: number) {
    const next = new URLSearchParams(searchParams.toString());
    next.set("workspace_id", String(workspaceId));
    next.delete("connection_id");
    replaceSearch(next);
  }

  function setSelectedConnectionId(connectionId: number) {
    const next = new URLSearchParams(searchParams.toString());
    next.set("connection_id", String(connectionId));
    replaceSearch(next);
  }

  useEffect(() => {
    if (me.loading || !me.data || !preferredWorkspace) {
      return;
    }
    if (!queryWorkspaceId || !me.data.workspaces.some((workspace) => workspace.id === queryWorkspaceId)) {
      setSelectedWorkspaceId(preferredWorkspace.id);
    }
  }, [me.data, me.loading, preferredWorkspace, queryWorkspaceId]);

  useEffect(() => {
    if (connections.loading || !connections.data) {
      return;
    }
    const connectionIsKnown = queryConnectionId
      ? connections.data.items.some((connection) => connection.id === queryConnectionId)
      : false;
    if (preferredConnection && (!queryConnectionId || !connectionIsKnown)) {
      setSelectedConnectionId(preferredConnection.id);
    } else if (!preferredConnection && queryConnectionId) {
      const next = new URLSearchParams(searchParams.toString());
      next.delete("connection_id");
      replaceSearch(next);
    }
  }, [connections.data, connections.loading, preferredConnection, queryConnectionId, searchParams]);

  const value = useMemo<ConnectionContextValue>(
    () => ({
      user: me.data?.user ?? null,
      workspaces: me.data?.workspaces ?? [],
      selectedWorkspaceId,
      selectedWorkspace,
      workspaceRole: selectedWorkspace?.role ?? null,
      canEditWorkspace: selectedWorkspace?.role === "owner" || selectedWorkspace?.role === "editor",
      isWorkspaceOwner: selectedWorkspace?.role === "owner",
      connections: connections.data?.items ?? [],
      selectedConnectionId,
      selectedConnection,
      loading: me.loading || connections.loading,
      error: me.error ?? connections.error,
      setSelectedWorkspaceId,
      setSelectedConnectionId,
      refreshConnections: connections.refresh,
      refreshWorkspace: me.refresh
    }),
    [
      connections.data,
      connections.error,
      connections.loading,
      connections.refresh,
      me.data,
      me.error,
      me.loading,
      me.refresh,
      selectedConnection,
      selectedConnectionId,
      selectedWorkspace,
      selectedWorkspaceId
    ]
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
