"use client";

import { ErrorState, LoadingState, PageHeader, Panel, RecommendationCard } from "@/components/ui";
import { useApiData } from "@/lib/api";
import type { RecommendationsResponse } from "@/lib/types";

export default function RecommendationsPage() {
  const recommendations = useApiData<RecommendationsResponse>("/recommendations");

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
        description="These recommendations are persisted findings, which means the UI can stay fast while the later collector and rules engine keep evolving behind the same API contract."
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

