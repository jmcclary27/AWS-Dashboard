"use client";

import { useConnection } from "@/components/connection-provider";
import { ErrorState, LoadingState, PageHeader, Panel, RecommendationCard } from "@/components/ui";
import { useApiData, withConnectionId } from "@/lib/api";
import type { RecommendationsResponse } from "@/lib/types";

export default function RecommendationsPage() {
  const { loading: connectionLoading, error: connectionError, selectedConnection, selectedConnectionId } = useConnection();
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

  if (recommendations.loading) {
    return <LoadingState label="Loading recommendations..." />;
  }

  if (recommendations.error || !recommendations.data) {
    return <ErrorState message={recommendations.error ?? "Unable to load recommendations."} />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Recommendations"
        title="A working backlog, not just an analytics flourish."
        description={`Persisted opportunities for ${selectedConnection?.name ?? "the selected connection"}, kept separate so organizational and individual recommendations do not overlap.`}
      />
      <Panel title="Open opportunities" subtitle="Initial seeded recommendations built from the same domain objects a real collector will feed">
        <div className="grid gap-4 md:grid-cols-2">
          {recommendations.data.items.map((item) => (
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
  );
}
