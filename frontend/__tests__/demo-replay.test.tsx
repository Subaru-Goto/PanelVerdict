import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeResponse } from "./fixtures";

// The $0 demo (061/#156): a captured run replayed through the real graph,
// reachable signed out from `/test?demo=<case>`. What is pinned here: the
// wall stays open for it, the steps print the capture's own seconds, the
// report is the real report component, and the analyst is signed-in only —
// a line saying why, never a dead control.

const runDemoMock = vi.fn();
const myTestMock = vi.fn();
const streamChatMock = vi.fn();

let search = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useSearchParams: () => search,
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("../app/lib/api", () => ({
  evaluate: () => Promise.reject(new Error("not used")),
  resumeEvaluate: () => Promise.reject(new Error("not used")),
  runDemo: (demoCase: string) => runDemoMock(demoCase),
  streamChat: (...args: unknown[]) => streamChatMock(...args),
  LOCALES: ["US", "JP", "DE"],
  MIN_PANEL_AGE: 18,
  MAX_PANEL_AGE: 100,
  myTests: () => Promise.resolve({ tests: [], next_cursor: null }),
  myTest: (id: string) => myTestMock(id),
  forgetTest: () => Promise.resolve(),
  onRunsChanged: () => () => {},
}));

// Signed out, and sign-in configured: the exact state whose wall must not
// stop the demo.
vi.mock("../app/lib/auth", () => ({
  onAuthChange: (listener: (value: boolean) => void) => {
    listener(false);
    return () => {};
  },
  signInAvailable: () => true,
  mountGoogleButton: vi.fn(),
}));

import EvaluateForm from "../app/components/evaluate-form";

const DEMO = {
  ...makeResponse(),
  status: "complete",
  thread_id: "t-run",
  step_seconds: { select: 0.09, vote: 45.3, assemble: 0.02 },
  captured_at: "2026-09-01",
};

afterEach(cleanup);

beforeEach(() => {
  vi.useRealTimers();
  runDemoMock.mockReset();
  streamChatMock.mockReset();
  search = new URLSearchParams("demo=free-delivery");
});

describe("the demo replay", () => {
  it("runs signed out — the wall does not stop the sample", async () => {
    runDemoMock.mockResolvedValue(DEMO);
    render(<EvaluateForm tracing={false} />);

    expect(await screen.findByText(/panel assembled/i)).toBeTruthy();
    expect(runDemoMock).toHaveBeenCalledWith("free-delivery");
    expect(screen.queryByText(/sign in to run a test/i)).toBeNull();
    // Art. 50 does not pause for a demo: the AI-system disclosure shows
    // from the first frame of the playback.
    expect(screen.getByText(/AI system/)).toBeTruthy();
  });

  it("prints the captured run's own seconds on the steps", async () => {
    runDemoMock.mockResolvedValue(DEMO);
    render(<EvaluateForm tracing={false} />);

    expect(await screen.findByText("45.3 s")).toBeTruthy();
    // Sub-second steps print milliseconds — "0.0 s" would round a real
    // duration away, and a rounded-away number reads as an invented one.
    expect(screen.getByText("90 ms")).toBeTruthy();
    expect(screen.getByText("20 ms")).toBeTruthy();
  });

  it("ends on the real report, with the honesty line naming the day", async () => {
    runDemoMock.mockResolvedValue(DEMO);
    render(<EvaluateForm tracing={false} />);

    // The pacing is clamped, so the report arrives in test time. The vote
    // list is the report's own element — the replay line alone also shows
    // during playback, so the report marker is what is waited on.
    expect(
      await screen.findByText(/in their own words/i, undefined, {
        timeout: 8000,
      }),
    ).toBeTruthy();
    expect(screen.getByText(/replayed/)).toBeTruthy();
    expect(screen.getByText(/2026-09-01/)).toBeTruthy();
  });

  it("locks the analyst with a line saying why, and asks it nothing", async () => {
    runDemoMock.mockResolvedValue(DEMO);
    render(<EvaluateForm tracing={false} />);

    await screen.findByText(/in their own words/i, undefined, {
      timeout: 8000,
    });
    expect(screen.queryByText(/ask the analyst/i)).toBeNull();
    expect(screen.getByText(/signed-in account/)).toBeTruthy();
    expect(streamChatMock).not.toHaveBeenCalled();
  });

  it("says when a demo is not seeded, instead of an empty page", async () => {
    runDemoMock.mockRejectedValue(new Error("this demo is not ready yet"));
    render(<EvaluateForm tracing={false} />);

    expect(await screen.findByText(/not ready yet/i)).toBeTruthy();
  });

  it("a demo address wins over a stale open param — no authenticated fetch", async () => {
    // No rail link mints both; a hand-edited URL must not fire myTest under
    // a demo render whose failure would land in invisible state.
    runDemoMock.mockResolvedValue(DEMO);
    search = new URLSearchParams("demo=free-delivery&open=t-stale");
    render(<EvaluateForm tracing={false} />);

    expect(await screen.findByText(/panel assembled/i)).toBeTruthy();
    expect(myTestMock).not.toHaveBeenCalled();
  });
});
