import { afterEach, describe, expect, it, vi } from "vitest";

import { DELETE as forgetMe, GET as readMe } from "../app/api/me/route";

// 063/#158 + 092/#197. Two things the account itself needs: how many runs it
// has left today, and a way to be erased. Both go through the proxy for the
// same reason every other call does — the backend URL and the edge secret
// exist only server-side.

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function request(method: string, headers: Record<string, string> = {}): Request {
  return new Request("http://frontend.test/api/me", { method, headers });
}

function stubBackend(body: string | null = "{}", status = 200) {
  // null, not "": the Response constructor rejects a body on a 204, which is
  // exactly what the backend answers a successful deletion with.
  const backend = vi.fn().mockResolvedValue(new Response(body, { status }));
  vi.stubEnv("API_URL", "http://backend.test");
  vi.stubEnv("API_SHARED_SECRET", "edge-secret");
  vi.stubGlobal("fetch", backend);
  return backend;
}

describe("the account route", () => {
  it("relays the remaining-runs figure for the signed-in account", async () => {
    const backend = stubBackend(
      JSON.stringify({ runs_per_day: 3, runs_remaining: 2 }),
    );

    const response = await readMe(
      request("GET", { Authorization: "Bearer a-session-jwt" }),
    );

    const [url, init] = backend.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://backend.test/me");
    expect(init.method).toBe("GET");
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer a-session-jwt",
    );
    expect(new Headers(init.headers).get("X-API-Key")).toBe("edge-secret");
    expect(await response.json()).toEqual({
      runs_per_day: 3,
      runs_remaining: 2,
    });
  });

  it("passes a deletion request through as a deletion", async () => {
    // Erasure is the one request here that cannot be retried into existence
    // if the method were wrong, so the method is asserted rather than assumed.
    const backend = stubBackend(null, 204);

    const response = await forgetMe(
      request("DELETE", { Authorization: "Bearer a-session-jwt" }),
    );

    const [url, init] = backend.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://backend.test/me");
    expect(init.method).toBe("DELETE");
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer a-session-jwt",
    );
    expect(response.status).toBe(204);
  });

  it("relays the backend's refusal when nobody is signed in", async () => {
    // The browser must see the 401 rather than a proxy-invented success.
    const backend = stubBackend(JSON.stringify({ detail: "sign in" }), 401);

    const response = await readMe(request("GET"));

    expect(new Headers((backend.mock.calls[0] as [string, RequestInit])[1].headers).get(
      "Authorization",
    )).toBeNull();
    expect(response.status).toBe(401);
  });
});
