import {
  act,
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
  myTests: (cursor?: string) => myTestsMock(cursor),
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
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });

    render(<PastTests onOpen={() => {}} />);

    // Not an empty rail and not a prompt: the tests are the account's, so a box
    // for a visitor without one could only explain itself.
    expect(screen.queryByLabelText("Your tests")).toBeNull();
    expect(myTestsMock).not.toHaveBeenCalled();
  });

  it("shows both headlines and a phrase the report would agree with", async () => {
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });

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
    myTestsMock.mockResolvedValue({
      tests: [stored({ verdict: tied.verdict, tally: tied.tally })],
      next_cursor: null,
    });

    render(<PastTests onOpen={() => {}} />);

    expect(await screen.findByText("too close to call")).toBeTruthy();
  });

  it("hands the whole stored report up when a row is opened", async () => {
    const report = makeResponse();
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });
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
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });
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
    myTestsMock.mockResolvedValue({
      tests: [
        stored(),
        stored({
          test_id: "t-2",
          variants: { a: "Book in 30 seconds", b: "Reserve your slot now" },
        }),
      ],
      next_cursor: null,
    });

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

describe("the rail reads in pages", () => {
  it("asks for one page, and offers the rest only while there is more", async () => {
    myTestsMock.mockResolvedValueOnce({ tests: [stored()], next_cursor: "c1" });
    myTestsMock.mockResolvedValueOnce({
      tests: [
        stored({
          test_id: "t-2",
          variants: { a: "Book in 30 seconds", b: "Reserve your slot now" },
        }),
      ],
      next_cursor: null,
    });

    render(<PastTests onOpen={() => {}} />);
    await screen.findByText(/“Save 50% today”/);

    // The first read named no cursor: it is the newest page, not a resumption.
    expect(myTestsMock).toHaveBeenCalledWith(undefined);
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));

    // The older rows join the newer ones — the reader is scrolling down their
    // history, not turning a page that replaces it.
    expect(await screen.findByText(/“Book in 30 seconds”/)).toBeTruthy();
    expect(screen.getByText(/“Save 50% today”/)).toBeTruthy();
    expect(myTestsMock).toHaveBeenLastCalledWith("c1");
    // The server said that was everything, so nothing offers a fetch that
    // would come back empty.
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("never offers more when the first page is everything", async () => {
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });

    render(<PastTests onOpen={() => {}} />);
    await screen.findByText(/“Save 50% today”/);

    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("does not claim nothing matches while unsearched pages remain", async () => {
    // The search reads the rows on hand, and older pages may hold the match —
    // saying "no test matches" while a Show more could still find one would be
    // a false sentence about the reader's own history.
    myTestsMock.mockResolvedValueOnce({ tests: [stored()], next_cursor: "c1" });

    render(<PastTests onOpen={() => {}} />);
    await screen.findByText(/“Save 50% today”/);
    fireEvent.change(screen.getByLabelText("Search your tests"), {
      target: { value: "zzz" },
    });

    expect(screen.getByText(/No test loaded so far matches/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Show more" })).toBeTruthy();
  });

  it("stops saying the rail failed once Show more succeeds", async () => {
    // `load` clears the banner on success for exactly this reason (117/#252,
    // review); the second reader must not drift from the first.
    myTestsMock.mockResolvedValueOnce({ tests: [stored()], next_cursor: "c1" });
    myTestsMock.mockRejectedValueOnce(new Error("offline"));
    myTestsMock.mockResolvedValueOnce({
      tests: [
        stored({
          test_id: "t-2",
          variants: { a: "Book in 30 seconds", b: "Reserve your slot now" },
        }),
      ],
      next_cursor: null,
    });

    render(<PastTests onOpen={() => {}} />);
    await screen.findByText(/“Save 50% today”/);
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    await screen.findByText(/not lost/);

    fireEvent.click(screen.getByRole("button", { name: "Show more" }));

    expect(await screen.findByText(/“Book in 30 seconds”/)).toBeTruthy();
    expect(screen.queryByText(/not lost/)).toBeNull();
  });

  it("a second click while the page is away buys nothing", async () => {
    // Show more appends, so a double-click that fetched twice would show the
    // same rows twice. The button goes quiet until the page lands.
    myTestsMock.mockResolvedValueOnce({ tests: [stored()], next_cursor: "c1" });
    render(<PastTests onOpen={() => {}} />);
    await screen.findByText(/“Save 50% today”/);

    myTestsMock.mockReturnValue(new Promise(() => {}));
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));

    // One for the first page, one for the click — and nothing for the second.
    expect(myTestsMock.mock.calls.length).toBe(2);
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
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });

    render(<PastTests onOpen={() => {}} />);
    await screen.findByText(/“Save 50% today”/);

    myTestsMock.mockResolvedValue({ tests: [], next_cursor: null });
    announce(false);
    announce(true);

    await waitFor(() =>
      expect(screen.queryByText(/“Save 50% today”/)).toBeNull(),
    );
  });

  it("never lands an old account's page in the new account's rail", async () => {
    // Show more is an append, so a page fetched under the previous session
    // must die with it — the clearing in the listener protects `load`, and
    // this is the same guarantee for the slower, resumable read (117/#252
    // taught the class of bug; 118/#253 adds the second member).
    let announce: (value: boolean) => void = () => {};
    listeners.push((listener) => {
      announce = listener;
    });
    myTestsMock.mockResolvedValueOnce({ tests: [stored()], next_cursor: "c1" });
    render(<PastTests onOpen={() => {}} />);
    await screen.findByText(/“Save 50% today”/);

    let settle: (page: unknown) => void = () => {};
    myTestsMock.mockReturnValueOnce(
      new Promise((resolve) => {
        settle = resolve;
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));

    myTestsMock.mockResolvedValue({
      tests: [
        stored({
          test_id: "t-new",
          variants: { a: "The new account's", b: "own row" },
        }),
      ],
      next_cursor: null,
    });
    announce(false);
    announce(true);
    await screen.findByText(/“The new account's”/);

    // Settled inside act, so the append (if the component wrongly performs
    // one) has flushed before the assertion looks — a waitFor here would pass
    // in the gap before the stale page landed.
    await act(async () => {
      settle({
        tests: [
          stored({
            test_id: "t-old",
            variants: { a: "The old account's", b: "stale page" },
          }),
        ],
        next_cursor: null,
      });
    });

    expect(screen.queryByText(/“The old account's”/)).toBeNull();
    expect(screen.getByText(/“The new account's”/)).toBeTruthy();
  });

  it("stops saying the rail failed once it loads", async () => {
    // A cold backend fails the first load; the run that follows fires
    // `onRunsChanged` and the rows arrive. The warning must not still be
    // standing above them.
    myTestsMock.mockRejectedValueOnce(new Error("offline"));
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });
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
