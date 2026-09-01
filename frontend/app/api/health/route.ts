// /health costs nothing and needs no secret, but proxying it too means the
// backend URL exists nowhere in client code — one discipline, no exceptions
// (pinned by bundle-discipline.test.ts). The fetch keeps this handler dynamic,
// so no caching config is needed (route handlers cache GET only on opt-in).
export async function GET(): Promise<Response> {
  const response = await fetch(`${process.env.API_URL}/health`);
  return new Response(response.body, {
    status: response.status,
    headers: {
      "Content-Type":
        response.headers.get("content-type") ?? "application/json",
    },
  });
}

/** Seconds this route may run: a cold Render start takes ~1 minute
 * (docs/deploy.md), and the platform default 504s these reads first —
 * the fuller rationale lives on /api/evaluate's copy of this number. */
export const maxDuration = 60;
