export type SummaryResponse = {
  connection_id: number;
  range: string;
  generated_at: string;
  totals: {
    total_cost: number;
    previous_total_cost: number;
    delta_pct: number;
    forecast_total: number;
    active_accounts: number;
    services_covered: number;
    unallocated_share_pct: number;
  };
  daily_costs: Array<{ date: string; cost: number }>;
  cost_by_account: Array<{ key: number; label: string; cost: number }>;
  cost_by_service: Array<{ key: string; label: string; cost: number }>;
  cost_by_team: Array<{ key: string; label: string; cost: number }>;
  sync_status: {
    last_run_at: string | null;
    status: string;
    accounts_synced: number;
  };
};

export type AccountItem = {
  id: number;
  display_name: string;
  aws_account_id: string;
  team_tag_key: string;
  enabled: boolean;
  current_30d_cost: number;
  last_7d_cost: number;
  forecast_total: number;
  gross_usage_mtd_usd: number;
  direct_net_due_mtd_usd: number;
  direct_projected_month_end_net_due_usd: number;
  shared_adjustments_included: boolean;
  last_sync_at: string | null;
  last_sync_status: string;
  unallocated_share_pct: number;
  membership_source: string;
  is_primary: boolean;
  membership_enabled: boolean;
};

export type AccountsResponse = {
  connection_id: number;
  items: AccountItem[];
};

export type ServicesResponse = {
  connection_id: number;
  range: string;
  account_id: number | null;
  summary: {
    total_cost: number;
    top_service: string | null;
    top_service_cost: number;
  };
  items: Array<{
    service_name: string;
    total_cost: number;
    avg_daily_cost: number;
    latest_cost: number;
    change_pct: number;
  }>;
  daily_series: Array<{ date: string; service_name: string; cost: number }>;
};

export type TrendsResponse = {
  connection_id: number;
  range: string;
  group_by: "account" | "service" | "team";
  series: Array<{ date: string; group: string; cost: number }>;
  totals: Array<{ group: string; total_cost: number }>;
  available_groups: string[];
};

export type ForecastResponse = {
  connection_id: number;
  month: string;
  generated_at: string;
  overall: {
    actual_to_date: number;
    projected_remainder: number;
    projected_total: number;
  };
  accounts: Array<{
    account_id: number;
    account_name: string;
    actual_to_date: number;
    projected_remainder: number;
    projected_total: number;
  }>;
  daily_projection: Array<{ date: string; projected_cost: number }>;
};

export type BillingOverviewResponse = {
  connection_id: number;
  truth_mode: "exact" | "approximate";
  month: string;
  generated_at: string;
  actual_to_date: {
    gross_usage_usd: number;
    credits_and_savings_usd: number;
    bill_adjustments_usd: number;
    net_due_usd: number;
  };
  projected_remainder: {
    usage_net_usd: number;
    bill_adjustments_usd: number;
    net_due_usd: number;
  };
  month_end_estimate: {
    net_due_usd: number;
  };
  daily_net_due: Array<{
    date: string;
    actual_net_due_usd: number;
    projected_net_due_usd: number;
  }>;
  reconciliation: {
    shared_adjustments_usd: number;
    shared_offsets_present: boolean;
  };
};

export type RecommendationsResponse = {
  connection_id: number;
  items: Array<{
    id: number;
    title: string;
    summary: string;
    impact_level: string;
    estimated_monthly_savings_usd: number;
    account_name: string | null;
    service_name: string | null;
    status: string;
    created_at: string | null;
  }>;
};

export type AnomaliesResponse = {
  connection_id: number;
  items: Array<{
    id: number;
    kind: string;
    title: string;
    summary: string;
    severity: string;
    detected_on: string;
    amount_delta_usd: number;
    account_name: string | null;
    service_name: string | null;
    team_name: string | null;
  }>;
};

export type SyncResponse = {
  status: string;
  connection_id: number;
  accounts_synced: number;
  records_written: number;
  window_days: number;
  message?: string | null;
};

export type ConnectionItem = {
  id: number;
  name: string;
  kind: "demo" | "org_management" | "account_role";
  enabled: boolean;
  billing_mode: "usage_only" | "payable_hybrid";
  billing_truth_mode: "exact" | "approximate";
  team_tag_key: string;
  account_count: number;
  primary_account_name: string | null;
  last_sync_at: string | null;
  last_sync_status: string;
};

export type ConnectionsResponse = {
  workspace_id: number;
  role: "owner" | "editor" | "viewer";
  read_only: boolean;
  items: ConnectionItem[];
};

export type WorkspaceItem = {
  id: number;
  name: string;
  role: "owner" | "editor" | "viewer";
  is_demo: boolean;
  read_only: boolean;
};

export type MeResponse = {
  user: {
    id: number;
    email: string | null;
    display_name: string;
  };
  workspaces: WorkspaceItem[];
};

export type ConnectionConfigItem = {
  id: number;
  workspace_id: number;
  name: string;
  kind: "demo" | "org_management" | "account_role";
  enabled: boolean;
  role_arn: string | null;
  external_id_configured: boolean;
  billing_view_arn: string | null;
  billing_mode: "usage_only" | "payable_hybrid";
  billing_export_bucket: string | null;
  billing_export_prefix: string | null;
  billing_export_region: string | null;
  team_tag_key: string;
  created_by_user_id: number | null;
  created_at: string | null;
  updated_at: string | null;
};

export type ConnectionConfigResponse = { item: ConnectionConfigItem };

export type WorkspaceMembersResponse = {
  workspace_id: number;
  items: Array<{
    user_id: number;
    email: string;
    display_name: string;
    role: "owner" | "editor" | "viewer";
    created_at: string | null;
  }>;
};

export type WorkspaceInviteResponse = {
  item: {
    id: number;
    email: string;
    role: "editor" | "viewer";
    expires_at: string;
    invite_url: string;
  };
};

export type WorkspaceInvitesResponse = {
  workspace_id: number;
  items: Array<{
    id: number;
    email: string;
    role: "editor" | "viewer";
    status: "pending" | "accepted" | "revoked" | "expired";
    expires_at: string;
    created_at: string | null;
  }>;
};

export type AuditEventsResponse = {
  workspace_id: number;
  next_before_id: number | null;
  items: Array<{
    id: number;
    action: string;
    outcome: string;
    target_type: string | null;
    target_id: string | null;
    connection_id: number | null;
    actor_name: string | null;
    request_id: string | null;
    metadata: Record<string, unknown>;
    created_at: string;
  }>;
};

export type SyncRunsResponse = {
  connection_id: number;
  items: Array<{
    id: number;
    status: string;
    kind: string;
    message: string | null;
    window_days: number;
    accounts_synced: number;
    records_written: number;
    started_at: string | null;
    finished_at: string | null;
  }>;
};

export type ConnectionValidationResponse = {
  connection_id: number;
  kind: "demo" | "org_management" | "account_role";
  ready: boolean;
  status: "ready" | "error";
  truth_mode: "exact" | "approximate";
  credential_source: string | null;
  identity: {
    account_id: string;
    arn: string;
    user_id: string;
  } | null;
  checks: Array<{
    code: string;
    status: "success" | "warning" | "error";
    message: string;
  }>;
  message: string;
};
