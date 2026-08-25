import { proxyToBackend } from "../../proxy";

/** Answering the panel gate.
 *
 * Its own route because it hits a different backend path, and it reuses
 * `/api/evaluate`'s execution budget because accepting is what spends. */
export { maxDuration } from "../route";

export async function POST(request: Request): Promise<Response> {
  return proxyToBackend("/evaluate/resume", "POST", request);
}
