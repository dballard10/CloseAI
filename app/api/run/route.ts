import { NextResponse } from "next/server";

import { fallbackResponse } from "@/lib/demo-data";
import type { RunRequest } from "@/lib/types";

export const dynamic = "force-dynamic";

const PYTHON_SERVICE_URL = process.env.CLOSEDAI_PYTHON_URL ?? "http://127.0.0.1:8000";

export async function POST(request: Request) {
  const body = (await request.json()) as RunRequest;

  try {
    const response = await fetch(`${PYTHON_SERVICE_URL}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store"
    });

    if (!response.ok) {
      throw new Error(`Python service returned ${response.status}`);
    }

    return NextResponse.json(await response.json());
  } catch (error) {
    return NextResponse.json({
      ...fallbackResponse,
      rawPrompt: body.rawPrompt || fallbackResponse.rawPrompt,
      weaveMetadata: {
        ...fallbackResponse.weaveMetadata,
        status: `using Next.js fallback mock: ${(error as Error).message}`
      }
    });
  }
}
