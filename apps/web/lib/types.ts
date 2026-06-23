export type SummaryResponse = {
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
  role_arn: string | null;
  external_id: string | null;
  team_tag_key: string;
  enabled: boolean;
  current_30d_cost: number;
  last_7d_cost: number;
  forecast_total: number;
  last_sync_at: string | null;
  last_sync_status: string;
  unallocated_share_pct: number;
};

export type AccountsResponse = {
  items: AccountItem[];
};

export type ServicesResponse = {
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
  range: string;
  group_by: "account" | "service" | "team";
  series: Array<{ date: string; group: string; cost: number }>;
  totals: Array<{ group: string; total_cost: number }>;
  available_groups: string[];
};

export type ForecastResponse = {
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

export type RecommendationsResponse = {
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
  accounts_synced: number;
  records_written: number;
  window_days: number;
};

