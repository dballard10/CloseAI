import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const PYTHON_SERVICE_URL = process.env.CLOSEDAI_PYTHON_URL ?? "http://127.0.0.1:8000";

export async function POST(request: Request) {
  const body = await request.json();

  try {
    const response = await fetch(`${PYTHON_SERVICE_URL}/revise-classification`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rawPrompt: body.rawPrompt,
        feedback: body.feedback,
        mode: "general"
      }),
      cache: "no-store"
    });

    if (!response.ok) {
      throw new Error(`Python service returned ${response.status}`);
    }

    return NextResponse.json(await response.json());
  } catch (error) {
    return NextResponse.json(
      { error: `Revision failed: ${(error as Error).message}` },
      { status: 502 }
    );
  }
}
