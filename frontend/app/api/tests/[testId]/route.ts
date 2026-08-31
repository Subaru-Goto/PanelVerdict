import { proxyToBackend } from "../../proxy";

/** One stored test: reopening it, and deleting it (117/#252).
 *
 * `testId` is the only path segment in this app that comes from a URL, so it is
 * encoded before it reaches the backend. Unencoded, a caller asking for
 * `/api/tests/..%2fme` would have this route build `/tests/../me` and proxy a
 * request to an endpoint it never named — the segment is caller text, and the
 * one place a proxy must not concatenate it raw.
 *
 * `RouteContext<'/api/tests/[testId]'>` rather than a hand-written
 * `{ params: Promise<{ testId: string }> }`: this version derives the param
 * names from the route literal, so renaming the folder is a type error here
 * instead of an `undefined` at runtime.
 */
export async function GET(
  request: Request,
  ctx: RouteContext<"/api/tests/[testId]">,
): Promise<Response> {
  const { testId } = await ctx.params;
  return proxyToBackend(`/tests/${encodeURIComponent(testId)}`, "GET", request);
}

export async function DELETE(
  request: Request,
  ctx: RouteContext<"/api/tests/[testId]">,
): Promise<Response> {
  const { testId } = await ctx.params;
  return proxyToBackend(
    `/tests/${encodeURIComponent(testId)}`,
    "DELETE",
    request,
  );
}
