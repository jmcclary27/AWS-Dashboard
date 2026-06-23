"use client";

import { useState } from "react";

import { AccountTableRow, ErrorState, LoadingState, PageHeader, Panel, StatusPill } from "@/components/ui";
import { apiRequest, useApiData } from "@/lib/api";
import type { AccountsResponse, SyncResponse } from "@/lib/types";

const initialForm = {
  display_name: "",
  aws_account_id: "",
  role_arn: "",
  external_id: "",
  team_tag_key: "Team"
};

export default function AccountsPage() {
  const accounts = useApiData<AccountsResponse>("/accounts");
  const [form, setForm] = useState(initialForm);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [syncingAll, setSyncingAll] = useState(false);

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
      setMessage("Account created. Run a sync to seed its rolling demo window.");
      accounts.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create account");
    } finally {
      setSubmitting(false);
    }
  }

  async function syncAccount(accountId: number) {
    try {
      const result = await apiRequest<SyncResponse>(`/accounts/${accountId}/sync`, { method: "POST" });
      setMessage(`Synced ${result.window_days} days of demo data for 1 account.`);
      accounts.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to sync account");
    }
  }

  async function syncAll() {
    setSyncingAll(true);
    try {
      const result = await apiRequest<SyncResponse>("/sync/all", { method: "POST" });
      setMessage(`Synced ${result.accounts_synced} accounts across a ${result.window_days}-day window.`);
      accounts.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to sync all accounts");
    } finally {
      setSyncingAll(false);
    }
  }

  if (accounts.loading) {
    return <LoadingState label="Loading account inventory..." />;
  }

  if (accounts.error || !accounts.data) {
    return <ErrorState message={accounts.error ?? "Unable to load accounts."} />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Account Inventory"
        title="Seeded today, collector-ready tomorrow."
        description="Manual account onboarding already matches the metadata we need for a later Cost Explorer collector: display name, AWS account id, billing role, external id, team tag key, and enabled state."
        action={
          <button
            onClick={syncAll}
            disabled={syncingAll}
            className="rounded-full bg-slate-900 px-5 py-3 text-sm font-medium text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {syncingAll ? "Syncing..." : "Sync All"}
          </button>
        }
      />

      {message ? (
        <div className="glass-panel rounded-[24px] px-5 py-4 text-sm text-slate-700">{message}</div>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <Panel title="Add account" subtitle="This form stays intentionally simple for the single-admin MVP.">
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
        </Panel>

        <Panel title="Tracked accounts" subtitle="30-day cost, forecast, unallocated share, and latest sync status">
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
                  <AccountTableRow key={account.id} account={account} onSync={syncAccount} />
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <StatusPill label="demo mode" />
            <StatusPill label="manual sync" />
            <StatusPill label="future role-based collector" />
          </div>
        </Panel>
      </div>
    </div>
  );
}

