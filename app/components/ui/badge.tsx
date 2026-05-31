import * as React from "react";

import { cn } from "@/lib/utils";

type BadgeProps = React.HTMLAttributes<HTMLSpanElement> & {
  tone?: "default" | "success" | "warning" | "danger" | "muted";
};

export function Badge({ className, tone = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center rounded-md border px-2 text-xs font-medium",
        tone === "default" && "border-primary/25 bg-primary/10 text-primary",
        tone === "success" && "border-emerald-700/20 bg-emerald-50 text-emerald-700",
        tone === "warning" && "border-amber-700/20 bg-amber-50 text-amber-800",
        tone === "danger" && "border-red-700/20 bg-red-50 text-red-700",
        tone === "muted" && "border-border bg-muted text-muted-foreground",
        className
      )}
      {...props}
    />
  );
}
