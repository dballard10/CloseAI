import { PipelineCard, TextBlock } from "./PipelineCard";

export function RepairLoopCard({ prompt, repaired }: { prompt?: string | null; repaired: boolean }) {
  return (
    <PipelineCard title="Repair loop" status={repaired ? "passed" : "neutral"} badge={repaired ? "repaired" : "not needed"}>
      <TextBlock>{prompt || "No repair has been run yet."}</TextBlock>
    </PipelineCard>
  );
}
