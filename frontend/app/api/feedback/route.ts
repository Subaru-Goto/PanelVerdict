import { proxyToBackend } from "../proxy";

/** A reader's message about one of their own tests (053/#150). Proxied like
 *  everything else so the backend URL and the edge secret stay server-side. */
export async function POST(request: Request): Promise<Response> {
  return proxyToBackend("/feedback", "POST", request);
}
