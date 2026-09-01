import { proxyToBackend } from "../../proxy";

/** Seconds this route may run: a cold Render start takes ~1 minute
 * (docs/deploy.md), and the platform default 504s these reads first —
 * the fuller rationale lives on /api/evaluate's copy of this number. */
export const maxDuration = 60;

/** One demo case: a captured run, replayed by the backend (061/#156).
 *
 * Proxied like everything else so the backend URL stays server-side — but the
 * backend route is deliberately ungated, so this is the one proxy path where
 * the secret is a formality. The segment is caller text and is encoded for
 * the same reason `/tests/[testId]`'s is.
 */
export async function GET(
  request: Request,
  ctx: RouteContext<"/api/demo/[demoCase]">,
): Promise<Response> {
  const { demoCase } = await ctx.params;
  return proxyToBackend(
    `/demo/${encodeURIComponent(demoCase)}`,
    "GET",
    request,
  );
}
