import { proxyPost } from "../proxy";

/** Seconds this route may run before the platform kills it.
 *
 * Proxying inserts a timeout the browser's direct-to-backend calls never had,
 * and the work behind it is slow by nature: a prod run measures ~40s (010a:
 * 4.65 s/vote at concurrency 25, 200 votes) and a cold Render instance adds
 * ~1 minute (docs/deploy.md). A platform default of a few seconds would 504
 * the visitor while the backend runs on — and the ledger has already charged
 * the run. 60 buys the measured run with margin; a host may cap it lower, so
 * confirm the ceiling for the plan in use rather than trusting this number.
 */
export const maxDuration = 60;

export async function POST(request: Request): Promise<Response> {
  return proxyPost("/evaluate", request);
}
