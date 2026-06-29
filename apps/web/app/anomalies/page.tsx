"use client";

import { useConnection } from "@/components/connection-provider";
import { AnomalyCard, ErrorState, LoadingState, PageHeader, Panel } from "@/components/ui";
import { useApiData, withConnectionId } from "@/lib/api";
import type { AnomaliesResponse } from "@/lib/types";

export default function AnomaliesPage() {
  const { loading: connectionLoading, error: connectionError, selectedConnection, selectedConnectionId } = useConnection();
  const anomalies = useApiData<AnomaliesResponse>(selectedConnectionId ? withConnectionId("/anomalies", selectedConnectionId) : null);

  if (connectionError) {
    return <ErrorState message={connectionError} />;
  }

  if (connectionLoading) {
    return <LoadingState label="Resolving the active connection..." />;
  }

  if (!selectedConnectionId) {
    return <ErrorState message="No available connection. Initialize the demo dataset or create an AWS connection." />;
  }

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
        description={`Persisted usage anomalies for ${selectedConnection?.name ?? "the selected connection"}, kept scoped so one dataset cannot pollute another or get mistaken for payable bill truth.`}
      />
      <Panel title="Latest findings" subtitle="Daily spikes, team growth patterns, and unallocated usage warnings">
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
