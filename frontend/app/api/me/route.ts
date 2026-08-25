import { proxyToBackend } from "../proxy";

/** The signed-in account: what it has left today, and erasing it (063/#158).
 *
 * Proxied like everything else so the backend URL and the edge secret stay
 * server-side (pinned by bundle-discipline.test.ts). Neither method spends
 * money on a model, so neither needs the run's longer execution budget.
 */

export async function GET(request: Request): Promise<Response> {
  return proxyToBackend("/me", "GET", request);
}

export async function DELETE(request: Request): Promise<Response> {
  return proxyToBackend("/me", "DELETE", request);
}
