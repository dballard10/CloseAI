import type { SensitiveEntity } from "@/lib/types";

import { Badge } from "./ui/badge";

const riskTone = {
  high: "danger",
  medium: "warning",
  low: "muted"
} as const;

export function EntityTable({ entities }: { entities: SensitiveEntity[] }) {
  if (!entities.length) {
    return <p className="text-sm text-muted-foreground">No sensitive entities detected.</p>;
  }

  return (
    <div className="overflow-hidden rounded-md border">
      <table className="w-full table-fixed text-left text-sm">
        <thead className="bg-muted text-xs uppercase text-muted-foreground">
          <tr>
            <th className="w-[34%] px-3 py-2 font-medium">Text</th>
            <th className="w-[27%] px-3 py-2 font-medium">Type</th>
            <th className="w-[19%] px-3 py-2 font-medium">Risk</th>
            <th className="px-3 py-2 font-medium">Replacement</th>
          </tr>
        </thead>
        <tbody>
          {entities.map((entity) => (
            <tr key={`${entity.text}-${entity.type}`} className="border-t">
              <td className="break-words px-3 py-2 font-medium">{entity.text}</td>
              <td className="break-words px-3 py-2 text-muted-foreground">{entity.type}</td>
              <td className="px-3 py-2">
                <Badge tone={riskTone[entity.risk]}>{entity.risk}</Badge>
              </td>
              <td className="break-words px-3 py-2 text-muted-foreground">{entity.replacementHint ?? "semantic abstraction"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
