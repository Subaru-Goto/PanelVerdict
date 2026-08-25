import { afterEach, describe, expect, it, vi } from "vitest";

import { evaluate } from "../app/lib/api";
import { accessToken } from "../app/lib/auth";

// 063/#158: the browser proves who is spending. The token travels on the one
// header whose contents the backend can check for itself — everything else a
// caller sends is untrusted by construction, which is why the proxy builds its
// headers from scratch.

vi.mock("../app/lib/auth", () => ({ accessToken: vi.fn() }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(accessToken).mockReset();
});

const INPUT = { targetDescription: "t", headlineA: "a", headlineB: "b" };

function stubbedFetch() {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

describe("a paid call from the browser", () => {
  it("carries the signed-in session as a bearer token", async () => {
    vi.mocked(accessToken).mockResolvedValue("a-session-jwt");
    const fetcher = stubbedFetch();

    await evaluate(INPUT);

    const [, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer a-session-jwt",
    );
  });

  it("sends no authorization at all when nobody is signed in", async () => {
    // Not an empty bearer, and not a made-up id: the backend's refusal is the
    // correct outcome here, and inventing a header would only obscure it.
    vi.mocked(accessToken).mockResolvedValue(null);
    const fetcher = stubbedFetch();

    await evaluate(INPUT);

    const [, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBeNull();
  });
});
