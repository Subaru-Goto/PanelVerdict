import { proxyToBackend } from "../proxy";

/** The signed-in account's finished tests — what the rail lists (117/#252).
 *
 * Proxied like everything else so the backend URL and the edge secret stay
 * server-side (pinned by bundle-discipline.test.ts). A read of stored rows, so
 * it needs neither the run's longer execution budget nor its cost warnings.
 */
export async function GET(request: Request): Promise<Response> {
  return proxyToBackend("/tests", "GET", request);
}
