"use client";

import { SpendLineChart, BreakdownBarChart } from "@/components/charts";
import { useConnection } from "@/components/connection-provider";
import {
  AnomalyCard,
  ErrorState,
  LoadingState,
  MetricRow,
  PageHeader,
  Panel,
  StatusPill,
  RecommendationCard,
  StatCard,
  uiHelpers
} from "@/components/ui";
import { useApiData, withConnectionId } from "@/lib/api";
import type {
  AnomaliesResponse,
  BillingOverviewResponse,
  RecommendationsResponse,
  SummaryResponse
} from "@/lib/types";

export default function DashboardPage() {
  const { loading: connectionLoading, error: connectionError, selectedConnection, selectedConnectionId } = useConnection();
  const summary = useApiData<SummaryResponse>(selectedConnectionId ? withConnectionId("/summary?range=30d", selectedConnectionId) : null);
  const billing = useApiData<BillingOverviewResponse>(selectedConnectionId ? withConnectionId("/billing/overview", selectedConnectionId) : null);
  const anomalies = useApiData<AnomaliesResponse>(selectedConnectionId ? withConnectionId("/anomalies", selectedConnectionId) : null);
  const recommendations = useApiData<RecommendationsResponse>(selectedConnectionId ? withConnectionId("/recommendations", selectedConnectionId) : null);

  if (connectionError) {
    return <ErrorState message={connectionError} />;
  }

  if (connectionLoading) {
    return <LoadingState label="Resolving the active connection..." />;
  }

  if (!selectedConnectionId) {
    return <ErrorState message="No available connection. Initialize the demo dataset or create an AWS connection." />;
  }

  if (summary.loading || billing.loading || anomalies.loading || recommendations.loading) {
    return <LoadingState label="Loading the command center..." />;
  }

  if (summary.error || billing.error || anomalies.error || recommendations.error || !summary.data || !billing.data || !anomalies.data || !recommendations.data) {
    return <ErrorState message={summary.error ?? billing.error ?? anomalies.error ?? recommendations.error ?? "Unable to load the dashboard."} />;
  }

  const topAnomalies = anomalies.data.items.slice(0, 3);
  const topRecommendations = recommendations.data.items.slice(0, 3);
  const payableSeries = billing.data.daily_net_due.map((item) => ({
    date: item.date,
    cost: item.actual_net_due_usd + item.projected_net_due_usd
  }));

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={selectedConnection?.kind === "org_management" ? "Organization Scope" : selectedConnection?.kind === "account_role" ? "Standalone Scope" : "FinOps MVP"}
        title="Local cost visibility with a real deployment runway."
        description={`Viewing ${selectedConnection?.name ?? "the active connection"} through separate workload and bill-truth layers so usage analytics stay useful while payable totals stay as close to AWS month-end charges as possible.`}
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Month-To-Date Due"
          value={uiHelpers.formatCurrency(billing.data.actual_to_date.net_due_usd)}
          detail={billing.data.truth_mode === "exact" ? "Exact bill-truth actuals from AWS Data Exports." : "Approximate net-due actuals from Cost Explorer fallback."}
          accent="blue"
        />
        <StatCard
          label="Projected Month-End"
          value={uiHelpers.formatCurrency(billing.data.month_end_estimate.net_due_usd)}
          detail={`${uiHelpers.formatCurrency(billing.data.projected_remainder.net_due_usd)} still projected this month`}
          accent="orange"
        />
        <StatCard
          label="Gross Usage"
          value={uiHelpers.formatCurrency(billing.data.actual_to_date.gross_usage_usd)}
          detail="Pre-credit service activity for the current month."
          accent="teal"
        />
        <StatCard
          label="Credits & Savings"
          value={uiHelpers.formatCurrency(billing.data.actual_to_date.credits_and_savings_usd)}
          detail="Offsets currently reducing what AWS says you owe."
          accent="orange"
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.65fr_1fr]">
        <Panel title="Daily payable pulse" subtitle={`${billing.data.month} actuals and projected remainder`}>
          <SpendLineChart data={payableSeries} />
        </Panel>

        <Panel title="Top services" subtitle="Usage analytics still stay separate from bill-truth totals">
          <BreakdownBarChart data={summary.data.cost_by_service.slice(0, 6)} />
        </Panel>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <Panel title="Payable outlook" subtitle={billing.data.month}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-[24px] bg-white/75 p-5">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Overall</p>
                <StatusPill label={billing.data.truth_mode} />
              </div>
              <p className="mt-3 font-[family-name:var(--font-display)] text-4xl font-semibold text-slate-950">
                {uiHelpers.formatCurrency(billing.data.month_end_estimate.net_due_usd)}
              </p>
              <div className="mt-4">
                <MetricRow label="Actual to date" value={uiHelpers.formatCurrency(billing.data.actual_to_date.net_due_usd)} />
                <MetricRow label="Projected remainder" value={uiHelpers.formatCurrency(billing.data.projected_remainder.net_due_usd)} tone="warm" />
                <MetricRow label="Bill adjustments" value={uiHelpers.formatCurrency(billing.data.actual_to_date.bill_adjustments_usd)} />
              </div>
            </div>
            <div className="rounded-[24px] bg-slate-900 p-5 text-white">
              <p className="text-xs uppercase tracking-[0.24em] text-slate-300">Reconciliation</p>
              <p className="mt-3 font-[family-name:var(--font-display)] text-2xl font-semibold">
                {uiHelpers.formatCurrency(billing.data.actual_to_date.net_due_usd)}
              </p>
              <div className="mt-4">
                <MetricRow label="Gross usage" value={uiHelpers.formatCurrency(billing.data.actual_to_date.gross_usage_usd)} />
                <MetricRow label="Offsets applied" value={uiHelpers.formatCurrency(billing.data.actual_to_date.credits_and_savings_usd)} tone="good" />
                <MetricRow label="Shared adjustments" value={uiHelpers.formatCurrency(billing.data.reconciliation.shared_adjustments_usd)} />
              </div>
            </div>
          </div>
          <div className="mt-5 space-y-3">
            <div className="rounded-[22px] border border-slate-200/70 bg-white/75 p-4">
              <p className="font-semibold text-slate-900">How the payable total is built</p>
              <div className="mt-3">
                <MetricRow label="Gross usage" value={uiHelpers.formatCurrency(billing.data.actual_to_date.gross_usage_usd)} />
                <MetricRow label="Minus credits and savings" value={uiHelpers.formatCurrency(billing.data.actual_to_date.credits_and_savings_usd)} tone="good" />
                <MetricRow label="Plus bill adjustments" value={uiHelpers.formatCurrency(billing.data.actual_to_date.bill_adjustments_usd)} />
                <MetricRow label="Equals current net due" value={uiHelpers.formatCurrency(billing.data.actual_to_date.net_due_usd)} tone="warm" />
              </div>
              <p className="mt-3 text-sm text-slate-500">
                Shared payer-level offsets and bill items are kept at the connection level instead of being forced into per-account allocations.
              </p>
            </div>
          </div>
        </Panel>

        <Panel title="Signal board" subtitle="Usage analytics still drive anomalies and recommendations">
          <div className="space-y-4">
            {topAnomalies.map((item) => (
              <AnomalyCard
                key={item.id}
                title={item.title}
                summary={item.summary}
                severity={item.severity}
                delta={item.amount_delta_usd}
                account={item.account_name}
                detectedOn={item.detected_on}
              />
            ))}
            {topRecommendations.map((item) => (
              <RecommendationCard
                key={item.id}
                title={item.title}
                summary={item.summary}
                impact={item.impact_level}
                savings={item.estimated_monthly_savings_usd}
                account={item.account_name}
                service={item.service_name}
              />
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
