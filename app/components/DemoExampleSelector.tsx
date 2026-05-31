"use client";

import type { DemoExample } from "@/lib/types";

import { Button } from "./ui/button";

export function DemoExampleSelector({
  examples,
  onSelect
}: {
  examples: DemoExample[];
  onSelect: (example: DemoExample) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {examples.map((example) => (
        <Button key={example.label} type="button" variant="secondary" size="sm" onClick={() => onSelect(example)}>
          {example.label}
        </Button>
      ))}
    </div>
  );
}
