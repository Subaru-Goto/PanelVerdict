import { proxyToBackend } from "../../../proxy";

/** Seconds this route may run: a cold Render start takes ~1 minute
 * (docs/deploy.md), and the platform default 504s these reads first —
 * the fuller rationale lives on /api/evaluate's copy of this number. */
export const maxDuration = 60;

/** The run's live vote count (021/#126), polled by the waiting screen. The
 * segment is caller text and is encoded for the same reason
 * `/tests/[testId]`'s is. */
export async function GET(
  request: Request,
  ctx: RouteContext<"/api/evaluate/[threadId]/progress">,
): Promise<Response> {
  const { threadId } = await ctx.params;
  return proxyToBackend(
    `/evaluate/${encodeURIComponent(threadId)}/progress`,
    "GET",
    request,
  );
}
