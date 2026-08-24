import { afterEach, describe, expect, it, vi } from "vitest";

import { POST as chatProxy } from "../app/api/chat/route";
import { POST as evaluateProxy } from "../app/api/evaluate/route";

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

  it("names the real client to the backend, whose ledger counts callers", async () => {
    // Without this, every visitor arrives at the backend as this proxy's one
    // egress IP and shares a single rate-limit budget.
    vi.stubEnv("API_URL", "http://backend.test");
    vi.stubEnv("API_SHARED_SECRET", "edge-secret");
    const backend = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", backend);
    const request = new Request("http://frontend.test/api/evaluate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Forwarded-For": "203.0.113.9",
      },
      body: "{}",
    });

    await evaluateProxy(request);

    const [, init] = backend.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("X-Forwarded-For")).toBe(
      "203.0.113.9",
    );
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
