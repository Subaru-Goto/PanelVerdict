import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeStoredTest, makeTiedResponse } from "./fixtures";

const myTestsMock = vi.fn();
const myTestMock = vi.fn();
const forgetTestMock = vi.fn();
let signedIn = true;

const runsListeners: (() => void)[] = [];

vi.mock("../app/lib/api", () => ({
  myTests: (cursor?: string) => myTestsMock(cursor),
  myTest: (id: string) => myTestMock(id),
  forgetTest: (id: string) => forgetTestMock(id),
  onAccountChanged: (listener: () => void) => {
    runsListeners.push(listener);
    return () => {};
  },
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

const stored = makeStoredTest;

afterEach(() => {
  cleanup();
  myTestsMock.mockReset();
  myTestMock.mockReset();
  forgetTestMock.mockReset();
  signedIn = true;
  listeners.length = 0;
  runsListeners.length = 0;
});

describe("the account's own tests", () => {
  it("renders nothing at all when nobody is signed in", async () => {
    signedIn = false;
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });

    render(<PastTests />);

    // Not an empty rail and not a prompt: the tests are the account's, so a box
    // for a visitor without one could only explain itself.
    expect(screen.queryByLabelText("Your tests")).toBeNull();
    expect(myTestsMock).not.toHaveBeenCalled();
  });

  it("shows both headlines and a phrase the report would agree with", async () => {
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });

    render(<PastTests />);

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

    render(<PastTests />);

    expect(await screen.findByText("too close to call")).toBeTruthy();
  });

  it("gives every row the test's own address, fetching nothing", async () => {
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });

    render(<PastTests />);
    const row = (
      await screen.findByText(/“Save 50% today” vs “Members save half”/)
    ).closest("a");

    // A row is a link to the wizard, which fetches the stored report itself
    // (119/#257): one render path for reports, reachable from anywhere the
    // rail shows — including a page that is not the wizard.
    expect(row?.getAttribute("href")).toBe("/test?open=t-1");
    expect(myTestMock).not.toHaveBeenCalled();
  });

  it("drops a deleted row before the round trip settles", async () => {
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });
    let settle: () => void = () => {};
    forgetTestMock.mockReturnValue(
      new Promise<void>((resolve) => {
        settle = resolve;
      }),
    );

    render(<PastTests />);
    fireEvent.click(
      await screen.findByLabelText("Delete the test of “Save 50% today”"),
    );
    fireEvent.click(
      screen.getByLabelText("Really delete the test of “Save 50% today”?"),
    );

    // Gone from the rail while the delete is still in flight: the call is
    // idempotent and a 404 is not an error, so the row never needs to return,
    // and a rail that waits feels broken on a slow connection.
    await waitFor(() =>
      expect(screen.queryByText(/“Save 50% today”/)).toBeNull(),
    );
    settle();
  });

  it("asks before deleting — one click never destroys a paid report", async () => {
    // ChatGPT's and Gemini's rails both put a confirmation between the click
    // and the delete; ours is the inline version (085/#176, decided
    // 2026-09-01). The × becomes the question, on the row, no popup.
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });

    render(<PastTests />);
    fireEvent.click(
      await screen.findByLabelText("Delete the test of “Save 50% today”"),
    );

    expect(forgetTestMock).not.toHaveBeenCalled();
    expect(screen.getByText(/“Save 50% today”/)).toBeDefined();
    expect(screen.getByText("Delete?")).toBeDefined();
  });

  it("keeps the keyboard user's focus on the question it just posed", async () => {
    // React patches the same button node across the ×→Delete? swap, so the
    // focus the × held is the focus the question holds — which is what makes
    // Escape reachable for the user who just armed it (085/#176, review).
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });

    render(<PastTests />);
    const arm = await screen.findByLabelText(
      "Delete the test of “Save 50% today”",
    );
    arm.focus();
    fireEvent.click(arm);

    expect(document.activeElement).toBe(
      screen.getByLabelText("Really delete the test of “Save 50% today”?"),
    );
  });

  it("withdraws the question when focus leaves it", async () => {
    // Tab away and an armed Delete? must not stay standing where a later
    // click, from someone no longer thinking about it, would destroy a row.
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });

    render(<PastTests />);
    fireEvent.click(
      await screen.findByLabelText("Delete the test of “Save 50% today”"),
    );
    fireEvent.blur(
      screen.getByLabelText("Really delete the test of “Save 50% today”?"),
    );

    expect(screen.queryByText("Delete?")).toBeNull();
    expect(forgetTestMock).not.toHaveBeenCalled();
  });

  it("withdraws the question when the pointer leaves the row", async () => {
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });

    render(<PastTests />);
    const arm = await screen.findByLabelText(
      "Delete the test of “Save 50% today”",
    );
    fireEvent.click(arm);
    fireEvent.mouseLeave(arm.closest("li")!);

    // Back to the plain ×: a question left standing after the pointer moved
    // on would make the next visit to the row a one-click delete after all.
    expect(screen.queryByText("Delete?")).toBeNull();
    expect(
      screen.getByLabelText("Delete the test of “Save 50% today”"),
    ).toBeDefined();
    expect(forgetTestMock).not.toHaveBeenCalled();
  });

  it("withdraws the question on Escape", async () => {
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });

    render(<PastTests />);
    fireEvent.click(
      await screen.findByLabelText("Delete the test of “Save 50% today”"),
    );
    fireEvent.keyDown(
      screen.getByLabelText("Really delete the test of “Save 50% today”?"),
      { key: "Escape" },
    );

    expect(screen.queryByText("Delete?")).toBeNull();
    expect(forgetTestMock).not.toHaveBeenCalled();
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

    render(<PastTests />);
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

    render(<PastTests />);

    // The distinction that matters to someone who paid for those reports: the
    // rail failed, the reports did not.
    expect(await screen.findByText(/not lost/)).toBeTruthy();
  });

  it("the banner's Try again retries in place, without a reload", async () => {
    // The likely failure on this deploy is a cold backend (docs/deploy.md:
    // ~1 minute after idle), so the remedy must be one click, not a reload
    // that loses the page.
    myTestsMock.mockRejectedValueOnce(new Error("cold start"));
    render(<PastTests />);
    await screen.findByText(/not lost/);

    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    });

    expect(screen.queryByText(/not lost/)).toBeNull();
    expect(screen.getByText(/Save 50% today/)).toBeTruthy();
  });

  it("Try again goes quiet while its read is away — no stacking clicks", async () => {
    // The button's own target case is a wait of up to a minute; a button that
    // looks untouched after the click gets clicked again, and every extra
    // click held another function open.
    myTestsMock.mockRejectedValueOnce(new Error("cold start"));
    render(<PastTests />);
    await screen.findByText(/not lost/);

    myTestsMock.mockReturnValue(new Promise(() => {}));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    });

    expect(
      (screen.getByRole("button", { name: /try again/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("a late failure from a superseded read cannot resurrect the banner", async () => {
    // Two reads can be away at once (a retry racing the run-finished refresh);
    // only the latest one started may speak, or 'could not be loaded' lands
    // on top of rows that loaded fine.
    let rejectFirst: (error: Error) => void = () => {};
    myTestsMock.mockReturnValueOnce(
      new Promise((_, reject) => {
        rejectFirst = reject;
      }),
    );
    render(<PastTests />);

    // The run-finished refresh supersedes the slow first read and succeeds.
    myTestsMock.mockResolvedValueOnce({ tests: [stored()], next_cursor: null });
    await act(async () => {
      runsListeners.forEach((notify) => notify());
    });
    await screen.findByText(/Save 50% today/);

    await act(async () => {
      rejectFirst(new Error("cold start, finally timing out"));
    });

    expect(screen.queryByText(/not lost/)).toBeNull();
  });

  it("a failed Show more retries the page it was fetching, not the whole list", async () => {
    // The banner is shared, but the remedies differ: replacing the list with
    // page one would throw away every page already reached.
    myTestsMock.mockResolvedValueOnce({
      tests: [stored()],
      next_cursor: "after-t-1",
    });
    render(<PastTests />);
    await screen.findByText(/Save 50% today/);

    myTestsMock.mockRejectedValueOnce(new Error("cold start"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /show more/i }));
    });
    await screen.findByText(/not lost/);

    myTestsMock.mockResolvedValueOnce({
      tests: [
        stored({ test_id: "t-2", variants: { a: "Second page", b: "row" } }),
      ],
      next_cursor: null,
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    });

    // The retry asked for the failed cursor, and both pages are on screen.
    expect(myTestsMock).toHaveBeenLastCalledWith("after-t-1");
    expect(screen.getByText(/Save 50% today/)).toBeTruthy();
    expect(screen.getByText(/Second page/)).toBeTruthy();
  });

  it("a first read landing after the session changed says nothing", async () => {
    // Supabase can collapse a sign-out and sign-in to true→true, so the rail
    // never unmounts; a read started under the old account must not stamp
    // that account's headlines into the new one's rail.
    let resolveOld: (page: unknown) => void = () => {};
    myTestsMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveOld = resolve;
      }),
    );
    let announce: (value: boolean) => void = () => {};
    listeners.push((listener) => {
      announce = listener;
    });
    render(<PastTests />);

    // The session changes; the new account's read finds nothing.
    myTestsMock.mockResolvedValueOnce({ tests: [], next_cursor: null });
    await act(async () => {
      announce(true);
    });
    await screen.findByText(/Nothing yet/);

    await act(async () => {
      resolveOld({
        tests: [stored({ variants: { a: "Not this account's", b: "test" } })],
        next_cursor: null,
      });
    });

    expect(screen.queryByText(/Not this account's/)).toBeNull();
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

    render(<PastTests />);
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

    render(<PastTests />);
    await screen.findByText(/“Save 50% today”/);

    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("does not claim nothing matches while unsearched pages remain", async () => {
    // The search reads the rows on hand, and older pages may hold the match —
    // saying "no test matches" while a Show more could still find one would be
    // a false sentence about the reader's own history.
    myTestsMock.mockResolvedValueOnce({ tests: [stored()], next_cursor: "c1" });

    render(<PastTests />);
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

    render(<PastTests />);
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
    render(<PastTests />);
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

    render(<PastTests />);
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
    render(<PastTests />);
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
    // `onAccountChanged` and the rows arrive. The warning must not still be
    // standing above them.
    myTestsMock.mockRejectedValueOnce(new Error("offline"));
    myTestsMock.mockResolvedValue({ tests: [stored()], next_cursor: null });
    let announce: (value: boolean) => void = () => {};
    listeners.push((listener) => {
      announce = listener;
    });

    render(<PastTests />);
    await screen.findByText(/not lost/);

    announce(false);
    announce(true);

    expect(await screen.findByText(/“Save 50% today”/)).toBeTruthy();
    expect(screen.queryByText(/not lost/)).toBeNull();
  });
});
