import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const PYTHON_SERVICE_URL = process.env.CLOSEDAI_PYTHON_URL ?? "http://127.0.0.1:8000";

export async function GET() {
  try {
    const response = await fetch(`${PYTHON_SERVICE_URL}/api/health`, {
      cache: "no-store"
    });

    if (!response.ok) {
      throw new Error(`Python service returned ${response.status}`);
    }

    return NextResponse.json(await response.json());
  } catch (error) {
    return NextResponse.json(
      {
        status: "offline",
        product: "ClosedAI",
        consult_pipeline: `offline/setup needed: ${(error as Error).message}`,
        internal_provider: "unknown",
        external_provider: "unknown"
      },
      { status: 200 }
    );
  }
}
