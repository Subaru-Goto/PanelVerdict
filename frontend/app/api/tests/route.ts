import { proxyToBackend } from "../proxy";

/** Seconds this route may run: a cold Render start takes ~1 minute
 * (docs/deploy.md), and the platform default 504s these reads first —
 * the fuller rationale lives on /api/evaluate's copy of this number. */
export const maxDuration = 60;

/** The signed-in account's finished tests — what the rail lists (117/#252).
 *
 * Proxied like everything else so the backend URL and the edge secret stay
 * server-side (pinned by bundle-discipline.test.ts). A read of stored rows, so
 * it needs neither the run's longer execution budget nor its cost warnings.
 */
export async function GET(request: Request): Promise<Response> {
  // The rail pages (118/#253), so `cursor` and `limit` cross the edge —
  // rebuilt through URLSearchParams rather than passed through, so the values
  // are re-encoded and any other parameter a caller minted stops here.
  const incoming = new URL(request.url).searchParams;
  const forwarded = new URLSearchParams();
  for (const name of ["cursor", "limit"]) {
    const value = incoming.get(name);
    if (value !== null) forwarded.set(name, value);
  }
  return proxyToBackend(
    forwarded.size > 0 ? `/tests?${forwarded}` : "/tests",
    "GET",
    request,
  );
}
