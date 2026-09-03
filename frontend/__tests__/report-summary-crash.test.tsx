import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeResponse } from "./fixtures";

// An analyst whose state cannot be read: the summary card and the dock both
// format it, so both must fail inside the analyst's boundary, not the report's.
vi.mock("../app/lib/use-analyst", () => ({
  OPENING_REQUEST: "opening",
  useAnalyst: () => ({
    get turns(): never {
      throw new TypeError("turns are unreadable");
    },
    busy: false,
    send: () => Promise.resolve(),
  }),
}));

const { default: Report } = await import("../app/components/report");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("the analyst boundary (049/#147)", () => {
  it("keeps the verdict when the analyst's summary card crashes", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const result = makeResponse({
      variants: { a: "Kept line", b: "Its rival" },
    });

    render(<Report result={result} testId="t-1" onRefresh={() => {}} />);

    expect(screen.getAllByText(/Kept line/).length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(
        "The analyst is unavailable right now. Refresh to try again.",
      ).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText(/Something went wrong drawing/)).toBeNull();
  });
});
