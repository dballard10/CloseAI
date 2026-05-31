import { NextResponse } from "next/server";

import { fallbackResponse } from "@/lib/demo-data";
import type { RunRequest } from "@/lib/types";

export const dynamic = "force-dynamic";

const PYTHON_SERVICE_URL = process.env.CLOSEDAI_PYTHON_URL ?? "http://127.0.0.1:8000";

export async function POST(request: Request) {
  const body = (await request.json()) as RunRequest;

  try {
    const response = await fetch(`${PYTHON_SERVICE_URL}/run/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rawPrompt: body.rawPrompt, mode: "general" }),
      cache: "no-store"
    });

    if (!response.ok || !response.body) {
      throw new Error(`Python service returned ${response.status}`);
    }

    return new Response(response.body, {
      headers: {
        "Content-Type": "application/x-ndjson; charset=utf-8",
        "Cache-Control": "no-cache, no-transform"
      }
    });
  } catch (error) {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            `${JSON.stringify({
              stage: "fallback",
              patch: {
                ...fallbackResponse,
                rawPrompt: body.rawPrompt || fallbackResponse.rawPrompt,
                weaveMetadata: {
                  ...fallbackResponse.weaveMetadata,
                  status: `using Next.js fallback mock: ${(error as Error).message}`
                }
              }
            })}\n`
          )
        );
        controller.close();
      }
    });

    return new NextResponse(stream, {
      headers: {
        "Content-Type": "application/x-ndjson; charset=utf-8",
        "Cache-Control": "no-cache, no-transform"
      }
    });
  }
}
