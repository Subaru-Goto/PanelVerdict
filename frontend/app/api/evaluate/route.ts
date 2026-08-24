// 045/#143: the browser talks to its own origin; this handler holds the edge
// secret server-side — anything NEXT_PUBLIC_* is compiled into the client
// bundle by definition, so the secret must live here or authenticate nobody.
export async function POST(request: Request): Promise<Response> {
  const secret = process.env.API_SHARED_SECRET;
  const response = await fetch(`${process.env.API_URL}/evaluate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(secret ? { "X-API-Key": secret } : {}),
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
