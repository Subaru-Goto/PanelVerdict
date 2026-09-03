import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// 119/#257: "the form itself is behind Google" (prototype, 2026-08-25). The
// backend already refuses unsigned runs; this makes the page say so before a
// visitor fills in a form that cannot be submitted.

let signedIn: boolean | null = null;
let available = true;

vi.mock("../app/lib/api", () => ({
  accountFigures: () =>
    Promise.resolve({ runs_remaining: 3, saved_tests: 0, saved_tests_cap: 10 }),
  onAccountChanged: () => () => {},
  evaluate: () => Promise.reject(new Error("not used")),
  resumeEvaluate: () => Promise.reject(new Error("not used")),
  myTest: () => Promise.reject(new Error("not used")),
  LOCALES: ["US", "JP", "DE"],
  MIN_PANEL_AGE: 18,
  MAX_PANEL_AGE: 100,
}));

vi.mock("../app/lib/auth", () => ({
  displayName: () => Promise.resolve("Sam O."),
  onAuthChange: (listener: (value: boolean) => void) => {
    if (signedIn !== null) listener(signedIn);
    return () => {};
  },
  signInAvailable: () => available,
  mountGoogleButton: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: () => {}, push: () => {} }),
}));

const { default: EvaluateForm } =
  await import("../app/components/evaluate-form");

afterEach(() => {
  cleanup();
  signedIn = null;
  available = true;
});

describe("the wizard behind Google", () => {
  it("offers sign-in instead of the form to a signed-out visitor", () => {
    signedIn = false;
    render(<EvaluateForm tracing={false} />);

    expect(screen.queryByLabelText(/headline a/i)).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Sign in to run a test" }),
    );
    expect(screen.getByRole("dialog", { name: "Sign in" })).toBeDefined();
  });

  it("shows the form once signed in", () => {
    signedIn = true;
    render(<EvaluateForm tracing={false} />);
    expect(screen.getByLabelText(/headline a/i)).toBeDefined();
  });

  it("keeps the form in a build with no sign-in at all", () => {
    // Local development and CI have no identity provider; a wall that nothing
    // can open would make the app undevelopable (the sign-in control's rule).
    signedIn = false;
    available = false;
    render(<EvaluateForm tracing={false} />);
    expect(screen.getByLabelText(/headline a/i)).toBeDefined();
  });

  it("shows nothing form-shaped before the session is known", () => {
    signedIn = null;
    render(<EvaluateForm tracing={false} />);
    expect(screen.queryByLabelText(/headline a/i)).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Sign in to run a test" }),
    ).toBeNull();
  });
});
