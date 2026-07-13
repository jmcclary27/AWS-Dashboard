"use client";

import { useState } from "react";

import { useConnection } from "@/components/connection-provider";
import { AccountTableRow, ErrorState, LoadingState, PageHeader, Panel, StatusPill } from "@/components/ui";
import { apiRequest, useApiData, withConnectionId } from "@/lib/api";
import type { AccountsResponse, SyncResponse } from "@/lib/types";

export default function AccountsPage() {
  const {
    loading: connectionLoading,
    error: connectionError,
    selectedConnection,
    selectedConnectionId,
    canEditWorkspace,
    selectedWorkspace,
    refreshConnections
  } = useConnection();
  const accounts = useApiData<AccountsResponse>(selectedConnectionId ? withConnectionId("/accounts", selectedConnectionId) : null);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function syncConnection() {
    if (!selectedConnectionId) return;
    setSyncing(true);
    setMessage(null);
    try {
      const result = await apiRequest<SyncResponse>(`/connections/${selectedConnectionId}/sync`, { method: "POST" });
      setMessage(
        result.message
          ? `Sync finished with ${result.status}: ${result.message}`
          : `Synced ${result.accounts_synced} accounts across a ${result.window_days}-day window.`
      );
      accounts.refresh();
      refreshConnections();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to sync connection");
    } finally {
      setSyncing(false);
    }
  }

  if (connectionError) return <ErrorState message={connectionError} />;
  if (connectionLoading) return <LoadingState label="Resolving the active connection..." />;
  if (!selectedConnectionId || !selectedConnection) {
    return <ErrorState message="No available connection in this workspace. Create one from Settings." />;
  }
  if (accounts.loading) return <LoadingState label="Loading account inventory..." />;
  if (accounts.error || !accounts.data) return <ErrorState message={accounts.error ?? "Unable to load accounts."} />;

  const canSync = canEditWorkspace && !selectedWorkspace?.read_only && selectedConnection.kind !== "demo";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Account Inventory"
        title={`${selectedConnection.name} account membership`}
        description="Accounts are visible only through the selected authorized connection. Account-specific credentials are never exposed from this view."
        action={
          canSync ? (
            <button
              onClick={syncConnection}
              disabled={syncing}
              className="rounded-full bg-slate-900 px-5 py-3 text-sm font-medium text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {syncing ? "Syncing..." : selectedConnection.kind === "org_management" ? "Sync Organization" : "Sync Connection"}
            </button>
          ) : undefined
        }
      />

      {message ? <div className="glass-panel rounded-[24px] px-5 py-4 text-sm text-slate-700">{message}</div> : null}

      <div className="grid gap-6 xl:grid-cols-[0.75fr_1.25fr]">
        <Panel title="Connection posture" subtitle="Mutations are available only to editors and owners in non-demo workspaces.">
          <div className="space-y-3 rounded-[24px] bg-white/75 p-5 text-sm leading-7 text-slate-600">
            <p><strong>Workspace:</strong> {selectedWorkspace?.name ?? "Unknown"}</p>
            <p><strong>Kind:</strong> {selectedConnection.kind}</p>
            <p><strong>Team Tag Key:</strong> {selectedConnection.team_tag_key}</p>
            <p><strong>Billing Truth:</strong> {selectedConnection.billing_truth_mode}</p>
            <p><strong>Accounts In Scope:</strong> {selectedConnection.account_count}</p>
            {selectedConnection.primary_account_name ? <p><strong>Primary Account:</strong> {selectedConnection.primary_account_name}</p> : null}
            <div className="flex flex-wrap gap-2 pt-2">
              <StatusPill label={selectedConnection.kind} />
              <StatusPill label={selectedConnection.enabled ? "enabled" : "disabled"} />
              <StatusPill label={selectedWorkspace?.read_only ? "read-only" : canEditWorkspace ? "can manage" : "viewer"} />
            </div>
          </div>
        </Panel>

        <Panel title="Visible accounts" subtitle="30-day usage stays operational, while direct payable fields exclude shared payer-level offsets and bill adjustments.">
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr className="text-left text-xs uppercase tracking-[0.18em] text-slate-500">
                  <th className="pb-4 pr-4">Account</th><th className="pb-4 pr-4">30d usage</th><th className="pb-4 pr-4">Gross MTD</th>
                  <th className="pb-4 pr-4">Direct due MTD</th><th className="pb-4 pr-4">Direct month-end</th><th className="pb-4 pr-4">Unallocated</th>
                  <th className="pb-4 pr-4">Last sync</th><th className="pb-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {accounts.data.items.map((account) => <AccountTableRow key={account.id} account={account} onSync={() => undefined} showSyncAction={false} />)}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}
