import { proxyToBackend } from "../../proxy";

/** Answering the panel gate — accepting is what spends. The execution budget
 * every route shares lives in vercel.json (see proxyToBackend's note): a
 * re-export of another route's `maxDuration` here looked right and was
 * silently ignored by Next's static analysis. */

export async function POST(request: Request): Promise<Response> {
  return proxyToBackend("/evaluate/resume", "POST", request);
}
