import type { RunResponse } from "@/lib/types";

import { Badge } from "./ui/badge";
import { PipelineCard } from "./PipelineCard";

export function WeaveTraceCard({ result }: { result?: RunResponse | null }) {
  const metadata = result?.weaveMetadata;
  const versions = result?.promptVersions;

  return (
    <PipelineCard title="Weave trace and eval metadata" badge={metadata?.project ?? "closedai"}>
      {result ? (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap gap-2">
            <Badge tone="default">{metadata?.traceName ?? "closedai-private-consult-run"}</Badge>
            <Badge tone={result.weaveTraceUrl ? "success" : "muted"}>{result.weaveTraceUrl ? "trace linked" : "offline trace stub"}</Badge>
            <Badge tone="muted">{metadata?.status ?? "offline-compatible"}</Badge>
          </div>
          {versions ? (
            <div className="grid gap-x-6 gap-y-3 md:grid-cols-3">
              <Metric label="De-id prompt" value={versions.deidPrompt} />
              <Metric label="Checker prompt" value={versions.checkerPrompt} />
              <Metric label="Repair prompt" value={versions.repairPrompt} />
            </div>
          ) : null}
          {metadata?.evalScores ? (
            <div className="grid gap-x-6 gap-y-3 md:grid-cols-4">
              {Object.entries(metadata.evalScores).map(([key, value]) => (
                <Metric key={key} label={key.replaceAll("_", " ")} value={String(value)} />
              ))}
            </div>
          ) : null}
          {metadata?.promptComparison?.length ? (
            <div className="overflow-hidden rounded-md border">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted text-xs uppercase text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-medium">Prompt version</th>
                    <th className="px-3 py-2 font-medium">Leakage pass</th>
                    <th className="px-3 py-2 font-medium">Avg utility</th>
                  </tr>
                </thead>
                <tbody>
                  {metadata.promptComparison.map((row) => (
                    <tr key={String(row.version)} className="border-t">
                      <td className="px-3 py-2 font-medium">{row.version}</td>
                      <td className="px-3 py-2">{Number(row.leakagePassRate) * 100}%</td>
                      <td className="px-3 py-2">{Number(row.avgUtilityScore) * 100}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Run the pipeline to see trace metadata and prompt-version comparison.</p>
      )}
    </PipelineCard>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase text-muted-foreground">{label}</div>
      <div className="mt-1 break-words font-medium">{value}</div>
    </div>
  );
}
