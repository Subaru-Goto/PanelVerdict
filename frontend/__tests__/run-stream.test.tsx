import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RunStream from "../app/components/run-stream";

// 021/#126: the waiting screen for a paid run. The vote line's number is
// polled off the vote ledger — rows the pipeline was already writing — so the
// count is a fact, never an animation.

const { progressMock } = vi.hoisted(() => ({ progressMock: vi.fn() }));

vi.mock("../app/lib/api", () => ({ runProgress: progressMock }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("the waiting screen", () => {
  it("shows the run's three steps and the size the gate approved", async () => {
    progressMock.mockResolvedValue({ votes_recorded: 0 });
    render(<RunStream threadId="t-1" size={200} />);
    await act(async () => {});

    expect(screen.getByText(/panel assembled/i)).toBeTruthy();
    expect(screen.getByText(/votes returning/i)).toBeTruthy();
    expect(screen.getByText(/verdict computed/i)).toBeTruthy();
    expect(screen.getByText("200 readers")).toBeTruthy();
    expect(screen.getByText("200 readers, one line each.")).toBeTruthy();
    // The early-stop framing is the ticket's carried constraint: a count
    // that halts short of the size must read as an answer, and the screen
    // says so before it happens.
    expect(
      screen.getByText(/usually takes under a minute — and stops early once/i),
    ).toBeTruthy();
  });

  it("prints the polled count against the panel size", async () => {
    progressMock.mockResolvedValue({ votes_recorded: 87 });
    render(<RunStream threadId="t-1" size={200} />);

    expect(await screen.findByText("87 of 200")).toBeTruthy();
    expect(progressMock).toHaveBeenCalledWith("t-1");
  });

  it("keeps asking on the interval", async () => {
    vi.useFakeTimers();
    progressMock.mockResolvedValue({ votes_recorded: 25 });
    render(<RunStream threadId="t-1" size={200} />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6500);
    });

    expect(progressMock.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("a failed poll keeps the last count instead of breaking the wait", async () => {
    vi.useFakeTimers();
    progressMock
      .mockResolvedValueOnce({ votes_recorded: 25 })
      .mockRejectedValue(new Error("proxy hiccup"));
    render(<RunStream threadId="t-1" size={200} />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6500);
    });

    expect(screen.getByText("25 of 200")).toBeTruthy();
  });
});
