"use client";

import type { Mode } from "@/lib/types";

import { Select } from "./ui/select";

const modes: Array<{ value: Mode; label: string }> = [
  { value: "hr", label: "HR" },
  { value: "legal", label: "Legal" },
  { value: "healthcare", label: "Healthcare" },
  { value: "education", label: "Education" },
  { value: "general", label: "General" }
];

export function ModeSelector({ value, onChange }: { value: Mode; onChange: (mode: Mode) => void }) {
  return (
    <Select value={value} onChange={(event) => onChange(event.target.value as Mode)} aria-label="Domain mode">
      {modes.map((mode) => (
        <option key={mode.value} value={mode.value}>
          {mode.label}
        </option>
      ))}
    </Select>
  );
}
