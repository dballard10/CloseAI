import type { ReactNode } from "react";

import { CheckCircle2, CircleAlert, Lock, ShieldCheck } from "lucide-react";

import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

type Status = "neutral" | "passed" | "failed" | "private";

const icon = {
  neutral: Lock,
  passed: ShieldCheck,
  failed: CircleAlert,
  private: CheckCircle2
};

export function PipelineCard({
  title,
  status = "neutral",
  badge,
  children
}: {
  title: string;
  status?: Status;
  badge?: string;
  children: ReactNode;
}) {
  const Icon = icon[status];
  const tone = status === "passed" || status === "private" ? "success" : status === "failed" ? "danger" : "muted";

  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <CardTitle className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-primary" />
          <span className="truncate">{title}</span>
        </CardTitle>
        {badge ? <Badge tone={tone}>{badge}</Badge> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export function TextBlock({ children }: { children: string }) {
  return <pre className="whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-sm leading-6">{children}</pre>;
}
