import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SignIn from "../app/components/sign-in";

// 063/#158 + 092/#197. The smallest control that makes signing in reachable —
// the redesign (093/#198) owns where it eventually sits. What is asserted here
// is behaviour that must survive that move: a build with no auth configured
// looks exactly as it did before, and a signed-in reader can see their own
// remaining runs.

const {
  signInMock,
  signOutMock,
  availableMock,
  onAuthChangeMock,
  remainingRunsMock,
} = vi.hoisted(() => ({
  signInMock: vi.fn(),
  signOutMock: vi.fn(),
  availableMock: vi.fn(),
  onAuthChangeMock: vi.fn(),
  remainingRunsMock: vi.fn(),
}));

vi.mock("../app/lib/auth", () => ({
  signIn: signInMock,
  signOut: signOutMock,
  signInAvailable: availableMock,
  onAuthChange: onAuthChangeMock,
}));

vi.mock("../app/lib/api", () => ({ remainingRuns: remainingRunsMock }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

/** Drives the auth subscription the component registers. */
function withSession(signedIn: boolean) {
  availableMock.mockReturnValue(true);
  onAuthChangeMock.mockImplementation((listener: (v: boolean) => void) => {
    listener(signedIn);
    return () => {};
  });
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
    stubRuns(3);

    let container!: HTMLElement;
    await act(async () => {
      ({ container } = render(<SignIn />));
    });

    expect(container.innerHTML).toBe("");
  });

  it("offers Google to a visitor who is not signed in", async () => {
    withSession(false);
    stubRuns(3);

    await renderSettled();
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(signInMock).toHaveBeenCalled();
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

  it("says nothing about runs when the count cannot be read", async () => {
    // A failed read is not a zero: claiming "0 runs left" would tell someone
    // they are out when they are not.
    withSession(true);
    stubRuns(null);

    await renderSettled();

    expect(screen.queryByText(/runs left/i)).toBeNull();
  });
});
