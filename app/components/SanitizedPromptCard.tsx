import { PipelineCard, TextBlock } from "./PipelineCard";

export function SanitizedPromptCard({ title, prompt }: { title: string; prompt?: string | null }) {
  return (
    <PipelineCard title={title} badge="sanitized">
      <TextBlock>{prompt || "Run the pipeline to generate the semantic abstraction."}</TextBlock>
    </PipelineCard>
  );
}
