// 045/#143: the one place the edge secret exists. Route handlers run on the
// server only, so nothing here can reach the client bundle — which is the
// whole point: anything NEXT_PUBLIC_* ships to every visitor by definition.
/** Who the backend's rate limiter should count.
 *
 * Exactly one header qualifies: `x-vercel-forwarded-for`, which Vercel stamps
 * at its edge where an incoming request cannot reach. This route is public, so
 * every other candidate is caller-writable — `x-client-id` and
 * `x-forwarded-for` outright (the latter is appended to rather than replaced,
 * making its leftmost entry attacker text), and `x-real-ip` is merely a
 * convention: off Vercel a visitor sends it themselves and mints unlimited
 * budgets, which is the hole the move away from `x-forwarded-for` closed.
 * Returning null where the platform names nobody (local `next dev`) leaves the
 * backend counting the socket peer rather than trusting caller text.
 */
function clientId(request: Request): string | null {
  return request.headers.get("x-vercel-forwarded-for");
}

export async function proxyToBackend(
  path: "/evaluate" | "/chat" | "/me",
  method: "GET" | "POST" | "DELETE",
  request: Request,
): Promise<Response> {
  const secret = process.env.API_SHARED_SECRET;
  const response = await fetch(`${process.env.API_URL}${path}`, {
    method,
    // Built from scratch, never spread from the incoming request: this route
    // is public, so every header a caller sent is untrusted input. Only these
    // three reach the backend.
    headers: {
      "Content-Type": "application/json",
      ...(secret ? { "X-API-Key": secret } : {}),
      ...(clientId(request) ? { "X-Client-Id": clientId(request)! } : {}),
      // The one incoming header that is forwarded, and forwarded *because* it
      // is caller-written (063/#158): the backend verifies its signature
      // against the project's published keys, so a forged one buys nothing.
      // Every other header here is stamped by this route precisely because
      // the backend could not check it. Passed through untouched — this route
      // does not verify it, and a proxy that half-checked a token would only
      // add a second opinion to disagree with the real one.
      ...(request.headers.get("authorization")
        ? { Authorization: request.headers.get("authorization")! }
        : {}),
    },
    // GET and DELETE carry nothing; `fetch` rejects a body on either, and
    // reading one that was never sent would hang on an empty stream.
    ...(method === "POST" ? { body: await request.text() } : {}),
  });
  // The body is handed over as the stream it already is — /chat's tokens are
  // worth nothing after the conversation moved on, so nothing here buffers.
  return new Response(response.body, {
    status: response.status,
    headers: {
      "Content-Type":
        response.headers.get("content-type") ?? "application/json",
    },
  });
}
