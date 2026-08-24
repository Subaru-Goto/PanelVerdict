import { afterEach, describe, expect, it, vi } from "vitest";

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
});
