import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Allowance from "../app/components/allowance";
import { forgetTest } from "../app/lib/api";

// The real api module and the real notice, composed: the two halves (a delete
// announces; the notice re-reads on an announcement) each have their own
// tests, and this is the one place they meet (124/#291, seam 3).

vi.mock("../app/lib/auth", () => ({
  authHeaders: () => Promise.resolve({ Authorization: "Bearer t" }),
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("a full rail's notice", () => {
  it("goes the moment a saved test is deleted", async () => {
    let saved = 10;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === "DELETE") {
          saved -= 1;
          return Promise.resolve(new Response(null, { status: 204 }));
        }
        expect(url).toBe("/api/me");
        return Promise.resolve(
          new Response(
            JSON.stringify({
              runs_per_day: 3,
              runs_remaining: 3,
              saved_tests: saved,
              saved_tests_cap: 10,
            }),
            { status: 200 },
          ),
        );
      }),
    );

    await act(async () => {
      render(<Allowance />);
    });
    expect(await screen.findByText(/rail is full/i)).toBeTruthy();

    await act(async () => {
      await forgetTest("t-1");
    });

    expect(screen.queryByText(/rail is full/i)).toBeNull();
    expect(screen.getByText("3 runs left today")).toBeTruthy();
  });
});
