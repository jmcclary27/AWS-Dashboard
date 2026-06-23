"use client";

import { useState } from "react";

import { GroupTrendChart } from "@/components/charts";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/ui";
import { useApiData } from "@/lib/api";
import type { TrendsResponse } from "@/lib/types";

export default function TrendsPage() {
  const [range, setRange] = useState("90d");
  const [groupBy, setGroupBy] = useState<"account" | "service" | "team">("account");
  const trendsPath = `/trends?range=${range}&group_by=${groupBy}`;
  const trends = useApiData<TrendsResponse>(trendsPath);

  if (trends.loading) {
    return <LoadingState label="Loading trend data..." />;
  }

  if (trends.error || !trends.data) {
    return <ErrorState message={trends.error ?? "Unable to load trends."} />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Trends"
        title="Portfolio shifts, sliced the way operators actually think."
        description="Switch between accounts, services, and teams to understand whether the current movement is a platform-wide pattern or concentrated in one slice of the estate."
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
              value={groupBy}
              onChange={(event) => setGroupBy(event.target.value as "account" | "service" | "team")}
              className="rounded-full border border-slate-200 bg-white/80 px-4 py-3 text-sm"
            >
              <option value="account">By account</option>
              <option value="service">By service</option>
              <option value="team">By team</option>
            </select>
          </div>
        }
      />

      <Panel title="Multi-series trendline" subtitle={`Top ${trends.data.available_groups.slice(0, 6).length} ${groupBy} groups in the selected range`}>
        <GroupTrendChart series={trends.data.series.filter((item) => trends.data.available_groups.slice(0, 6).includes(item.group))} />
      </Panel>

      <Panel title="Current leaders" subtitle="Cumulative spend across the selected grouping">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {trends.data.totals.slice(0, 9).map((item) => (
            <div key={item.group} className="rounded-[24px] border border-slate-200/70 bg-white/75 p-5">
              <p className="text-sm uppercase tracking-[0.18em] text-slate-500">{groupBy}</p>
              <p className="mt-2 font-semibold text-slate-900">{item.group}</p>
              <p className="mt-4 font-[family-name:var(--font-display)] text-3xl font-semibold text-slate-950">
                {new Intl.NumberFormat("en-US", {
                  style: "currency",
                  currency: "USD",
                  maximumFractionDigits: 0
                }).format(item.total_cost)}
              </p>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
