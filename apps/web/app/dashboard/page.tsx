"use client";

import { SpendLineChart, BreakdownBarChart } from "@/components/charts";
import {
  AnomalyCard,
  ErrorState,
  LoadingState,
  MetricRow,
  PageHeader,
  Panel,
  RecommendationCard,
  StatCard,
  uiHelpers
} from "@/components/ui";
import { useApiData } from "@/lib/api";
import type {
  AnomaliesResponse,
  ForecastResponse,
  RecommendationsResponse,
  SummaryResponse
} from "@/lib/types";

export default function DashboardPage() {
  const summary = useApiData<SummaryResponse>("/summary?range=30d");
  const forecast = useApiData<ForecastResponse>("/forecast");
  const anomalies = useApiData<AnomaliesResponse>("/anomalies");
  const recommendations = useApiData<RecommendationsResponse>("/recommendations");

  if (summary.loading || forecast.loading || anomalies.loading || recommendations.loading) {
    return <LoadingState label="Loading the command center..." />;
  }

  if (summary.error || forecast.error || anomalies.error || recommendations.error || !summary.data || !forecast.data || !anomalies.data || !recommendations.data) {
    return <ErrorState message={summary.error ?? forecast.error ?? anomalies.error ?? recommendations.error ?? "Unable to load the dashboard."} />;
  }

  const topAnomalies = anomalies.data.items.slice(0, 3);
  const topRecommendations = recommendations.data.items.slice(0, 3);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="FinOps MVP"
        title="Local cost visibility with a real deployment runway."
        description="This dashboard fronts only the FastAPI layer, starts with seeded data, and mirrors the routes and tables we can later feed from Cost Explorer."
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="30-Day Spend"
          value={uiHelpers.formatCurrency(summary.data.totals.total_cost)}
          detail={`${uiHelpers.formatPercent(summary.data.totals.delta_pct)} versus the prior period`}
          accent="blue"
        />
        <StatCard
          label="Month Forecast"
          value={uiHelpers.formatCurrency(forecast.data.overall.projected_total)}
          detail={`${uiHelpers.formatCurrency(forecast.data.overall.projected_remainder)} still projected this month`}
          accent="orange"
        />
        <StatCard
          label="Accounts"
          value={String(summary.data.totals.active_accounts)}
          detail={`${summary.data.totals.services_covered} services currently represented in the dataset`}
          accent="teal"
        />
        <StatCard
          label="Unallocated"
          value={`${summary.data.totals.unallocated_share_pct.toFixed(1)}%`}
          detail="Spend with missing or unknown team tags stays visible instead of disappearing."
          accent="orange"
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.65fr_1fr]">
        <Panel title="Daily spend pulse" subtitle="Last 30 days across all seeded AWS accounts">
          <SpendLineChart data={summary.data.daily_costs} />
        </Panel>

        <Panel title="Top services" subtitle="Current 30-day contribution by AWS service">
          <BreakdownBarChart data={summary.data.cost_by_service.slice(0, 6)} />
        </Panel>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <Panel title="Forecast posture" subtitle={forecast.data.month}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-[24px] bg-white/75 p-5">
              <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Overall</p>
              <p className="mt-3 font-[family-name:var(--font-display)] text-4xl font-semibold text-slate-950">
                {uiHelpers.formatCurrency(forecast.data.overall.projected_total)}
              </p>
              <div className="mt-4">
                <MetricRow label="Actual to date" value={uiHelpers.formatCurrency(forecast.data.overall.actual_to_date)} />
                <MetricRow label="Projected remainder" value={uiHelpers.formatCurrency(forecast.data.overall.projected_remainder)} tone="warm" />
              </div>
            </div>
            <div className="rounded-[24px] bg-slate-900 p-5 text-white">
              <p className="text-xs uppercase tracking-[0.24em] text-slate-300">Latest sync</p>
              <p className="mt-3 font-[family-name:var(--font-display)] text-2xl font-semibold">
                {uiHelpers.formatDateTimeLabel(summary.data.sync_status.last_run_at)}
              </p>
              <div className="mt-4">
                <MetricRow label="Status" value={summary.data.sync_status.status} tone="good" />
                <MetricRow label="Projected services" value={String(summary.data.totals.services_covered)} />
              </div>
            </div>
          </div>
          <div className="mt-5 space-y-3">
            {forecast.data.accounts.slice(0, 4).map((account) => (
              <div key={account.account_id} className="rounded-[22px] border border-slate-200/70 bg-white/75 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-semibold text-slate-900">{account.account_name}</p>
                    <p className="text-sm text-slate-500">
                      {uiHelpers.formatCurrency(account.actual_to_date)} actual + {uiHelpers.formatCurrency(account.projected_remainder)} projected
                    </p>
                  </div>
                  <p className="font-[family-name:var(--font-display)] text-2xl font-semibold text-slate-950">
                    {uiHelpers.formatCurrency(account.projected_total)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Signal board" subtitle="Persisted findings from the latest seeded analytics run">
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

