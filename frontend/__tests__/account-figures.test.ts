import { afterEach, describe, expect, it, vi } from "vitest";

import { accountFigures } from "../app/lib/api";

// Signed in: without a bearer the read is skipped, and that is not what these
// tests are about.
vi.mock("../app/lib/auth", () => ({
  authHeaders: () => Promise.resolve({ Authorization: "Bearer t" }),
}));

const stubMe = (status: number, body: unknown) =>
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })),
  );

afterEach(() => vi.unstubAllGlobals());

describe("accountFigures", () => {
  it("reads the runs left and the rail's figures", async () => {
    stubMe(200, {
      runs_per_day: 3,
      runs_remaining: 2,
      saved_tests: 10,
      saved_tests_cap: 10,
    });

    expect(await accountFigures()).toEqual({
      runs_remaining: 2,
      saved_tests: 10,
      saved_tests_cap: 10,
    });
  });

  it("keeps the runs figure when the backend does not report the rail yet", async () => {
    // Frontend and backend deploy separately; for the minutes the backend is
    // behind, the runs-left line should not vanish along with the notice.
    stubMe(200, { runs_per_day: 3, runs_remaining: 2 });

    expect(await accountFigures()).toEqual({ runs_remaining: 2 });
  });

  it("is null when the read fails", async () => {
    // Null rather than zeros: a failed read must not say "no runs left".
    stubMe(500, { detail: "down" });

    expect(await accountFigures()).toBeNull();
  });
});
