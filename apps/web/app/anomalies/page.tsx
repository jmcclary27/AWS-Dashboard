"use client";

import { AnomalyCard, ErrorState, LoadingState, PageHeader, Panel } from "@/components/ui";
import { useApiData } from "@/lib/api";
import type { AnomaliesResponse } from "@/lib/types";

export default function AnomaliesPage() {
  const anomalies = useApiData<AnomaliesResponse>("/anomalies");

  if (anomalies.loading) {
    return <LoadingState label="Loading anomaly feed..." />;
  }

  if (anomalies.error || !anomalies.data) {
    return <ErrorState message={anomalies.error ?? "Unable to load anomalies."} />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Anomalies"
        title="Spend spikes stay visible instead of surprising us at month end."
        description="The current rules are demo-backed but deliberately shaped like persisted findings, so the route contract can survive the move from fake data to real AWS ingestion."
      />
      <Panel title="Latest findings" subtitle="Daily spikes, team growth patterns, and unallocated spend warnings">
        <div className="grid gap-4 md:grid-cols-2">
          {anomalies.data.items.map((item) => (
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
        </div>
      </Panel>
    </div>
  );
}

