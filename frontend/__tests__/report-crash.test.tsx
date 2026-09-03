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
const runDemoMock = vi.fn();
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
  runDemo: (demoCase: string) => runDemoMock(demoCase),
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
  runDemoMock.mockReset();
  search = new URLSearchParams("open=t-1");
});

/** A promise the test settles by hand — for a Refresh caught mid-flight. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

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

  it("a Refresh the reader walked away from does not drag them back", async () => {
    // The reopen effect guards its fetch against unmount and a changed id;
    // Refresh must too, or a late response redraws a report the reader left
    // (049/#147, review). Each redraw also opens a paid analyst turn, so the
    // button is disabled while one refresh is in flight.
    vi.spyOn(console, "error").mockImplementation(() => {});
    const late = deferred<typeof GOOD>();
    myTestMock.mockResolvedValueOnce(BROKEN).mockReturnValueOnce(late.promise);

    render(<EvaluateForm tracing={false} />);
    await screen.findByText(/Something went wrong drawing this report/);

    const refresh = screen.getByRole("button", { name: "Refresh" });
    fireEvent.click(refresh);
    await waitFor(() => expect(myTestMock).toHaveBeenCalledTimes(2));
    expect((refresh as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /test again/i }));
    late.resolve(GOOD);
    await waitFor(() =>
      expect(screen.getByLabelText(/headline a/i)).toBeTruthy(),
    );
    // Settled after the leave: the form stays, no report comes back.
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText(/Redrawn line/)).toBeNull();
  });

  it("on the demo, the card appears too and Refresh reloads the page", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    search = new URLSearchParams("demo=free-delivery");
    runDemoMock.mockResolvedValue({
      ...BROKEN,
      status: "complete",
      thread_id: "t-run",
      step_seconds: { select: 0.09, vote: 45.3, assemble: 0.02 },
      captured_at: "2026-09-01",
    });

    render(<EvaluateForm tracing={false} />);

    // The replay paces its three steps at 600–2600 ms each before the report.
    await screen.findByText(
      /Something went wrong drawing this report/,
      undefined,
      {
        timeout: 8000,
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(reload).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });
});
