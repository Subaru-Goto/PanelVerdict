// 045/#143: the one place the edge secret exists. Route handlers run on the
// server only, so nothing here can reach the client bundle — which is the
// whole point: anything NEXT_PUBLIC_* ships to every visitor by definition.
export async function proxyPost(
  path: "/evaluate" | "/chat",
  request: Request,
): Promise<Response> {
  const secret = process.env.API_SHARED_SECRET;
  // The backend's ledger counts callers by this header; without it every
  // visitor would arrive as this proxy's one egress IP and share one budget.
  const client = request.headers.get("x-forwarded-for");
  const response = await fetch(`${process.env.API_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(secret ? { "X-API-Key": secret } : {}),
      ...(client ? { "X-Forwarded-For": client } : {}),
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
