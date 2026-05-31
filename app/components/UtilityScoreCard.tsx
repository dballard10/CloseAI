import type { UtilityResult } from "@/lib/types";

import { Badge } from "./ui/badge";
import { PipelineCard } from "./PipelineCard";

export function UtilityScoreCard({ result }: { result?: UtilityResult }) {
  const score = result?.utilityScore ?? 0;
  return (
    <PipelineCard title="Utility score" status={score >= 0.6 ? "passed" : "neutral"} badge={result ? `${Math.round(score * 100)}%` : "pending"}>
      {result ? (
        <div className="space-y-4">
          <div className="h-3 overflow-hidden rounded-full bg-muted">
            <div className="h-full bg-primary" style={{ width: `${Math.round(score * 100)}%` }} />
          </div>
          <div className="space-y-2 text-sm">
            <div>
              <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">Preserved</div>
              <div className="flex flex-wrap gap-2">
                {result.preservedConcepts.map((concept) => (
                  <Badge key={concept} tone="success">
                    {concept}
                  </Badge>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">Missing useful context</div>
              <div className="flex flex-wrap gap-2">
                {result.missingUsefulContext.length ? (
                  result.missingUsefulContext.map((concept) => (
                    <Badge key={concept} tone="warning">
                      {concept}
                    </Badge>
                  ))
                ) : (
                  <Badge tone="muted">none</Badge>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Waiting for the final sanitized prompt.</p>
      )}
    </PipelineCard>
  );
}
