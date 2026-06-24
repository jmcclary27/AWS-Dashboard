"use client";

import { useEffect, useMemo, useState } from "react";

import { useConnection } from "@/components/connection-provider";
import { ErrorState, LoadingState, PageHeader, Panel, StatusPill } from "@/components/ui";
import { apiRequest, useApiData, withConnectionId } from "@/lib/api";
import type { ConnectionItem, SyncResponse, SyncRunsResponse } from "@/lib/types";

type CreateFormState = {
  name: string;
  kind: "org_management" | "account_role";
  enabled: boolean;
  role_arn: string;
  external_id: string;
  billing_view_arn: string;
  team_tag_key: string;
  account_display_name: string;
  account_aws_account_id: string;
};

const initialCreateForm: CreateFormState = {
  name: "",
  kind: "org_management",
  enabled: true,
  role_arn: "",
  external_id: "",
  billing_view_arn: "",
  team_tag_key: "Team",
  account_display_name: "",
  account_aws_account_id: ""
};

function ConnectionEditor({
  connection,
  active,
  onSaved,
  onSynced
}: {
  connection: ConnectionItem;
  active: boolean;
  onSaved: () => void;
  onSynced: () => void;
}) {
  const [form, setForm] = useState({
    name: connection.name,
    enabled: connection.enabled,
    role_arn: connection.role_arn ?? "",
    external_id: connection.external_id ?? "",
    billing_view_arn: connection.billing_view_arn ?? "",
    team_tag_key: connection.team_tag_key,
    account_display_name: connection.primary_account_name ?? "",
    account_aws_account_id: ""
  });
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    setForm({
      name: connection.name,
      enabled: connection.enabled,
      role_arn: connection.role_arn ?? "",
      external_id: connection.external_id ?? "",
      billing_view_arn: connection.billing_view_arn ?? "",
      team_tag_key: connection.team_tag_key,
      account_display_name: connection.primary_account_name ?? "",
      account_aws_account_id: ""
    });
  }, [
    connection.billing_view_arn,
    connection.enabled,
    connection.external_id,
    connection.name,
    connection.primary_account_name,
    connection.role_arn,
    connection.team_tag_key
  ]);

  async function saveConnection() {
    setSaving(true);
    setMessage(null);
    try {
      await apiRequest(`/connections/${connection.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: form.name,
          enabled: form.enabled,
          role_arn: form.role_arn || null,
          external_id: form.external_id || null,
          billing_view_arn: form.billing_view_arn || null,
          team_tag_key: form.team_tag_key,
          account:
            connection.kind === "account_role" && form.account_display_name && form.account_aws_account_id
              ? {
                  display_name: form.account_display_name,
                  aws_account_id: form.account_aws_account_id
                }
              : undefined
        })
      });
      setMessage("Saved connection settings.");
      onSaved();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save connection");
    } finally {
      setSaving(false);
    }
  }

  async function syncConnection() {
    setSyncing(true);
    setMessage(null);
    try {
      const result = await apiRequest<SyncResponse>(`/connections/${connection.id}/sync`, {
        method: "POST",
        body: JSON.stringify({ days: 14 })
      });
      setMessage(
        result.message
          ? `Sync finished with ${result.status}: ${result.message}`
          : `Synced ${result.accounts_synced} accounts across ${result.window_days} days.`
      );
      onSynced();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to sync connection");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className={`rounded-[24px] border p-5 ${active ? "border-slate-900 bg-white" : "border-slate-200/70 bg-white/75"}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-slate-900">{connection.name}</p>
          <p className="mt-1 text-sm text-slate-500">{connection.kind}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusPill label={connection.enabled ? "enabled" : "disabled"} />
          {active ? <StatusPill label="active" /> : null}
        </div>
      </div>

      <div className="mt-4 grid gap-3">
        <input
          value={form.name}
          onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
          className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm"
          placeholder="Connection name"
        />
        <div className="grid gap-3 md:grid-cols-2">
          <input
            value={form.role_arn}
            onChange={(event) => setForm((current) => ({ ...current, role_arn: event.target.value }))}
            className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm"
            placeholder="Role ARN"
          />
          <input
            value={form.external_id}
            onChange={(event) => setForm((current) => ({ ...current, external_id: event.target.value }))}
            className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm"
            placeholder="External ID"
          />
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <input
            value={form.billing_view_arn}
            onChange={(event) => setForm((current) => ({ ...current, billing_view_arn: event.target.value }))}
            className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm"
            placeholder="Billing View ARN"
          />
          <input
            value={form.team_tag_key}
            onChange={(event) => setForm((current) => ({ ...current, team_tag_key: event.target.value }))}
            className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm"
            placeholder="Team Tag Key"
          />
        </div>
        {connection.kind === "account_role" ? (
          <div className="grid gap-3 md:grid-cols-2">
            <input
              value={form.account_display_name}
              onChange={(event) => setForm((current) => ({ ...current, account_display_name: event.target.value }))}
              className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm"
              placeholder="Primary account display name"
            />
            <input
              value={form.account_aws_account_id}
              onChange={(event) => setForm((current) => ({ ...current, account_aws_account_id: event.target.value }))}
              className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm"
              placeholder="Primary account AWS ID"
            />
          </div>
        ) : null}
        <label className="flex items-center gap-3 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(event) => setForm((current) => ({ ...current, enabled: event.target.checked }))}
          />
          Enabled
        </label>
      </div>

      <div className="mt-4 flex flex-wrap gap-3">
        <button
          onClick={saveConnection}
          disabled={saving}
          className="rounded-full bg-blue-700 px-4 py-2 text-sm text-white transition hover:bg-blue-600 disabled:bg-blue-300"
        >
          {saving ? "Saving..." : "Save"}
        </button>
        <button
          onClick={syncConnection}
          disabled={syncing}
          className="rounded-full bg-slate-900 px-4 py-2 text-sm text-white transition hover:bg-slate-700 disabled:bg-slate-400"
        >
          {syncing ? "Syncing..." : "Sync"}
        </button>
      </div>

      <div className="mt-4 flex flex-wrap gap-2 text-xs uppercase tracking-[0.18em] text-slate-500">
        <span>{connection.account_count} accounts</span>
        {connection.primary_account_name ? <span>{connection.primary_account_name}</span> : null}
      </div>
      {message ? <p className="mt-3 text-sm text-slate-600">{message}</p> : null}
    </div>
  );
}

export default function SettingsPage() {
  const {
    loading: connectionLoading,
    error: connectionError,
    connections,
    selectedConnection,
    selectedConnectionId,
    refreshConnections
  } = useConnection();
  const syncRuns = useApiData<SyncRunsResponse>(selectedConnectionId ? withConnectionId("/sync-runs", selectedConnectionId) : null);
  const [form, setForm] = useState<CreateFormState>(initialCreateForm);
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function createConnection(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setMessage(null);
    try {
      await apiRequest("/connections", {
        method: "POST",
        body: JSON.stringify({
          name: form.name,
          kind: form.kind,
          enabled: form.enabled,
          role_arn: form.role_arn || null,
          external_id: form.external_id || null,
          billing_view_arn: form.billing_view_arn || null,
          team_tag_key: form.team_tag_key,
          account:
            form.kind === "account_role"
              ? {
                  display_name: form.account_display_name,
                  aws_account_id: form.account_aws_account_id
                }
              : undefined
        })
      });
      setForm(initialCreateForm);
      setMessage("Connection created.");
      refreshConnections();
      syncRuns.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create connection");
    } finally {
      setSubmitting(false);
    }
  }

  const sortedConnections = useMemo(
    () => [...connections].sort((left, right) => Number(right.id === selectedConnectionId) - Number(left.id === selectedConnectionId) || left.name.localeCompare(right.name)),
    [connections, selectedConnectionId]
  );

  if (connectionLoading) {
    return <LoadingState label="Loading connection settings..." />;
  }

  if (connectionError) {
    return <ErrorState message={connectionError} />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Settings"
        title="Connection-scoped ingestion controls."
        description="Create and manage demo, organization, and standalone account connections without blending datasets together."
      />

      {message ? <div className="glass-panel rounded-[24px] px-5 py-4 text-sm text-slate-700">{message}</div> : null}

      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <Panel title="Create connection" subtitle="Org-management and standalone account-role connections share one scoped model.">
          <form className="grid gap-4" onSubmit={createConnection}>
            <input
              value={form.name}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="Connection name"
              className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3"
              required
            />
            <select
              value={form.kind}
              onChange={(event) => setForm((current) => ({ ...current, kind: event.target.value as CreateFormState["kind"] }))}
              className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3"
            >
              <option value="org_management">Organization management</option>
              <option value="account_role">Standalone account role</option>
            </select>
            <input
              value={form.role_arn}
              onChange={(event) => setForm((current) => ({ ...current, role_arn: event.target.value }))}
              placeholder={form.kind === "account_role" ? "Role ARN (required)" : "Role ARN (optional)"}
              className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3"
            />
            <div className="grid gap-4 md:grid-cols-2">
              <input
                value={form.external_id}
                onChange={(event) => setForm((current) => ({ ...current, external_id: event.target.value }))}
                placeholder="External ID"
                className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3"
              />
              <input
                value={form.team_tag_key}
                onChange={(event) => setForm((current) => ({ ...current, team_tag_key: event.target.value }))}
                placeholder="Team Tag Key"
                className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3"
              />
            </div>
            <input
              value={form.billing_view_arn}
              onChange={(event) => setForm((current) => ({ ...current, billing_view_arn: event.target.value }))}
              placeholder="Billing View ARN"
              className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3"
            />
            {form.kind === "account_role" ? (
              <div className="grid gap-4 md:grid-cols-2">
                <input
                  value={form.account_display_name}
                  onChange={(event) => setForm((current) => ({ ...current, account_display_name: event.target.value }))}
                  placeholder="Primary account display name"
                  className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3"
                  required
                />
                <input
                  value={form.account_aws_account_id}
                  onChange={(event) => setForm((current) => ({ ...current, account_aws_account_id: event.target.value }))}
                  placeholder="12-digit AWS account id"
                  className="rounded-2xl border border-slate-200 bg-white/80 px-4 py-3"
                  required
                />
              </div>
            ) : null}
            <label className="flex items-center gap-3 text-sm text-slate-600">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(event) => setForm((current) => ({ ...current, enabled: event.target.checked }))}
              />
              Enabled
            </label>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-full bg-blue-700 px-5 py-3 text-sm font-medium text-white transition hover:bg-blue-600 disabled:bg-blue-300"
            >
              {submitting ? "Creating..." : "Create Connection"}
            </button>
          </form>
        </Panel>

        <Panel title="Guidance" subtitle="Operational rules that keep the scoped model honest.">
          <div className="space-y-3 rounded-[24px] bg-slate-900 p-5 text-sm leading-7 text-slate-200">
            <p>1. Organization sync uses one Cost Explorer view and imports linked accounts into the selected connection.</p>
            <p>2. Standalone account-role sync requires one primary account membership plus a role ARN.</p>
            <p>3. Team analytics depend on an activated cost allocation tag key; blank values fall back to Unallocated.</p>
            <p>4. Connections stay separate by design, so totals from organization and standalone scopes are never implicitly merged.</p>
          </div>
        </Panel>
      </div>

      <Panel title="Managed connections" subtitle="Edit, enable, and sync each scoped collector independently.">
        <div className="grid gap-4">
          {sortedConnections.map((connection) => (
            <ConnectionEditor
              key={connection.id}
              connection={connection}
              active={connection.id === selectedConnectionId}
              onSaved={() => {
                refreshConnections();
                syncRuns.refresh();
              }}
              onSynced={() => {
                refreshConnections();
                syncRuns.refresh();
              }}
            />
          ))}
        </div>
      </Panel>

      <Panel title="Recent sync runs" subtitle={selectedConnection ? `${selectedConnection.name} run history` : "Select a connection to inspect recent runs."}>
        {syncRuns.loading ? (
          <LoadingState label="Loading sync history..." />
        ) : syncRuns.error || !syncRuns.data ? (
          <ErrorState message={syncRuns.error ?? "Unable to load sync history."} />
        ) : (
          <div className="space-y-3">
            {syncRuns.data.items.map((run) => (
              <div key={run.id} className="rounded-[24px] border border-slate-200/70 bg-white/75 p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-semibold text-slate-900">{run.kind}</p>
                    <p className="text-sm text-slate-500">{run.finished_at ?? run.started_at ?? "No timestamp"}</p>
                  </div>
                  <StatusPill label={run.status} />
                </div>
                <p className="mt-3 text-sm text-slate-600">
                  {run.accounts_synced} account{run.accounts_synced === 1 ? "" : "s"} synced, {run.records_written} records written, {run.window_days}-day window.
                </p>
                {run.message ? <p className="mt-2 text-sm text-slate-500">{run.message}</p> : null}
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
