// 045/#143: the one place the edge secret exists. Route handlers run on the
// server only, so nothing here can reach the client bundle — which is the
// whole point: anything NEXT_PUBLIC_* ships to every visitor by definition.
/** Who the backend's rate limiter should count.
 *
 * Only headers the *platform* sets are trustworthy here: this route is public,
 * so a visitor can send any `x-client-id` or `x-forwarded-for` they like, and
 * `x-forwarded-for` is appended to rather than replaced — its leftmost entry
 * is caller-written text. Vercel sets `x-vercel-forwarded-for` and `x-real-ip`
 * at the edge, where a request cannot reach. Returning null when neither
 * exists (local `next dev`) leaves the backend to count the socket peer rather
 * than trust anything a caller wrote.
 */
function clientId(request: Request): string | null {
  return (
    request.headers.get("x-vercel-forwarded-for") ??
    request.headers.get("x-real-ip")
  );
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
