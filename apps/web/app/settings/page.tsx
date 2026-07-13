"use client";

import { useEffect, useState, type Dispatch, type FormEvent, type SetStateAction } from "react";

import { useConnection } from "@/components/connection-provider";
import { ErrorState, LoadingState, PageHeader, Panel, StatusPill } from "@/components/ui";
import { apiRequest, useApiData } from "@/lib/api";
import type {
  AuditEventsResponse,
  ConnectionConfigResponse,
  ConnectionValidationResponse,
  SyncResponse,
  WorkspaceInviteResponse,
  WorkspaceInvitesResponse,
  WorkspaceMembersResponse
} from "@/lib/types";

type ConnectionForm = {
  name: string;
  kind: "org_management" | "account_role";
  enabled: boolean;
  role_arn: string;
  external_id: string;
  clear_external_id: boolean;
  billing_view_arn: string;
  billing_mode: "usage_only" | "payable_hybrid";
  billing_export_bucket: string;
  billing_export_prefix: string;
  billing_export_region: string;
  team_tag_key: string;
  account_display_name: string;
  account_aws_account_id: string;
};

const blankConnectionForm: ConnectionForm = {
  name: "",
  kind: "org_management",
  enabled: true,
  role_arn: "",
  external_id: "",
  clear_external_id: false,
  billing_view_arn: "",
  billing_mode: "payable_hybrid",
  billing_export_bucket: "",
  billing_export_prefix: "",
  billing_export_region: "us-east-1",
  team_tag_key: "Team",
  account_display_name: "",
  account_aws_account_id: ""
};

function inputClassName() {
  return "rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm";
}

function toPatch(form: ConnectionForm) {
  return {
    name: form.name,
    enabled: form.enabled,
    role_arn: form.role_arn || null,
    ...(form.external_id ? { external_id: form.external_id } : form.clear_external_id ? { external_id: null } : {}),
    billing_view_arn: form.billing_view_arn || null,
    billing_mode: form.billing_mode,
    billing_export_bucket: form.billing_export_bucket || null,
    billing_export_prefix: form.billing_export_prefix || null,
    billing_export_region: form.billing_export_region || null,
    team_tag_key: form.team_tag_key,
    ...(form.kind === "account_role" && form.account_display_name && form.account_aws_account_id
      ? { account: { display_name: form.account_display_name, aws_account_id: form.account_aws_account_id } }
      : {})
  };
}

export default function SettingsPage() {
  const {
    loading,
    error,
    selectedWorkspace,
    selectedWorkspaceId,
    selectedConnection,
    selectedConnectionId,
    canEditWorkspace,
    isWorkspaceOwner,
    refreshConnections,
    refreshWorkspace
  } = useConnection();
  const config = useApiData<ConnectionConfigResponse>(
    canEditWorkspace && selectedConnectionId ? `/connections/${selectedConnectionId}` : null
  );
  const members = useApiData<WorkspaceMembersResponse>(
    isWorkspaceOwner && selectedWorkspaceId ? `/workspaces/${selectedWorkspaceId}/members` : null
  );
  const invites = useApiData<WorkspaceInvitesResponse>(
    isWorkspaceOwner && selectedWorkspaceId ? `/workspaces/${selectedWorkspaceId}/invites` : null
  );
  const audit = useApiData<AuditEventsResponse>(
    isWorkspaceOwner && selectedWorkspaceId ? `/workspaces/${selectedWorkspaceId}/audit-events` : null
  );
  const [editorForm, setEditorForm] = useState<ConnectionForm>(blankConnectionForm);
  const [createForm, setCreateForm] = useState<ConnectionForm>(blankConnectionForm);
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState<ConnectionValidationResponse | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"editor" | "viewer">("viewer");
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);

  useEffect(() => {
    if (!config.data) return;
    const connection = config.data.item;
    setEditorForm({
      name: connection.name,
      kind: connection.kind === "demo" ? "org_management" : connection.kind,
      enabled: connection.enabled,
      role_arn: connection.role_arn ?? "",
      external_id: "",
      clear_external_id: false,
      billing_view_arn: connection.billing_view_arn ?? "",
      billing_mode: connection.billing_mode,
      billing_export_bucket: connection.billing_export_bucket ?? "",
      billing_export_prefix: connection.billing_export_prefix ?? "",
      billing_export_region: connection.billing_export_region ?? "us-east-1",
      team_tag_key: connection.team_tag_key,
      account_display_name: "",
      account_aws_account_id: ""
    });
  }, [config.data]);

  if (error) return <ErrorState message={error} />;
  if (loading) return <LoadingState label="Resolving workspace permissions..." />;
  if (!selectedWorkspace || !selectedWorkspaceId) return <ErrorState message="No authorized workspace is available." />;

  async function saveConnection() {
    if (!selectedConnectionId) return;
    setSaving(true);
    setMessage(null);
    try {
      await apiRequest(`/connections/${selectedConnectionId}`, { method: "PATCH", body: JSON.stringify(toPatch(editorForm)) });
      setMessage("Connection configuration saved. Sensitive external IDs remain write-only.");
      setEditorForm((current) => ({ ...current, external_id: "", clear_external_id: false }));
      config.refresh();
      refreshConnections();
    } catch (nextError) {
      setMessage(nextError instanceof Error ? nextError.message : "Unable to save connection configuration");
    } finally {
      setSaving(false);
    }
  }

  async function createConnection() {
    setCreating(true);
    setMessage(null);
    try {
      await apiRequest("/connections", {
        method: "POST",
        body: JSON.stringify({
          ...toPatch(createForm),
          workspace_id: selectedWorkspaceId,
          kind: createForm.kind,
          external_id: createForm.external_id || null
        })
      });
      setCreateForm(blankConnectionForm);
      setMessage("Connection created in this workspace.");
      refreshConnections();
    } catch (nextError) {
      setMessage(nextError instanceof Error ? nextError.message : "Unable to create connection");
    } finally {
      setCreating(false);
    }
  }

  async function validateConnection() {
    if (!selectedConnectionId) return;
    setValidating(true);
    setMessage(null);
    try {
      const result = await apiRequest<ConnectionValidationResponse>(`/connections/${selectedConnectionId}/validate`, { method: "POST" });
      setValidation(result);
      setMessage(result.message);
    } catch (nextError) {
      setValidation(null);
      setMessage(nextError instanceof Error ? nextError.message : "Unable to validate connection");
    } finally {
      setValidating(false);
    }
  }

  async function syncConnection() {
    if (!selectedConnectionId) return;
    setSyncing(true);
    setMessage(null);
    try {
      const result = await apiRequest<SyncResponse>(`/connections/${selectedConnectionId}/sync`, { method: "POST" });
      setMessage(result.message ?? `Synced ${result.accounts_synced} accounts across ${result.window_days} days.`);
      refreshConnections();
    } catch (nextError) {
      setMessage(nextError instanceof Error ? nextError.message : "Unable to sync connection");
    } finally {
      setSyncing(false);
    }
  }

  async function createInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setInviting(true);
    try {
      const result = await apiRequest<WorkspaceInviteResponse>(`/workspaces/${selectedWorkspaceId}/invites`, {
        method: "POST",
        body: JSON.stringify({ email: inviteEmail, role: inviteRole })
      });
      setInviteUrl(result.item.invite_url);
      setInviteEmail("");
      members.refresh();
      invites.refresh();
      audit.refresh();
    } catch (nextError) {
      setMessage(nextError instanceof Error ? nextError.message : "Unable to create invite");
    } finally {
      setInviting(false);
    }
  }

  async function changeMemberRole(userId: number, role: "editor" | "viewer") {
    try {
      await apiRequest(`/workspaces/${selectedWorkspaceId}/members/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({ role })
      });
      members.refresh();
      audit.refresh();
    } catch (nextError) {
      setMessage(nextError instanceof Error ? nextError.message : "Unable to update workspace member");
    }
  }

  async function removeMember(userId: number) {
    try {
      await apiRequest(`/workspaces/${selectedWorkspaceId}/members/${userId}`, { method: "DELETE" });
      members.refresh();
      audit.refresh();
    } catch (nextError) {
      setMessage(nextError instanceof Error ? nextError.message : "Unable to remove workspace member");
    }
  }

  async function revokeInvite(invitationId: number) {
    try {
      await apiRequest(`/workspaces/${selectedWorkspaceId}/invites/${invitationId}`, { method: "DELETE" });
      setInviteUrl(null);
      invites.refresh();
      audit.refresh();
    } catch (nextError) {
      setMessage(nextError instanceof Error ? nextError.message : "Unable to revoke workspace invite");
    }
  }

  const readOnly = !canEditWorkspace || selectedWorkspace.read_only;
  const externalConfigured = config.data?.item.external_id_configured;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Workspace Settings"
        title={selectedWorkspace.name}
        description="Workspace access is enforced by the API. Editors manage connections; only the owner manages sharing and audit history."
      />

      <div className="glass-panel flex flex-wrap items-center gap-3 rounded-[24px] px-5 py-4 text-sm text-slate-700">
        <StatusPill label={selectedWorkspace.role} />
        <StatusPill label={selectedWorkspace.read_only ? "read-only demo" : "private workspace"} />
        <span>{readOnly ? "You can view analytics, but cannot change this workspace." : "You can manage connections in this workspace."}</span>
      </div>
      {message ? <div className="glass-panel rounded-[24px] px-5 py-4 text-sm text-slate-700">{message}</div> : null}

      {canEditWorkspace && !selectedWorkspace.read_only ? (
        <div className="grid gap-6 xl:grid-cols-2">
          <Panel title="Create connection" subtitle="The connection is owned by this workspace; AWS credentials never enter browser storage.">
            <ConnectionFormFields form={createForm} setForm={setCreateForm} includeKind />
            <button onClick={createConnection} disabled={creating} className="mt-4 rounded-full bg-blue-700 px-5 py-3 text-sm font-medium text-white disabled:bg-blue-300">
              {creating ? "Creating..." : "Create connection"}
            </button>
          </Panel>

          <Panel title={selectedConnection ? `Manage ${selectedConnection.name}` : "Manage connection"} subtitle="Configuration is available to editors and owners only. External IDs are write-only.">
            {!selectedConnectionId ? <p className="text-sm text-slate-500">Create or select a connection first.</p> : config.loading ? <LoadingState label="Loading protected configuration..." /> : config.error || !config.data ? <ErrorState message={config.error ?? "Unable to load connection configuration."} /> : selectedConnection?.kind === "demo" ? <p className="text-sm text-slate-600">The shared demo connection is intentionally read-only.</p> : (
              <>
                <ConnectionFormFields form={editorForm} setForm={setEditorForm} includeKind={false} externalConfigured={externalConfigured} />
                <div className="mt-4 flex flex-wrap gap-3">
                  <button onClick={saveConnection} disabled={saving} className="rounded-full bg-blue-700 px-5 py-3 text-sm font-medium text-white disabled:bg-blue-300">{saving ? "Saving..." : "Save configuration"}</button>
                  <button onClick={validateConnection} disabled={validating} className="rounded-full border border-slate-300 px-5 py-3 text-sm">{validating ? "Validating..." : "Validate access"}</button>
                  <button onClick={syncConnection} disabled={syncing} className="rounded-full bg-slate-900 px-5 py-3 text-sm text-white disabled:bg-slate-400">{syncing ? "Syncing..." : "Run sync"}</button>
                </div>
                {validation ? <div className="mt-4 rounded-2xl bg-slate-50 p-4 text-sm text-slate-600"><StatusPill label={validation.status} /> <span className="ml-2">{validation.message}</span></div> : null}
              </>
            )}
          </Panel>
        </div>
      ) : null}

      {isWorkspaceOwner ? (
        <div className="grid gap-6 xl:grid-cols-2">
          <Panel title="Workspace members" subtitle="Share a time-limited, email-bound invite link. Email delivery through SES is intentionally deferred.">
            <form onSubmit={createInvite} className="flex flex-wrap gap-3">
              <input value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} type="email" required placeholder="teammate@example.com" className="min-w-[220px] flex-1 rounded-2xl border border-slate-200 px-4 py-3 text-sm" />
              <select value={inviteRole} onChange={(event) => setInviteRole(event.target.value as "editor" | "viewer")} className="rounded-2xl border border-slate-200 px-4 py-3 text-sm"><option value="viewer">Viewer</option><option value="editor">Editor</option></select>
              <button disabled={inviting} className="rounded-full bg-slate-900 px-5 py-3 text-sm text-white disabled:bg-slate-400">{inviting ? "Creating..." : "Create invite"}</button>
            </form>
            {inviteUrl ? <div className="mt-4 space-y-2 rounded-2xl bg-slate-50 p-4"><p className="text-sm font-medium">Copy and share this link once:</p><input readOnly value={inviteUrl} className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs" /><button onClick={() => navigator.clipboard?.writeText(inviteUrl)} className="text-sm font-medium text-blue-700">Copy link</button></div> : null}
            {members.loading ? <LoadingState label="Loading members..." /> : members.error ? <ErrorState message={members.error} /> : <div className="mt-5 space-y-3">{members.data?.items.map((member) => <div key={member.user_id} className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 p-4 text-sm"><div><p className="font-medium">{member.display_name}</p><p className="text-slate-500">{member.email}</p></div>{member.role === "owner" ? <StatusPill label="owner" /> : <div className="flex items-center gap-2"><select value={member.role} onChange={(event) => changeMemberRole(member.user_id, event.target.value as "editor" | "viewer")} className="rounded-xl border border-slate-200 px-3 py-2"><option value="viewer">Viewer</option><option value="editor">Editor</option></select><button onClick={() => removeMember(member.user_id)} className="text-sm text-rose-700">Remove</button></div>}</div>)}</div>}
            <div className="mt-5 border-t border-slate-200 pt-5">
              <p className="text-sm font-medium text-slate-800">Invite lifecycle</p>
              {invites.loading ? <LoadingState label="Loading invitations..." /> : invites.error ? <ErrorState message={invites.error} /> : <div className="mt-3 space-y-2">{invites.data?.items.length ? invites.data.items.map((invite) => <div key={invite.id} className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-slate-50 p-3 text-sm"><div><p className="font-medium">{invite.email}</p><p className="text-xs text-slate-500">{invite.role} · expires {new Date(invite.expires_at).toLocaleString()}</p></div><div className="flex items-center gap-2"><StatusPill label={invite.status} />{invite.status === "pending" ? <button onClick={() => revokeInvite(invite.id)} className="text-sm text-rose-700">Revoke</button> : null}</div></div>) : <p className="text-sm text-slate-500">No invitations yet.</p>}</div>}
            </div>
          </Panel>

          <Panel title="Audit history" subtitle="Append-only application events for this workspace. Sensitive values are redacted before storage.">
            {audit.loading ? <LoadingState label="Loading audit history..." /> : audit.error ? <ErrorState message={audit.error} /> : <div className="space-y-3">{audit.data?.items.map((event) => <div key={event.id} className="rounded-2xl border border-slate-200 p-4 text-sm"><div className="flex items-center justify-between gap-3"><div><p className="font-medium">{event.action}</p><p className="text-xs text-slate-500">{new Date(event.created_at).toLocaleString()} {event.actor_name ? `· ${event.actor_name}` : "· system"}</p></div><StatusPill label={event.outcome} /></div>{Object.keys(event.metadata).length ? <pre className="mt-3 overflow-x-auto rounded-xl bg-slate-50 p-3 text-xs text-slate-600">{JSON.stringify(event.metadata, null, 2)}</pre> : null}</div>) ?? <p className="text-sm text-slate-500">No events yet.</p>}</div>}
          </Panel>
        </div>
      ) : null}

      {selectedWorkspace.read_only ? <Panel title="Demo access" subtitle="The seeded demo is shared after sign-in so it remains safe for a public portfolio."><p className="text-sm leading-7 text-slate-600">Create a private workspace connection to validate AWS access, run syncs, or share a cost view with teammates.</p></Panel> : null}
    </div>
  );
}

function ConnectionFormFields({ form, setForm, includeKind, externalConfigured = false }: { form: ConnectionForm; setForm: Dispatch<SetStateAction<ConnectionForm>>; includeKind: boolean; externalConfigured?: boolean }) {
  const set = <Key extends keyof ConnectionForm>(key: Key, value: ConnectionForm[Key]) => setForm((current) => ({ ...current, [key]: value }));
  return (
    <div className="grid gap-3">
      <input value={form.name} onChange={(event) => set("name", event.target.value)} placeholder="Connection name" className={inputClassName()} required />
      {includeKind ? <select value={form.kind} onChange={(event) => set("kind", event.target.value as ConnectionForm["kind"])} className={inputClassName()}><option value="org_management">Organization management</option><option value="account_role">Standalone account role</option></select> : null}
      <div className="grid gap-3 md:grid-cols-2"><input value={form.role_arn} onChange={(event) => set("role_arn", event.target.value)} placeholder="Role ARN" className={inputClassName()} /><input value={form.external_id} onChange={(event) => set("external_id", event.target.value)} placeholder={externalConfigured ? "Replace configured external ID" : "External ID (optional)"} className={inputClassName()} /></div>
      {externalConfigured ? <label className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={form.clear_external_id} onChange={(event) => set("clear_external_id", event.target.checked)} /> Clear the existing external ID</label> : null}
      <div className="grid gap-3 md:grid-cols-2"><select value={form.billing_mode} onChange={(event) => set("billing_mode", event.target.value as ConnectionForm["billing_mode"])} className={inputClassName()}><option value="payable_hybrid">Payable hybrid</option><option value="usage_only">Usage-only fallback</option></select><input value={form.billing_view_arn} onChange={(event) => set("billing_view_arn", event.target.value)} placeholder="Billing View ARN" className={inputClassName()} /></div>
      <div className="grid gap-3 md:grid-cols-3"><input value={form.billing_export_bucket} onChange={(event) => set("billing_export_bucket", event.target.value)} placeholder="Billing export bucket" className={inputClassName()} /><input value={form.billing_export_prefix} onChange={(event) => set("billing_export_prefix", event.target.value)} placeholder="Billing export prefix" className={inputClassName()} /><input value={form.billing_export_region} onChange={(event) => set("billing_export_region", event.target.value)} placeholder="Export region" className={inputClassName()} /></div>
      <input value={form.team_tag_key} onChange={(event) => set("team_tag_key", event.target.value)} placeholder="Team tag key" className={inputClassName()} />
      {form.kind === "account_role" ? <div className="grid gap-3 md:grid-cols-2"><input value={form.account_display_name} onChange={(event) => set("account_display_name", event.target.value)} placeholder="Primary account display name" className={inputClassName()} /><input value={form.account_aws_account_id} onChange={(event) => set("account_aws_account_id", event.target.value)} placeholder="12-digit primary AWS account ID" className={inputClassName()} /></div> : null}
      <label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={form.enabled} onChange={(event) => set("enabled", event.target.checked)} /> Enabled</label>
    </div>
  );
}
