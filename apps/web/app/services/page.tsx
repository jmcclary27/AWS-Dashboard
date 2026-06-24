"use client";

import { useState } from "react";

import { BreakdownBarChart } from "@/components/charts";
import { useConnection } from "@/components/connection-provider";
import { ErrorState, LoadingState, MetricRow, PageHeader, Panel, uiHelpers } from "@/components/ui";
import { useApiData, withConnectionId } from "@/lib/api";
import type { AccountsResponse, ServicesResponse } from "@/lib/types";

export default function ServicesPage() {
  const [range, setRange] = useState("90d");
  const [accountId, setAccountId] = useState<string>("all");
  const { loading: connectionLoading, error: connectionError, selectedConnection, selectedConnectionId } = useConnection();
  const accounts = useApiData<AccountsResponse>(selectedConnectionId ? withConnectionId("/accounts", selectedConnectionId) : null);
  const servicesPath = selectedConnectionId
    ? withConnectionId(`/services?range=${range}${accountId === "all" ? "" : `&account_id=${accountId}`}`, selectedConnectionId)
    : null;
  const services = useApiData<ServicesResponse>(servicesPath);

  if (connectionError) {
    return <ErrorState message={connectionError} />;
  }

  if (connectionLoading) {
    return <LoadingState label="Resolving the active connection..." />;
  }

  if (!selectedConnectionId) {
    return <ErrorState message="No available connection. Initialize the demo dataset or create an AWS connection." />;
  }

  if (accounts.loading || services.loading) {
    return <LoadingState label="Loading service breakdowns..." />;
  }

  if (accounts.error || services.error || !accounts.data || !services.data) {
    return <ErrorState message={accounts.error ?? services.error ?? "Unable to load services."} />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Service Breakdown"
        title="The expensive layers become legible fast."
        description={`Tracing service concentration inside ${selectedConnection?.name ?? "the selected connection"} so organizational and standalone views stay independent.`}
        action={
          <div className="flex flex-wrap gap-3">
            <select
              value={range}
              onChange={(event) => setRange(event.target.value)}
              className="rounded-full border border-slate-200 bg-white/80 px-4 py-3 text-sm"
            >
              <option value="30d">30 days</option>
              <option value="90d">90 days</option>
              <option value="365d">365 days</option>
            </select>
            <select
              value={accountId}
              onChange={(event) => setAccountId(event.target.value)}
              className="rounded-full border border-slate-200 bg-white/80 px-4 py-3 text-sm"
            >
              <option value="all">All accounts</option>
              {accounts.data.items.map((account) => (
                <option key={account.id} value={String(account.id)}>
                  {account.display_name}
                </option>
              ))}
            </select>
          </div>
        }
      />

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <Panel title="Top service mix" subtitle={`${services.data.range} cumulative contribution`}>
          <BreakdownBarChart
            data={services.data.items.slice(0, 8).map((item) => ({
              label: item.service_name,
              cost: item.total_cost
            }))}
          />
        </Panel>

        <Panel title="Summary" subtitle="Useful at-a-glance context for the current filter">
          <div className="rounded-[24px] bg-white/75 p-5">
            <p className="font-[family-name:var(--font-display)] text-4xl font-semibold text-slate-950">
              {uiHelpers.formatCurrency(services.data.summary.total_cost)}
            </p>
            <p className="mt-2 text-sm text-slate-500">Total spend in the selected window</p>
          </div>
          <div className="mt-5">
            <MetricRow label="Top service" value={services.data.summary.top_service ?? "N/A"} />
            <MetricRow label="Top service cost" value={uiHelpers.formatCurrency(services.data.summary.top_service_cost)} />
            <MetricRow label="Tracked services" value={String(services.data.items.length)} />
          </div>
        </Panel>
      </div>

      <Panel title="Service leaderboard" subtitle="Latest spend, average daily cost, and recent directional change">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {services.data.items.map((item) => (
            <div key={item.service_name} className="rounded-[24px] border border-slate-200/70 bg-white/75 p-5">
              <p className="font-semibold text-slate-900">{item.service_name}</p>
              <p className="mt-3 font-[family-name:var(--font-display)] text-3xl font-semibold text-slate-950">
                {uiHelpers.formatCurrency(item.total_cost)}
              </p>
              <div className="mt-4">
                <MetricRow label="Average daily" value={uiHelpers.formatCurrency(item.avg_daily_cost)} />
                <MetricRow label="Latest day" value={uiHelpers.formatCurrency(item.latest_cost)} />
                <MetricRow label="7-day change" value={uiHelpers.formatPercent(item.change_pct)} tone={item.change_pct > 10 ? "warm" : "default"} />
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
