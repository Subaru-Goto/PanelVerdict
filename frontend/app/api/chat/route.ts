import { proxyPost } from "../proxy";

/** Seconds this route may run before the platform kills it.
 *
 * An analyst turn holds the connection open for as long as it streams, and a
 * turn may call up to three tools before answering. Same reasoning and same
 * caveat as the evaluate route: confirm the ceiling for the plan in use.
 */
export const maxDuration = 60;

export async function POST(request: Request): Promise<Response> {
  return proxyPost("/chat", request);
}
