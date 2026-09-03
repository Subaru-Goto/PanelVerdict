import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeResponse } from "./fixtures";

const myTestMock = vi.fn();
const replaceMock = vi.fn();
let search = new URLSearchParams("open=t-1");

vi.mock("next/navigation", () => ({
  useSearchParams: () => search,
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

const GOOD = {
  ...makeResponse(),
  variants: { a: "Redrawn line", b: "Its rival" },
};
// The shape the ticket names (049/#147): a payload the fetch cast through
// unchecked, failing deep inside a formatter rather than at the boundary.
const BROKEN = { ...GOOD, tally: undefined } as unknown as typeof GOOD;

vi.mock("../app/lib/api", () => ({
  remainingRuns: () => Promise.resolve(3),
  evaluate: () => Promise.reject(new Error("not used")),
  resumeEvaluate: () => Promise.reject(new Error("not used")),
  LOCALES: ["US", "JP", "DE"],
  MIN_PANEL_AGE: 18,
  MAX_PANEL_AGE: 100,
  myTests: () => Promise.resolve({ tests: [], next_cursor: null }),
  myTest: (id: string) => myTestMock(id),
  forgetTest: () => Promise.resolve(),
  onRunsChanged: () => () => {},
}));

vi.mock("../app/lib/auth", () => ({
  displayName: () => Promise.resolve("Sam O."),
  onAuthChange: (listener: (value: boolean) => void) => {
    listener(true);
    return () => {};
  },
  authHeaders: () => Promise.resolve({}),
  signInAvailable: () => true,
}));

vi.mock("../app/lib/chat", () => ({
  streamChat: function* () {},
}));

const { default: EvaluateForm } =
  await import("../app/components/evaluate-form");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  myTestMock.mockReset();
  search = new URLSearchParams("open=t-1");
});

describe("a report that crashes while drawing (049/#147)", () => {
  it("keeps the page, says one sentence, and Refresh fetches and redraws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    myTestMock.mockResolvedValueOnce(BROKEN).mockResolvedValueOnce(GOOD);

    render(<EvaluateForm tracing={false} />);

    const card = await screen.findByText(
      "Something went wrong drawing this report. Refresh to load it again.",
    );
    expect(card).toBeTruthy();
    // The page around the report survived: its own controls are still there.
    expect(screen.getByRole("button", { name: /test again/i })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() => expect(myTestMock).toHaveBeenCalledTimes(2));
    expect(myTestMock).toHaveBeenLastCalledWith("t-1");
    expect(await screen.findAllByText(/Redrawn line/)).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
  });
});
