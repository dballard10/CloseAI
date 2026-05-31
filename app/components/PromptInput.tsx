"use client";

import { Play } from "lucide-react";

import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";

export function PromptInput({
  value,
  onChange,
  onRun,
  running
}: {
  value: string;
  onChange: (value: string) => void;
  onRun: () => void;
  running: boolean;
}) {
  return (
    <div className="space-y-3">
      <Textarea value={value} onChange={(event) => onChange(event.target.value)} />
      <Button className="w-full" onClick={onRun} disabled={running || value.trim().length === 0}>
        <Play className="h-4 w-4" />
        {running ? "Running pipeline" : "Run privacy gate"}
      </Button>
    </div>
  );
}
