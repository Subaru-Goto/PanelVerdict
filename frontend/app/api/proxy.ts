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

export async function proxyPost(
  path: "/evaluate" | "/chat",
  request: Request,
): Promise<Response> {
  const secret = process.env.API_SHARED_SECRET;
  const response = await fetch(`${process.env.API_URL}${path}`, {
    method: "POST",
    // Built from scratch, never spread from the incoming request: this route
    // is public, so every header a caller sent is untrusted input. Only these
    // three reach the backend.
    headers: {
      "Content-Type": "application/json",
      ...(secret ? { "X-API-Key": secret } : {}),
      ...(clientId(request) ? { "X-Client-Id": clientId(request)! } : {}),
    },
    body: await request.text(),
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
