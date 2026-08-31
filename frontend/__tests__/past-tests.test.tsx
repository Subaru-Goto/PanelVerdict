import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeResponse, makeTiedResponse } from "./fixtures";

const myTestsMock = vi.fn();
const myTestMock = vi.fn();
const forgetTestMock = vi.fn();
let signedIn = true;

vi.mock("../app/lib/api", () => ({
  myTests: () => myTestsMock(),
  myTest: (id: string) => myTestMock(id),
  forgetTest: (id: string) => forgetTestMock(id),
  onRunsChanged: () => () => {},
}));

// A test that changes session mid-render needs the listener, not just its
// first value — `onAuthChange` is live, so this is how the component learns.
const listeners: ((listener: (value: boolean) => void) => void)[] = [];

vi.mock("../app/lib/auth", () => ({
  onAuthChange: (listener: (value: boolean) => void) => {
    listener(signedIn);
    listeners.forEach((take) => take(listener));
    return () => {};
  },
}));

const { default: PastTests } = await import("../app/components/past-tests");

function stored(over: Partial<Record<string, unknown>> = {}) {
  const response = makeResponse();
  return {
    test_id: "t-1",
    created_at: "2026-08-31T10:00:00Z",
    variants: { a: "Save 50% today", b: "Members save half" },
    verdict: response.verdict,
    tally: response.tally,
    ...over,
  };
}

afterEach(() => {
  cleanup();
  myTestsMock.mockReset();
  myTestMock.mockReset();
  forgetTestMock.mockReset();
  signedIn = true;
  listeners.length = 0;
});

describe("the account's own tests", () => {
  it("renders nothing at all when nobody is signed in", async () => {
    signedIn = false;
    myTestsMock.mockResolvedValue([stored()]);

    render(<PastTests onOpen={() => {}} />);

    // Not an empty rail and not a prompt: the tests are the account's, so a box
    // for a visitor without one could only explain itself.
    expect(screen.queryByLabelText("Your tests")).toBeNull();
    expect(myTestsMock).not.toHaveBeenCalled();
  });

  it("shows both headlines and a phrase the report would agree with", async () => {
    myTestsMock.mockResolvedValue([stored()]);

    render(<PastTests onOpen={() => {}} />);

    expect(
      await screen.findByText(/“Save 50% today” vs “Members save half”/),
    ).toBeTruthy();
    // 0.288 prefer B in the fixture, so the phrase names A's share — the rail
    // must never report the loser's figure.
    expect(screen.getByText("71% preferred the first")).toBeTruthy();
  });

  it("says a tie is a tie rather than inventing a winner", async () => {
    const tied = makeTiedResponse();
    myTestsMock.mockResolvedValue([
      stored({ verdict: tied.verdict, tally: tied.tally }),
    ]);

    render(<PastTests onOpen={() => {}} />);

    expect(await screen.findByText("too close to call")).toBeTruthy();
  });

  it("hands the whole stored report up when a row is opened", async () => {
    const report = makeResponse();
    myTestsMock.mockResolvedValue([stored()]);
    myTestMock.mockResolvedValue(report);
    const onOpen = vi.fn();

    render(<PastTests onOpen={onOpen} />);
    fireEvent.click(
      await screen.findByText(/“Save 50% today” vs “Members save half”/),
    );

    // The report itself, not a summary: this is the read that gets a paid
    // report back after the page drawing it crashed (049/#147).
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(report));
    expect(myTestMock).toHaveBeenCalledWith("t-1");
  });

  it("drops a deleted row before the round trip settles", async () => {
    myTestsMock.mockResolvedValue([stored()]);
    let settle: () => void = () => {};
    forgetTestMock.mockReturnValue(
      new Promise<void>((resolve) => {
        settle = resolve;
      }),
    );

    render(<PastTests onOpen={() => {}} />);
    fireEvent.click(
      await screen.findByLabelText("Delete the test of “Save 50% today”"),
    );

    // Gone from the rail while the delete is still in flight: the call is
    // idempotent and a 404 is not an error, so the row never needs to return,
    // and a rail that waits feels broken on a slow connection.
    await waitFor(() =>
      expect(screen.queryByText(/“Save 50% today”/)).toBeNull(),
    );
    settle();
  });

  it("searches the headlines it shows, and says when nothing matches", async () => {
    myTestsMock.mockResolvedValue([
      stored(),
      stored({
        test_id: "t-2",
        variants: { a: "Book in 30 seconds", b: "Reserve your slot now" },
      }),
    ]);

    render(<PastTests onOpen={() => {}} />);
    await screen.findByText(/“Save 50% today”/);
    fireEvent.change(screen.getByLabelText("Search your tests"), {
      target: { value: "Book" },
    });

    expect(screen.queryByText(/“Save 50% today”/)).toBeNull();
    expect(screen.getByText(/“Book in 30 seconds”/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Search your tests"), {
      target: { value: "zzz" },
    });
    expect(screen.getByText(/No test matches/)).toBeTruthy();
  });

  it("says the tests are not lost when the rail cannot load them", async () => {
    myTestsMock.mockRejectedValue(new Error("offline"));

    render(<PastTests onOpen={() => {}} />);

    // The distinction that matters to someone who paid for those reports: the
    // rail failed, the reports did not.
    expect(await screen.findByText(/not lost/)).toBeTruthy();
  });
});

describe("the rail across a change of session", () => {
  it("clears one account's rows before showing another's", async () => {
    // `onAuthChange` is a live session listener, so this happens without a
    // remount — and the previous account's headlines are not this account's to
    // show, even for the moment before the fetch resolves (117/#252, review).
    let announce: (value: boolean) => void = () => {};
    listeners.push((listener) => {
      announce = listener;
    });
    myTestsMock.mockResolvedValue([stored()]);

    render(<PastTests onOpen={() => {}} />);
    await screen.findByText(/“Save 50% today”/);

    myTestsMock.mockResolvedValue([]);
    announce(false);
    announce(true);

    await waitFor(() =>
      expect(screen.queryByText(/“Save 50% today”/)).toBeNull(),
    );
  });

  it("stops saying the rail failed once it loads", async () => {
    // A cold backend fails the first load; the run that follows fires
    // `onRunsChanged` and the rows arrive. The warning must not still be
    // standing above them.
    myTestsMock.mockRejectedValueOnce(new Error("offline"));
    myTestsMock.mockResolvedValue([stored()]);
    let announce: (value: boolean) => void = () => {};
    listeners.push((listener) => {
      announce = listener;
    });

    render(<PastTests onOpen={() => {}} />);
    await screen.findByText(/not lost/);

    announce(false);
    announce(true);

    expect(await screen.findByText(/“Save 50% today”/)).toBeTruthy();
    expect(screen.queryByText(/not lost/)).toBeNull();
  });
});
