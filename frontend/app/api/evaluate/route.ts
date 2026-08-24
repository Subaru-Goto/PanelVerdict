// 045/#143: the browser talks to its own origin; this handler holds the edge
// secret server-side — anything NEXT_PUBLIC_* is compiled into the client
// bundle by definition, so the secret must live here or authenticate nobody.
export async function POST(request: Request): Promise<Response> {
  const secret = process.env.API_SHARED_SECRET;
  // The backend's ledger counts callers by this header; without it every
  // visitor would arrive as this proxy's one egress IP and share one budget.
  const client = request.headers.get("x-forwarded-for");
  const response = await fetch(`${process.env.API_URL}/evaluate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(secret ? { "X-API-Key": secret } : {}),
      ...(client ? { "X-Forwarded-For": client } : {}),
    },
    body: await request.text(),
  });
  return new Response(response.body, {
    status: response.status,
    headers: {
      "Content-Type":
        response.headers.get("content-type") ?? "application/json",
    },
  });
}
