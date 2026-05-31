import type { ExternalConsultantResponse } from "@/lib/types";

import { Badge } from "./ui/badge";
import { PipelineCard } from "./PipelineCard";

export function ExternalConsultantCard({
  response,
  allowed
}: {
  response?: ExternalConsultantResponse | null;
  allowed?: boolean;
}) {
  const status: "neutral" | "passed" | "failed" = allowed === undefined ? "neutral" : allowed ? "passed" : "failed";
  const badge = allowed === undefined ? "pending" : allowed ? "sanitized only" : "blocked";
  return (
    <PipelineCard title="External consultant" status={status} badge={badge}>
      {response ? (
        <div className="space-y-3 text-sm">
          <p className="leading-6">{response.advice}</p>
          <div>
            <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">Suggested structure</div>
            <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
              {response.suggestedStructure.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ol>
          </div>
          <div className="flex flex-wrap gap-2">
            {response.risks.map((risk) => (
              <Badge key={risk} tone="warning">
                {risk}
              </Badge>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          The consultant is called only after the final checker passes and the utility score is at least 60%.
        </p>
      )}
    </PipelineCard>
  );
}
