import * as React from "react";

import { cn } from "@/lib/utils";

export function Textarea({ className, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "min-h-40 w-full resize-y rounded-md border border-input bg-white px-3 py-3 text-sm shadow-sm outline-none transition focus:ring-2 focus:ring-ring",
        className
      )}
      {...props}
    />
  );
}
