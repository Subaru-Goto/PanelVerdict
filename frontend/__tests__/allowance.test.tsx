import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Allowance from "../app/components/allowance";

// The reader's own remaining runs, beside the button that spends one (the
// prototype's seat for it). These behaviours moved here from the header's
// sign-in control and must survive the move.

const { remainingRunsMock, onRunsChangedMock } = vi.hoisted(() => ({
  remainingRunsMock: vi.fn(),
  onRunsChangedMock: vi.fn(),
}));

vi.mock("../app/lib/api", () => ({
  remainingRuns: remainingRunsMock,
  onRunsChanged: onRunsChangedMock,
}));

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

async function renderSettled() {
  onRunsChangedMock.mockImplementation(() => () => {});
  await act(async () => {
    render(<Allowance />);
  });
}

describe("the allowance", () => {
  it("tells a signed-in reader how many runs they have left today", async () => {
    // Their own count, never the shared pool's — that one is withheld on
    // purpose so nobody gets a progress bar for draining it.
    remainingRunsMock.mockResolvedValue(2);

    await renderSettled();

    expect(screen.getByText("2 runs left today")).toBeTruthy();
  });

  it("says it plainly when the day is spent", async () => {
    remainingRunsMock.mockResolvedValue(0);

    await renderSettled();

    expect(screen.getByText("No runs left today")).toBeTruthy();
  });

  it("re-reads the count after a run spends one", async () => {
    // The figure is a budget, so a stale one is a wrong one: it would still
    // read "3 runs left" immediately after the run that made it 2.
    remainingRunsMock.mockResolvedValue(3);
    let notify = () => {};
    onRunsChangedMock.mockImplementation((listener: () => void) => {
      notify = listener;
      return () => {};
    });
    await act(async () => {
      render(<Allowance />);
    });

    remainingRunsMock.mockResolvedValue(2);
    await act(async () => {
      notify();
    });

    expect(screen.getByText("2 runs left today")).toBeTruthy();
  });

  it("says nothing when the count cannot be read", async () => {
    // A failed read is not a zero: claiming "0 runs left" would tell someone
    // they are out when they are not.
    remainingRunsMock.mockResolvedValue(null);

    await renderSettled();

    expect(screen.queryByText(/runs left/i)).toBeNull();
  });
});
