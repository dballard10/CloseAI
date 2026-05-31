import { PipelineCard, TextBlock } from "./PipelineCard";

export function FinalAnswerCard({ answer }: { answer?: string }) {
  return (
    <PipelineCard title="Final trusted answer" status="private" badge="local finalizer">
      <TextBlock>{answer || "The trusted local finalizer may use private details after consultant advice returns."}</TextBlock>
    </PipelineCard>
  );
}
