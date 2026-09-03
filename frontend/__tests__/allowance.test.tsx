import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Allowance from "../app/components/allowance";

// The reader's own remaining runs, beside the button that spends one (the
// prototype's seat for it). These behaviours moved here from the header's
// sign-in control and must survive the move.

const { accountFiguresMock, onAccountChangedMock } = vi.hoisted(() => ({
  accountFiguresMock: vi.fn(),
  onAccountChangedMock: vi.fn(),
}));

vi.mock("../app/lib/api", () => ({
  accountFigures: accountFiguresMock,
  onAccountChanged: onAccountChangedMock,
}));

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

/** /me's answer: the runs left, and a rail with room unless said. */
function figures(
  runsLeft: number,
  rail: { saved: number; cap: number } = { saved: 0, cap: 10 },
) {
  return {
    runs_remaining: runsLeft,
    saved_tests: rail.saved,
    saved_tests_cap: rail.cap,
  };
}

async function renderSettled() {
  onAccountChangedMock.mockImplementation(() => () => {});
  await act(async () => {
    render(<Allowance />);
  });
}

describe("the allowance", () => {
  it("tells a signed-in reader how many runs they have left today", async () => {
    // Their own count, never the shared pool's — that one is withheld on
    // purpose so nobody gets a progress bar for draining it.
    accountFiguresMock.mockResolvedValue(figures(2));

    await renderSettled();

    expect(screen.getByText("2 runs left today")).toBeTruthy();
  });

  it("says it plainly when the day is spent", async () => {
    accountFiguresMock.mockResolvedValue(figures(0));

    await renderSettled();

    expect(screen.getByText("No runs left today")).toBeTruthy();
  });

  it("re-reads the count after a run spends one", async () => {
    // The figure is a budget, so a stale one is a wrong one: it would still
    // read "3 runs left" immediately after the run that made it 2.
    accountFiguresMock.mockResolvedValue(figures(3));
    let notify = () => {};
    onAccountChangedMock.mockImplementation((listener: () => void) => {
      notify = listener;
      return () => {};
    });
    await act(async () => {
      render(<Allowance />);
    });

    accountFiguresMock.mockResolvedValue(figures(2));
    await act(async () => {
      notify();
    });

    expect(screen.getByText("2 runs left today")).toBeTruthy();
  });

  it("warns before the run that a full rail will not keep this test", async () => {
    // The save cap refuses after the run is paid for (085/#176); the reader
    // should hear it while the run can still be skipped (124/#291). Same
    // sentence shape as the post-run warning: the limit, never the count.
    accountFiguresMock.mockResolvedValue(figures(3, { saved: 10, cap: 10 }));

    await renderSettled();

    expect(
      screen.getByText(
        "Your rail is full: an account keeps at most 10 saved tests, so this test will not be saved. Delete a saved test to make room.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("3 runs left today")).toBeTruthy();
  });

  it("says nothing about the rail while there is room", async () => {
    accountFiguresMock.mockResolvedValue(figures(3, { saved: 9, cap: 10 }));

    await renderSettled();

    expect(screen.queryByText(/rail is full/i)).toBeNull();
  });

  it("offers no remedy when the deployment keeps nothing", async () => {
    // A cap of zero means every test goes unkept; deleting makes no room.
    accountFiguresMock.mockResolvedValue(figures(3, { saved: 0, cap: 0 }));

    await renderSettled();

    expect(screen.getByText(/rail is full/i).textContent).toBe(
      "Your rail is full: an account keeps at most 0 saved tests, so this test will not be saved.",
    );
  });

  it("says nothing when the count cannot be read", async () => {
    // A failed read is not a zero: claiming "0 runs left" would tell someone
    // they are out when they are not.
    accountFiguresMock.mockResolvedValue(null);

    await renderSettled();

    expect(screen.queryByText(/runs left/i)).toBeNull();
  });
});
