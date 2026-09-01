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

/** Whether this deployment is tracing, for the server-rendered form.
 *
 * Lives here because this file is where the backend URL is allowed to exist.
 * Unreachable counts as not tracing: a backend the page cannot reach cannot
 * accept a run either, so nothing is being traced to warn about.
 */
export async function backendTracing({
  // Derived, not picked: /health opens its own database connection with
  // `connect_timeout=3` (backend/app/db.py), so a budget under 3s can abort a
  // backend that is alive, slow, and tracing — dropping the disclosure exactly
  // when it is owed. One second over that floor. A backend still silent after
  // it is one that "wakes in ~1 minute" (docs/deploy.md); waiting that out
  // would cost the page a minute to decide one line.
  timeoutMs = 4000,
}: { timeoutMs?: number } = {}): Promise<boolean> {
  try {
    const response = await fetch(`${process.env.API_URL}/health`, {
      // The disclosure must describe this deployment now, not whichever one
      // was up when the page was last built. This is also what makes the page
      // render at request time rather than being prerendered.
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) return false;
    const health = (await response.json()) as { tracing?: string };
    return health.tracing === "on";
  } catch {
    return false;
  }
}

/** Every route through here runs under one execution budget, set platform-side
 * in vercel.json ("app/api/**" → maxDuration 60) and pinned by proxy.test.ts.
 * Sourced: a prod run measures ~40s (010a) and a cold Render start ~1 minute
 * (docs/deploy.md) — the platform default 504s first, after the ledger has
 * already charged the run. One rule rather than per-file exports, because a
 * re-exported segment config is silently ignored by Next 16.2's static
 * analysis and a hand-pasted literal is a list a new route silently misses. */
export async function proxyToBackend(
  // A closed set, plus the one path with a caller-supplied segment. The
  // template literal keeps `/tests/<id>` inside the type while still requiring
  // every other path to be spelled here — a bare `string` would let any caller
  // text become a backend path (117/#252).
  path:
    | "/evaluate"
    | "/evaluate/resume"
    | "/chat"
    | "/me"
    | "/tests"
    | `/tests?${string}`
    | `/tests/${string}`
    | `/demo/${string}`
    | `/evaluate/${string}/progress`,
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
