"use client";

import { type ReactNode, useState } from "react";
import { ArrowRight, Brain, LockKeyhole, ShieldCheck } from "lucide-react";

import { CheckerResultCard } from "./components/CheckerResultCard";
import { DemoExampleSelector } from "./components/DemoExampleSelector";
import { EntityTable } from "./components/EntityTable";
import { ExternalConsultantCard } from "./components/ExternalConsultantCard";
import { FinalAnswerCard } from "./components/FinalAnswerCard";
import { PipelineCard, TextBlock } from "./components/PipelineCard";
import { PromptInput } from "./components/PromptInput";
import { RepairLoopCard } from "./components/RepairLoopCard";
import { SanitizedPromptCard } from "./components/SanitizedPromptCard";
import { UtilityScoreCard } from "./components/UtilityScoreCard";
import { Badge } from "./components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { WeaveTraceCard } from "./components/WeaveTraceCard";
import { examples } from "@/lib/demo-data";
import type { DemoExample, PipelineEvent, RunResponse } from "@/lib/types";

export default function Home() {
  const first = examples[0];
  const [prompt, setPrompt] = useState(first.prompt);
  const [result, setResult] = useState<Partial<RunResponse> | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentStage, setCurrentStage] = useState<string | null>(null);

  async function runPipeline() {
    setRunning(true);
    setError(null);
    setCurrentStage("starting");
    setResult({ rawPrompt: prompt, detectedEntities: [] });
    try {
      const response = await fetch("/api/run/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rawPrompt: prompt })
      });
      if (!response.ok) {
        throw new Error(`Request failed with ${response.status}`);
      }
      if (!response.body) {
        throw new Error("Streaming response was empty");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line) as PipelineEvent;
          setCurrentStage(event.stage);
          if (event.error) {
            throw new Error(event.error);
          }
          if (event.patch) {
            setResult((previous) => ({ ...(previous ?? {}), ...event.patch }));
          }
        }
      }

      if (buffer.trim()) {
        const event = JSON.parse(buffer) as PipelineEvent;
        setCurrentStage(event.stage);
        if (event.error) {
          throw new Error(event.error);
        }
        if (event.patch) {
          setResult((previous) => ({ ...(previous ?? {}), ...event.patch }));
        }
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunning(false);
      setCurrentStage(null);
    }
  }

  function selectExample(example: DemoExample) {
    setPrompt(example.prompt);
    setResult(null);
    setError(null);
    setCurrentStage(null);
  }

  return (
    <main className="mx-auto max-w-[1440px] px-4 py-5 md:px-6 lg:px-8">
      <header className="mb-5 flex flex-col gap-3 border-b pb-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-normal">ClosedAI</h1>
            <Badge tone="default">evaluated privacy gate</Badge>
            <Badge tone="muted">external model sees sanitized prompt only</Badge>
          </div>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            A trusted local orchestrator detects private details, builds a semantic abstraction, runs a checker and repair loop,
            then consults an untrusted model only after the privacy gate passes.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <BoundaryIcon icon={<LockKeyhole className="h-4 w-4" />} label="trusted local" />
          <ArrowRight className="h-4 w-4" />
          <BoundaryIcon icon={<ShieldCheck className="h-4 w-4" />} label="privacy gate" />
          <ArrowRight className="h-4 w-4" />
          <BoundaryIcon icon={<Brain className="h-4 w-4" />} label="untrusted consultant" />
        </div>
      </header>

      <div className="grid pipeline-grid gap-5">
        <aside className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Raw private prompt</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <PromptInput value={prompt} onChange={setPrompt} onRun={runPipeline} running={running} />
              {running && currentStage ? (
                <p className="rounded-md bg-muted p-3 text-sm text-muted-foreground">Current stage: {formatStage(currentStage)}</p>
              ) : null}
              {error ? <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Preset examples</CardTitle>
            </CardHeader>
            <CardContent>
              <DemoExampleSelector examples={examples} onSelect={selectExample} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Boundary invariant</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm leading-6 text-muted-foreground">
              <p>The final answer can include private details because it is generated inside the trusted boundary.</p>
              <p>The external consultant receives only the repaired sanitized prompt after checker pass and utility threshold.</p>
            </CardContent>
          </Card>
        </aside>

        <section className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-2">
            <PipelineCard title="Detected sensitive entities" badge={`${result?.detectedEntities?.length ?? 0} entities`}>
              <EntityTable entities={result?.detectedEntities ?? []} />
            </PipelineCard>

            <PipelineCard title="Raw prompt held locally" status="private" badge="trusted only">
              <TextBlock>{result?.rawPrompt ?? prompt}</TextBlock>
            </PipelineCard>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <SanitizedPromptCard title="Initial sanitized prompt" prompt={result?.initialSanitizedPrompt} />
            <CheckerResultCard title="Initial checker result" result={result?.checkerResult} />
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <RepairLoopCard prompt={result?.repairedSanitizedPrompt} repaired={Boolean(result?.repairedSanitizedPrompt)} />
            <CheckerResultCard title="Final checker result" result={result?.finalCheckerResult} />
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <UtilityScoreCard result={result?.utilityResult} />
            <ExternalConsultantCard response={result?.externalConsultantResponse} allowed={result?.externalCallAllowed} />
          </div>

          <FinalAnswerCard answer={result?.finalAnswer} />
          <WeaveTraceCard result={result} />
        </section>
      </div>
    </main>
  );
}

function formatStage(stage: string) {
  return stage.replaceAll("_", " ");
}

function BoundaryIcon({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <span className="inline-flex h-8 items-center gap-2 rounded-md border bg-white px-3">
      {icon}
      {label}
    </span>
  );
}
