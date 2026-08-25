import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SignIn from "../app/components/sign-in";

// 063/#158 + 092/#197. The smallest control that makes signing in reachable —
// the redesign (093/#198) owns where it eventually sits. What is asserted here
// is behaviour that must survive that move: a build with no auth configured
// looks exactly as it did before, and a signed-in reader can see their own
// remaining runs.

const {
  mountButtonMock,
  signOutMock,
  availableMock,
  onAuthChangeMock,
  remainingRunsMock,
  onRunsChangedMock,
} = vi.hoisted(() => ({
  mountButtonMock: vi.fn(),
  signOutMock: vi.fn(),
  availableMock: vi.fn(),
  onAuthChangeMock: vi.fn(),
  remainingRunsMock: vi.fn(),
  onRunsChangedMock: vi.fn(),
}));

vi.mock("../app/lib/auth", () => ({
  mountGoogleButton: mountButtonMock,
  signOut: signOutMock,
  signInAvailable: availableMock,
  onAuthChange: onAuthChangeMock,
}));

vi.mock("../app/lib/api", () => ({
  remainingRuns: remainingRunsMock,
  onRunsChanged: onRunsChangedMock,
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

/** Drives the auth subscription the component registers. */
function withSession(signedIn: boolean) {
  availableMock.mockReturnValue(true);
  mountButtonMock.mockResolvedValue(undefined);
  onAuthChangeMock.mockImplementation((listener: (v: boolean) => void) => {
    listener(signedIn);
    return () => {};
  });
  onRunsChangedMock.mockImplementation(() => () => {});
}

function stubRuns(remaining: number | null) {
  // null is what the API layer reports when the count could not be read.
  remainingRunsMock.mockResolvedValue(remaining);
}

async function renderSettled() {
  // The component reads /api/me on mount; flush that before asserting.
  await act(async () => {
    render(<SignIn />);
  });
}

describe("the sign-in control", () => {
  it("stays out of the way entirely when this build has no sign-in", async () => {
    // Local development and CI run with no Supabase project. Offering a button
    // that cannot work would be worse than offering nothing.
    availableMock.mockReturnValue(false);
    onAuthChangeMock.mockReturnValue(() => {});
    onRunsChangedMock.mockReturnValue(() => {});
    stubRuns(3);

    let container!: HTMLElement;
    await act(async () => {
      ({ container } = render(<SignIn />));
    });

    expect(container.innerHTML).toBe("");
  });

  it("hands Google a place to render its own button", async () => {
    // Google's pre-built button, not our own calling `prompt()`: FedCM puts
    // One Tap into a cooldown after a dismissal, so a button of ours would
    // silently do nothing for a visitor who once closed the prompt — the worst
    // kind of broken, since it looks fine.
    withSession(false);
    stubRuns(3);

    await renderSettled();

    expect(mountButtonMock).toHaveBeenCalledWith(expect.any(HTMLElement));
  });

  it("does not offer to sign in someone who already is", async () => {
    withSession(true);
    stubRuns(3);

    await renderSettled();

    expect(mountButtonMock).not.toHaveBeenCalled();
  });

  it("does not ask the backend who it is before anyone signs in", async () => {
    // A signed-out visitor has nothing to count, and the call would only ever
    // come back 401.
    withSession(false);
    stubRuns(3);

    await renderSettled();

    expect(remainingRunsMock).not.toHaveBeenCalled();
  });

  it("tells a signed-in reader how many runs they have left today", async () => {
    // Their own count, never the shared pool's — that one is withheld on
    // purpose so nobody gets a progress bar for draining it.
    withSession(true);
    stubRuns(2);

    await renderSettled();

    expect(screen.getByText(/2 runs left today/i)).toBeTruthy();
  });

  it("lets a signed-in reader sign out again", async () => {
    withSession(true);
    stubRuns(3);

    await renderSettled();
    fireEvent.click(screen.getByRole("button", { name: /sign out/i }));

    expect(signOutMock).toHaveBeenCalled();
  });

  it("re-reads the count after a run spends one", async () => {
    // The figure is a budget, so a stale one is a wrong one: it would still
    // read "3 runs left" immediately after the run that made it 2.
    withSession(true);
    stubRuns(3);
    let notify = () => {};
    onRunsChangedMock.mockImplementation((listener: () => void) => {
      notify = listener;
      return () => {};
    });

    await renderSettled();
    stubRuns(2);
    await act(async () => {
      notify();
    });

    expect(screen.getByText(/2 runs left today/i)).toBeTruthy();
  });

  it("says nothing about runs when the count cannot be read", async () => {
    // A failed read is not a zero: claiming "0 runs left" would tell someone
    // they are out when they are not.
    withSession(true);
    stubRuns(null);

    await renderSettled();

    expect(screen.queryByText(/runs left/i)).toBeNull();
  });
});
