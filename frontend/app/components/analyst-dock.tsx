"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useRef, useState } from "react";

import { ANALYST_DISCLOSURE } from "../lib/disclosure";
import {
  readerTurns,
  type Analyst,
  type AnalystTurn,
} from "../lib/use-analyst";

/** The final chip copy. Each maps to a tool the demo has to show. Which tool a
 *  chip reaches is the analyst's routing decision, not a fixed mapping — the
 *  first two ask what a figure means and now route through explain_the_report,
 *  the third describes people and reaches search_personas. None can spend
 *  anything, and that is true of every tool the analyst has rather than a
 *  property of this list. */
/** PENDING USER SIGN-OFF (not yet approved): how close to the bottom still
 *  counts as "following along". A feel parameter, judged in a browser. */
const PINNED_SLACK_PX = 48;

const CHIPS = [
  "Why did the test stop early?",
  "How sure are we about the winner?",
  "Who was on this panel?",
];

function Turn({ turn }: { turn: AnalystTurn }) {
  if (turn.role === "user") {
    return (
      <p className="ml-8 self-end rounded-lg bg-zinc-100 px-3 py-2 text-sm dark:bg-zinc-800">
        {turn.text}
      </p>
    );
  }
  return (
    <div className="mr-8 flex flex-col gap-1 self-start">
      {turn.text !== "" && (
        <p className="whitespace-pre-wrap rounded-lg border border-zinc-200 px-3 py-2 text-sm dark:border-zinc-700">
          {turn.text}
        </p>
      )}
      {turn.status !== null && (
        <p className="px-1 text-xs italic text-zinc-500">{turn.status}</p>
      )}
      {turn.error !== null && (
        <p className="rounded-lg border border-red-300 px-3 py-2 text-sm text-red-700 dark:border-red-700 dark:text-red-400">
          {turn.error}
        </p>
      )}
    </div>
  );
}

export default function AnalystDock({ analyst }: { analyst: Analyst }) {
  // Closed on a fresh report now. Variant C traded an open dock for the chips
  // being visible once, but the report already carries the analyst's opening
  // summary — an open dock would only print it a second time.
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const { turns, busy, send } = analyst;
  // The report's opening exchange is on the page already; the dock shows the
  // conversation the reader is having. Both the transcript and the chips read
  // this, so they cannot disagree about whether one has started.
  const visible = readerTurns(turns);

  const inputRef = useRef<HTMLInputElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  // Whether the reader was still inside the dock when it closed. Read at close
  // time rather than in `onCloseAutoFocus`, which runs during the unmount when
  // `contentRef` has already been cleared.
  const closedFromInsideRef = useRef(true);
  const listRef = useRef<HTMLDivElement | null>(null);
  // Follow the conversation only while the reader is near the bottom, so
  // scrolling up to reread is not fought by the typewriter. jsdom does no
  // layout, so nothing here is unit-testable — verified in a browser.
  const pinnedRef = useRef(true);

  useEffect(() => {
    const list = listRef.current;
    if (list && pinnedRef.current) list.scrollTop = list.scrollHeight;
  }, [turns]);

  return (
    <Dialog.Root
      open={open}
      modal={false}
      onOpenChange={(next) => {
        if (!next) {
          closedFromInsideRef.current =
            contentRef.current?.contains(document.activeElement) ?? false;
        }
        setOpen(next);
      }}
    >
      <Dialog.Trigger
        // The panel is opaque, 384px wide, and anchored to this same corner,
        // so an open dock covers this button completely. Left in the tab order
        // it is a control a keyboard reader can reach but not see, where Enter
        // shuts the dock with no visible cause. Still focusable
        // programmatically, which is what the close restoration below needs.
        tabIndex={open ? -1 : undefined}
        className="fixed bottom-6 right-6 rounded-full bg-zinc-900 px-5 py-3 text-sm font-medium text-white shadow-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 dark:bg-zinc-100 dark:text-zinc-900 dark:focus-visible:outline-zinc-100"
      >
        Ask the analyst
      </Dialog.Trigger>
      <Dialog.Portal>
        {/* Non-modal, and no overlay. 057 kept the dock floating because "a
            panel that floats keeps the chart on screen while the reader asks
            about it", and a modal dialog measurably takes the report away: it
            sets `pointer-events: none` on the page and `aria-hidden` on every
            sibling, so for a screen-reader user the report ceases to exist
            while the dock explains it. What a dialog is really for here —
            Escape, focus restoration, an announced role and name — is kept;
            the Tab-trap is what a non-modal dialog gives up, and it is the one
            part that would have cost the reader the thing they came for.
            Decided 2026-08-27, amending 093's "traps focus" wording. */}
        <Dialog.Content
          ref={contentRef}
          // A helper that closes the moment you touch what you are asking
          // about is no helper, so every outside-dismissal path is refused:
          // Escape and Close are the ways out. All three are needed — reaching
          // into the report is a pointer press AND a focus move, and a browser
          // check showed the dock closing with only the general handler on.
          onPointerDownOutside={(event) => event.preventDefault()}
          onFocusOutside={(event) => event.preventDefault()}
          onInteractOutside={(event) => event.preventDefault()}
          onOpenAutoFocus={(event) => {
            // Prefer the input — the reader opened this to type, and the chips
            // are one Tab away either way. But only when it can actually take
            // focus: the report opens a conversation on mount, so `busy` is
            // true (and the input `disabled`) from the first frame until the
            // opening summary has finished revealing. Focusing a disabled
            // input is a no-op, and having prevented Radix's own open-focus
            // there would be nothing behind it — the reader would land on
            // `body`, with the dialog never announced.
            const input = inputRef.current;
            if (input && !input.disabled) {
              event.preventDefault();
              input.focus();
            }
          }}
          onCloseAutoFocus={(event) => {
            // Radix's own version of this guard is disabled by the blanket
            // refusal above: it only records an outside interaction when the
            // event was not default-prevented. So it is done here instead.
            // Escape is heard at the document, so it fires wherever the reader
            // is — and one who had gone back to the chart should stay there
            // rather than be thrown to a button in the corner.
            if (!closedFromInsideRef.current) event.preventDefault();
          }}
          className="fixed bottom-6 right-6 flex max-h-[70vh] w-96 max-w-[calc(100vw-3rem)] flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-4 shadow-xl dark:border-zinc-700 dark:bg-zinc-900"
        >
          <header className="flex items-start justify-between gap-2">
            <div className="flex flex-col">
              <Dialog.Title className="text-sm font-semibold">
                Ask the analyst
              </Dialog.Title>
              {/* The first sentence is a legal duty, not flavour: anyone
                  chatting with an AI system must be told so, in context,
                  before the first exchange — a footer mention or an
                  "assistant" label does not count. As the dialog's
                  `Description` it is also read out when the dialog opens,
                  rather than only if the reader browses to it. */}
              <Dialog.Description className="text-xs text-zinc-500">
                {ANALYST_DISCLOSURE}
              </Dialog.Description>
            </div>
            <Dialog.Close className="rounded px-2 py-1 text-xs text-zinc-500 hover:bg-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-500 dark:hover:bg-zinc-800">
              Close
            </Dialog.Close>
          </header>

          {visible.length > 0 && (
            <div
              ref={listRef}
              onScroll={() => {
                const list = listRef.current;
                if (list) {
                  pinnedRef.current =
                    list.scrollHeight - list.scrollTop - list.clientHeight <
                    PINNED_SLACK_PX;
                }
              }}
              className="flex flex-col gap-2 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            >
              {visible.map((turn, index) => (
                <Turn key={index} turn={turn} />
              ))}
            </div>
          )}

          {visible.length === 0 && (
            <div className="flex flex-wrap gap-2">
              {CHIPS.map((chip) => (
                <button
                  key={chip}
                  type="button"
                  disabled={busy}
                  onClick={() => void send(chip)}
                  className="rounded-full border border-zinc-300 px-3 py-1.5 text-xs hover:bg-zinc-100 dark:border-zinc-600 dark:hover:bg-zinc-800"
                >
                  {chip}
                </button>
              ))}
            </div>
          )}

          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void send(draft);
              setDraft("");
            }}
          >
            <input
              ref={inputRef}
              aria-label="Ask about this test"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              disabled={busy}
              placeholder="Ask about this test…"
              className="min-w-0 flex-1 rounded border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-900"
            />
            <button
              type="submit"
              disabled={busy || draft.trim() === ""}
              className="rounded bg-zinc-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
            >
              Send
            </button>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
