import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
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
  displayNameMock,
} = vi.hoisted(() => ({
  mountButtonMock: vi.fn(),
  signOutMock: vi.fn(),
  availableMock: vi.fn(),
  onAuthChangeMock: vi.fn(),
  remainingRunsMock: vi.fn(),
  onRunsChangedMock: vi.fn(),
  displayNameMock: vi.fn(),
}));

vi.mock("../app/lib/auth", () => ({
  mountGoogleButton: mountButtonMock,
  signOut: signOutMock,
  signInAvailable: availableMock,
  onAuthChange: onAuthChangeMock,
  displayName: displayNameMock,
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

function stubName(name: string | null) {
  displayNameMock.mockResolvedValue(name);
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
    stubName("Sam O.");

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

  it("shows no half-dressed pill while the name is still being read", async () => {
    // A pill with a blank disc reads as broken, not loading — nothing, until
    // the name is known. (A session with no readable name is displayName's
    // case, and it answers with a plain label rather than null.)
    withSession(true);
    displayNameMock.mockReturnValue(new Promise(() => {}));

    await renderSettled();

    expect(screen.queryByRole("button")).toBeNull();
  });

  it("wears the reader's name and initials, the prototype's who pill", async () => {
    withSession(true);
    stubName("Sam O.");

    await renderSettled();

    expect(screen.getByText("Sam O.")).toBeTruthy();
    expect(screen.getByText("SO")).toBeTruthy();
  });

  it("an accidental click on the pill signs nobody out — it opens a menu", async () => {
    withSession(true);
    stubName("Sam O.");

    await renderSettled();
    fireEvent.click(screen.getByRole("button", { name: /account/i }));

    expect(signOutMock).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeTruthy();
  });

  it("lets a signed-in reader sign out — the menu's one item", async () => {
    withSession(true);
    stubName("Sam O.");

    await renderSettled();
    fireEvent.click(screen.getByRole("button", { name: /account/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: /sign out/i }));

    expect(signOutMock).toHaveBeenCalled();
  });

  it("a second click on the pill just closes the menu again", async () => {
    withSession(true);
    stubName("Sam O.");

    await renderSettled();
    fireEvent.click(screen.getByRole("button", { name: /account/i }));
    fireEvent.click(screen.getByRole("button", { name: /account/i }));

    expect(screen.queryByRole("menu")).toBeNull();
    expect(signOutMock).not.toHaveBeenCalled();
  });

  it("keeps the pill up until the sign-out actually lands", async () => {
    // Clearing the header at the click would leave no pill, no button and no
    // feedback for the whole server round-trip; the pill stays until the
    // session event flips the state, and the name is cleared on the way out
    // so it cannot flash into the next session.
    let announce: (value: boolean) => void = () => {};
    availableMock.mockReturnValue(true);
    mountButtonMock.mockResolvedValue(undefined);
    onAuthChangeMock.mockImplementation((listener: (v: boolean) => void) => {
      announce = listener;
      listener(true);
      return () => {};
    });
    stubName("Sam O.");
    signOutMock.mockReturnValue(new Promise(() => {}));

    await renderSettled();
    fireEvent.click(screen.getByRole("button", { name: /account/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: /sign out/i }));
    expect(screen.getByText("Sam O.")).toBeTruthy();

    await act(async () => {
      announce(false);
    });
    expect(screen.queryByText("Sam O.")).toBeNull();
  });

  it("says nothing about runs — the allowance lives beside the run button", async () => {
    // Moved to the actions row (Allowance), where spending happens.
    withSession(true);
    stubName("Sam O.");

    await renderSettled();

    expect(screen.queryByText(/runs left/i)).toBeNull();
    expect(remainingRunsMock).not.toHaveBeenCalled();
  });
});
