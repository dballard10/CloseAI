import type { CheckerResult } from "@/lib/types";

import { Badge } from "./ui/badge";
import { PipelineCard } from "./PipelineCard";

export function CheckerResultCard({ title, result }: { title: string; result?: CheckerResult }) {
  if (!result) {
    return (
      <PipelineCard title={title}>
        <p className="text-sm text-muted-foreground">Waiting for checker output.</p>
      </PipelineCard>
    );
  }

  return (
    <PipelineCard title={title} status={result.passed ? "passed" : "failed"} badge={result.passed ? "passed" : "failed"}>
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap gap-2">
          <Badge tone={result.riskLevel === "high" ? "danger" : result.riskLevel === "medium" ? "warning" : "success"}>
            risk {result.riskLevel}
          </Badge>
          {result.leakageTypes.map((type) => (
            <Badge key={type} tone="muted">
              {type}
            </Badge>
          ))}
        </div>
        {result.leakedItems.length ? (
          <div>
            <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">Leaked items</div>
            <div className="flex flex-wrap gap-2">
              {result.leakedItems.map((item) => (
                <Badge key={item} tone="danger">
                  {item}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}
        {result.explanation ? <p className="leading-6 text-muted-foreground">{result.explanation}</p> : null}
        {result.recommendedFix ? <p className="rounded-md bg-amber-50 p-3 leading-6 text-amber-900">{result.recommendedFix}</p> : null}
      </div>
    </PipelineCard>
  );
}
