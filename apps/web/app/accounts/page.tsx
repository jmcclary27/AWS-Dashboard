"use client";

import { useState } from "react";

import { useConnection } from "@/components/connection-provider";
import { AccountTableRow, ErrorState, LoadingState, PageHeader, Panel, StatusPill } from "@/components/ui";
import { apiRequest, useApiData, withConnectionId } from "@/lib/api";
import type { AccountsResponse, SyncResponse } from "@/lib/types";

const initialForm = {
  display_name: "",
  aws_account_id: "",
  role_arn: "",
  external_id: "",
  team_tag_key: "Team"
};

export default function AccountsPage() {
  const { loading: connectionLoading, error: connectionError, selectedConnection, selectedConnectionId, refreshConnections } = useConnection();
  const accounts = useApiData<AccountsResponse>(selectedConnectionId ? withConnectionId("/accounts", selectedConnectionId) : null);
  const [form, setForm] = useState(initialForm);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  async function createAccount(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setMessage(null);

    try {
      await apiRequest("/accounts", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          role_arn: form.role_arn || null,
          external_id: form.external_id || null
        })
      });
      setForm(initialForm);
      setMessage("Account created and attached to the demo connection.");
      accounts.refresh();
      refreshConnections();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create account");
    } finally {
      setSubmitting(false);
    }
  }

  async function syncAccount(accountId: number) {
    try {
      const result = await apiRequest<SyncResponse>(`/accounts/${accountId}/sync`, { method: "POST" });
      setMessage(`Synced ${result.accounts_synced} demo account across a ${result.window_days}-day window.`);
      accounts.refresh();
      refreshConnections();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to sync account");
    }
  }

  async function syncConnection() {
    if (!selectedConnectionId) {
      return;
    }
    setSyncing(true);
    try {
      const result = await apiRequest<SyncResponse>(`/connections/${selectedConnectionId}/sync`, {
        method: "POST",
        body: JSON.stringify({ days: 14 })
      });
      setMessage(
        result.message
          ? `Synced ${result.accounts_synced} accounts with status ${result.status}: ${result.message}`
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

  if (connectionError) {
    return <ErrorState message={connectionError} />;
  }

  if (connectionLoading) {
    return <LoadingState label="Resolving the active connection..." />;
  }

  if (!selectedConnectionId) {
    return <ErrorState message="No available connection. Initialize the demo dataset or create an AWS connection." />;
  }

  if (accounts.loading) {
    return <LoadingState label="Loading account inventory..." />;
  }

  if (accounts.error || !accounts.data || !selectedConnection) {
    return <ErrorState message={accounts.error ?? "Unable to load accounts."} />;
  }

  const showDemoForm = selectedConnection.kind === "demo";
  const showPerAccountSync = selectedConnection.kind === "demo";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Account Inventory"
        title={`${selectedConnection.name} account membership`}
        description="Canonical AWS accounts stay separate from ingestion scope, so the same account can exist in multiple connections without corrupting totals."
        action={
          <button
            onClick={syncConnection}
            disabled={syncing}
            className="rounded-full bg-slate-900 px-5 py-3 text-sm font-medium text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {syncing ? "Syncing..." : selectedConnection.kind === "org_management" ? "Sync Organization" : "Sync Connection"}
          </button>
        }
      />

      {message ? <div className="glass-panel rounded-[24px] px-5 py-4 text-sm text-slate-700">{message}</div> : null}

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <Panel
          title={showDemoForm ? "Add demo account" : "Connection posture"}
          subtitle={showDemoForm ? "Legacy demo onboarding remains available on the built-in demo connection." : "Membership and sync behavior for the selected connection."}
        >
          {showDemoForm ? (
            <form className="grid gap-4" onSubmit={createAccount}>
              <input
                value={form.display_name}
                onChange={(event) => setForm((current) => ({ ...current, display_name: event.target.value }))}
                placeholder="Display name"
                className="rounded-2xl border border-slate-200 bg-white/70 px-4 py-3"
                required
              />
              <input
                value={form.aws_account_id}
                onChange={(event) => setForm((current) => ({ ...current, aws_account_id: event.target.value }))}
                placeholder="12-digit AWS account id"
                className="rounded-2xl border border-slate-200 bg-white/70 px-4 py-3"
                maxLength={12}
                required
              />
              <input
                value={form.role_arn}
                onChange={(event) => setForm((current) => ({ ...current, role_arn: event.target.value }))}
                placeholder="Role ARN (optional for demo)"
                className="rounded-2xl border border-slate-200 bg-white/70 px-4 py-3"
              />
              <div className="grid gap-4 md:grid-cols-2">
                <input
                  value={form.external_id}
                  onChange={(event) => setForm((current) => ({ ...current, external_id: event.target.value }))}
                  placeholder="External id"
                  className="rounded-2xl border border-slate-200 bg-white/70 px-4 py-3"
                />
                <input
                  value={form.team_tag_key}
                  onChange={(event) => setForm((current) => ({ ...current, team_tag_key: event.target.value }))}
                  placeholder="Team tag key"
                  className="rounded-2xl border border-slate-200 bg-white/70 px-4 py-3"
                />
              </div>
              <button
                type="submit"
                disabled={submitting}
                className="rounded-full bg-blue-700 px-5 py-3 text-sm font-medium text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:bg-blue-300"
              >
                {submitting ? "Creating..." : "Create Account"}
              </button>
            </form>
          ) : (
            <div className="space-y-3 rounded-[24px] bg-white/75 p-5 text-sm leading-7 text-slate-600">
              <p><strong>Kind:</strong> {selectedConnection.kind}</p>
              <p><strong>Team Tag Key:</strong> {selectedConnection.team_tag_key}</p>
              <p><strong>Accounts In Scope:</strong> {selectedConnection.account_count}</p>
              {selectedConnection.primary_account_name ? <p><strong>Primary Account:</strong> {selectedConnection.primary_account_name}</p> : null}
              <div className="flex flex-wrap gap-2 pt-2">
                <StatusPill label={selectedConnection.kind} />
                <StatusPill label={selectedConnection.enabled ? "enabled" : "disabled"} />
              </div>
            </div>
          )}
        </Panel>

        <Panel title="Visible accounts" subtitle="Connection membership, 30-day spend, forecast, unallocated share, and latest sync status">
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr className="text-left text-xs uppercase tracking-[0.18em] text-slate-500">
                  <th className="pb-4 pr-4">Account</th>
                  <th className="pb-4 pr-4">30d spend</th>
                  <th className="pb-4 pr-4">Forecast</th>
                  <th className="pb-4 pr-4">Unallocated</th>
                  <th className="pb-4 pr-4">Last sync</th>
                  <th className="pb-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {accounts.data.items.map((account) => (
                  <AccountTableRow key={account.id} account={account} onSync={syncAccount} showSyncAction={showPerAccountSync} />
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}
