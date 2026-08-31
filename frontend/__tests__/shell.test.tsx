import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeStoredTest } from "./fixtures";

// 119/#257. The frame every page sits in: a header carrying identity and
// account (no tabs — the product has one function), and the rail. Signed out
// the rail is a demo shelf: samples only, static until #156 makes them run.
// Signed in it is yours: new test + your saved tests, samples gone.

const myTestsMock = vi.fn();
let signedIn: boolean | null = false;

vi.mock("../app/lib/api", () => ({
  myTests: (cursor?: string) => myTestsMock(cursor),
  myTest: vi.fn(),
  forgetTest: vi.fn(),
  onRunsChanged: () => () => {},
  remainingRuns: () => Promise.resolve(3),
}));

vi.mock("../app/lib/auth", () => ({
  onAuthChange: (listener: (value: boolean) => void) => {
    if (signedIn !== null) listener(signedIn);
    return () => {};
  },
  signInAvailable: () => true,
  mountGoogleButton: vi.fn().mockResolvedValue(undefined),
  signOut: vi.fn(),
}));

const { default: Shell, useGateSignal } =
  await import("../app/components/shell");

/** Stands in for the wizard: signals the gate the way the real page does. */
function AtTheGate({ open }: { open: boolean }) {
  useGateSignal(open);
  return <>content</>;
}

afterEach(() => {
  cleanup();
  myTestsMock.mockReset();
  signedIn = false;
});

function page() {
  return { tests: [makeStoredTest()], next_cursor: null };
}

describe("the shell", () => {
  it("frames the page: wordmark home link, and the demo shelf signed out", () => {
    render(<Shell>content</Shell>);

    expect(
      screen.getByRole("link", { name: "Panelverdict" }).getAttribute("href"),
    ).toBe("/");
    expect(screen.getByText("Sample verdicts")).toBeDefined();
    expect(
      screen.getByText(
        "“Save 50% this week” vs “Members save half price this week”",
      ),
    ).toBeDefined();
    expect(screen.queryByRole("link", { name: "New test" })).toBeNull();
    expect(screen.getByText("content")).toBeDefined();
  });

  it("signed in, the rail is yours: new test and saved tests, samples gone", async () => {
    signedIn = true;
    myTestsMock.mockResolvedValue(page());
    render(<Shell>content</Shell>);

    expect(
      screen.getByRole("link", { name: "New test" }).getAttribute("href"),
    ).toBe("/test");
    await waitFor(() =>
      expect(screen.getByText(/Save 50% today/)).toBeDefined(),
    );
    expect(screen.queryByText("Sample verdicts")).toBeNull();
  });

  it("the toggle puts the rail away and brings it back", () => {
    render(<Shell>content</Shell>);

    const toggle = screen.getByRole("button", {
      name: "Show or hide the rail",
    });
    expect(screen.getByRole("complementary")).toBeDefined();
    fireEvent.click(toggle);
    expect(screen.queryByRole("complementary")).toBeNull();
    fireEvent.click(toggle);
    expect(screen.getByRole("complementary")).toBeDefined();
  });

  it("holding at the gate puts the rail away without costing a refetch", async () => {
    // The gate is a decision about spending money; a list of other tests
    // beside it is an invitation to leave it half-answered (#252). Withheld
    // from the eye, not unmounted: unmounting would forget the loaded pages
    // and refetch them on the way back (118/#253).
    signedIn = true;
    myTestsMock.mockResolvedValue(page());
    const { rerender } = render(
      <Shell>
        <AtTheGate open={false} />
      </Shell>,
    );
    await waitFor(() => expect(myTestsMock).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("complementary")).toBeDefined();

    rerender(
      <Shell>
        <AtTheGate open />
      </Shell>,
    );
    expect(screen.queryByRole("complementary")).toBeNull();

    rerender(
      <Shell>
        <AtTheGate open={false} />
      </Shell>,
    );
    expect(screen.getByRole("complementary")).toBeDefined();
    expect(myTestsMock).toHaveBeenCalledTimes(1);
  });
});
