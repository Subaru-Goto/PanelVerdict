import { afterEach, describe, expect, it, vi } from "vitest";

import {
  maxDuration as chatMaxDuration,
  POST as chatProxy,
} from "../app/api/chat/route";
import {
  maxDuration as evaluateMaxDuration,
  POST as evaluateProxy,
} from "../app/api/evaluate/route";
import { backendTracing } from "../app/api/proxy";

// 045/#143: the browser never holds the edge secret — these route handlers do,
// server-side. The tests stub the backend fetch the way api.test.ts stubs it.

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function proxyRequest(body: unknown): Request {
  return new Request("http://frontend.test/api/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("the evaluate proxy", () => {
  it("forwards to the backend with the edge secret and relays the answer", async () => {
    vi.stubEnv("API_URL", "http://backend.test");
    vi.stubEnv("API_SHARED_SECRET", "edge-secret");
    const backend = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ verdict: "stub" }), { status: 200 }),
      );
    vi.stubGlobal("fetch", backend);

    const response = await evaluateProxy(
      proxyRequest({
        target_description: "t",
        headline_a: "a",
        headline_b: "b",
      }),
    );

    const [url, init] = backend.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://backend.test/evaluate");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-API-Key")).toBe("edge-secret");
    expect(JSON.parse(String(init.body))).toEqual({
      target_description: "t",
      headline_a: "a",
      headline_b: "b",
    });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ verdict: "stub" });
  });

  it("overwrites a forged client id with the platform's own value", async () => {
    // The proxy is public, so a caller can send any header they like. The
    // backend counts X-Client-Id, so whatever arrives under that name — or
    // under X-Forwarded-For, which platforms append to rather than replace —
    // must never survive into the upstream request.
    vi.stubEnv("API_URL", "http://backend.test");
    vi.stubEnv("API_SHARED_SECRET", "edge-secret");
    const backend = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", backend);

    await evaluateProxy(
      new Request("http://frontend.test/api/evaluate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Client-Id": "attacker-chosen",
          "X-Forwarded-For": "10.0.0.1, 203.0.113.9",
          "X-Vercel-Forwarded-For": "198.51.100.7",
        },
        body: "{}",
      }),
    );

    const [, init] = backend.mock.calls[0] as [string, RequestInit];
    const sent = new Headers(init.headers);
    expect(sent.get("X-Client-Id")).toBe("198.51.100.7");
    expect(sent.get("X-Forwarded-For")).toBeNull();
  });

  it("ignores x-real-ip, which only Vercel's edge makes trustworthy", async () => {
    // x-vercel-forwarded-for is stamped by Vercel and unreachable from a
    // request; x-real-ip is a convention any host may leave unset — and off
    // Vercel a visitor could send it themselves, reopening the very hole the
    // move away from X-Forwarded-For closed.
    vi.stubEnv("API_URL", "http://backend.test");
    vi.stubEnv("API_SHARED_SECRET", "edge-secret");
    const backend = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", backend);

    await evaluateProxy(
      new Request("http://frontend.test/api/evaluate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Real-IP": "attacker-chosen",
        },
        body: "{}",
      }),
    );

    const [, init] = backend.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("X-Client-Id")).toBeNull();
  });

  it("asserts no client id when the platform names no client", async () => {
    // Local `next dev` has no edge to stamp one. Sending nothing is the honest
    // answer: the backend then counts the socket peer, rather than being
    // handed a value a caller could have written.
    vi.stubEnv("API_URL", "http://backend.test");
    vi.stubEnv("API_SHARED_SECRET", "edge-secret");
    const backend = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", backend);

    await evaluateProxy(
      new Request("http://frontend.test/api/evaluate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Client-Id": "attacker-chosen",
        },
        body: "{}",
      }),
    );

    const [, init] = backend.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("X-Client-Id")).toBeNull();
  });
});

describe("the proxy routes' execution budget", () => {
  it("allows longer than a full panel run takes", () => {
    // Routing through a function inserts a timeout the direct-to-backend path
    // never had. A prod run measures ~40s (010a: 4.65 s/vote, concurrency 25,
    // 200 votes), and a platform default of a few seconds would 504 the
    // visitor while the backend keeps working — and the ledger has already
    // charged the run.
    const measuredRunSeconds = 40;

    expect(evaluateMaxDuration).toBeGreaterThan(measuredRunSeconds);
    expect(chatMaxDuration).toBeGreaterThan(measuredRunSeconds);
  });
});

describe("the chat proxy", () => {
  it("pipes the NDJSON stream through instead of buffering it", async () => {
    // The first token must reach the reader while the backend stream is still
    // open — a proxy that collects the body would hang right here, because
    // the analyst's answer is worth nothing after the conversation moved on.
    vi.stubEnv("API_URL", "http://backend.test");
    vi.stubEnv("API_SHARED_SECRET", "edge-secret");
    let backendStream!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        backendStream = controller;
      },
    });
    const backend = vi.fn().mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: { "Content-Type": "application/x-ndjson" },
      }),
    );
    vi.stubGlobal("fetch", backend);
    const encoder = new TextEncoder();

    const response = await chatProxy(
      new Request("http://frontend.test/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: "t-1", message: "why?", result: {} }),
      }),
    );
    const reader = response.body!.getReader();
    backendStream.enqueue(encoder.encode('{"type":"token","text":"pie"}\n'));
    const first = await reader.read();
    backendStream.enqueue(encoder.encode('{"type":"done"}\n'));
    backendStream.close();
    const second = await reader.read();

    expect(
      new Headers(
        (backend.mock.calls[0] as [string, RequestInit])[1].headers,
      ).get("X-API-Key"),
    ).toBe("edge-secret");
    expect(response.headers.get("content-type")).toBe("application/x-ndjson");
    expect(new TextDecoder().decode(first.value)).toContain('"pie"');
    expect(new TextDecoder().decode(second.value)).toContain('"done"');
  });
});

describe("the proxy and the signed-in session", () => {
  it("forwards the session token, the one header the backend can check itself", async () => {
    // 063/#158. Every other header this route sends is stamped here because
    // the backend could not tell a real one from a forged one. A signed token
    // it can, so passing it through is safe — and necessary, since the quota
    // it enforces is per account.
    vi.stubEnv("API_URL", "http://backend.test");
    vi.stubEnv("API_SHARED_SECRET", "edge-secret");
    const backend = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", backend);

    await evaluateProxy(
      new Request("http://frontend.test/api/evaluate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer a-session-jwt",
        },
        body: "{}",
      }),
    );

    const [, init] = backend.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer a-session-jwt",
    );
  });

  it("sends no authorization when the browser sent none", async () => {
    vi.stubEnv("API_URL", "http://backend.test");
    vi.stubEnv("API_SHARED_SECRET", "edge-secret");
    const backend = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", backend);

    await evaluateProxy(proxyRequest({}));

    const [, init] = backend.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBeNull();
  });
});

describe("the tracing disclosure's source", () => {
  it("reports what the backend says, so one deployment answers for both", async () => {
    // The alternative — a NEXT_PUBLIC_ flag set beside the backend's — is two
    // places to set one fact, and the drift stays invisible until someone
    // opens both dashboards.
    vi.stubEnv("API_URL", "http://backend.test");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ status: "ok", tracing: "on" })),
        ),
    );

    expect(await backendTracing()).toBe(true);
  });

  it("says not-tracing when the backend cannot be reached", async () => {
    // Off, not on, and it is the safe default rather than the optimistic one:
    // a backend this page cannot reach is a backend that cannot accept a run
    // either, so there is nothing being traced to disclose.
    vi.stubEnv("API_URL", "http://backend.test");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("ECONNREFUSED")),
    );

    expect(await backendTracing()).toBe(false);
  });

  it("gives up rather than holding the page open", async () => {
    // The page is server-rendered, so this fetch sits in front of the reader's
    // first byte. Node's fetch has no default timeout, and the backend is on a
    // free tier that sleeps — without a bound, one cold start is a page that
    // never paints. A deadline the disclosure misses is better than that.
    vi.stubEnv("API_URL", "http://backend.test");
    const backend = vi.fn().mockImplementation(({ signal }: RequestInit = {}) =>
      new Promise((_, reject) =>
        signal?.addEventListener("abort", () => reject(new Error("aborted"))),
      ),
    );
    vi.stubGlobal("fetch", (_url: string, init: RequestInit) => backend(init));

    expect(await backendTracing({ timeoutMs: 5 })).toBe(false);
  });
});
