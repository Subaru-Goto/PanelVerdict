---
title: "Nothing confirms the panel before the money is spent — the human-in-the-loop gap"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: Subaru-Goto
status: closed
---

## Resolution (2026-08-21): superseded by the graph — one `interrupt()`, not two endpoints

The gap this ticket names is real and stays the design's centre; the **mechanism** moved,
exactly as [055-map-public-demo](055-map-public-demo.md)'s fog note predicted. With
[067](067-where-is-a-hand-authored-graph-worth-it.md) resolved to a hand-authored graph
around the vote loop, the gate is an `interrupt()` at a `confirm` node —
[076](https://github.com/Subaru-Goto/PanelVerdict/issues/166) builds it,
[077](https://github.com/Subaru-Goto/PanelVerdict/issues/167) shows it to the reader.

What changed against this ticket's text, and why each change is sound:

- **"Anyone reaching for `interrupt()` here will find nothing to interrupt"** was true
  when written and was corrected by [068](068-amend-054-langgraph-is-installed.md)
  (langgraph *is* installed); now `/evaluate` gets a graph, so the framework primitive
  serves after all.
- **The two-endpoint recommendation with a client-returned approved query is dropped.**
  The checkpointer holds the paused state server-side, so the caller-supplied-filter
  concern and the phase-2 re-translation option both dissolve; the pending-state
  question this ticket flagged lands on 076's recorded decisions.
- **The author enlarged the ask (2026-08-21):** the preview shows the seated panel's
  *composition* (age, country, gender, education, income distributions), and the reader
  can **redraw** — a fresh free sample under the same filter — not only accept. Both
  live in 077's scope; "editing the filter by hand" stays out, as here.

Everything else — the seam at `select_panel`, the everything-is-already-computed table,
the warn-versus-gate argument for why `budget_notice`'s never-refuse stance does not
transfer to interpretation errors, the complementarity with
[016](https://github.com/Subaru-Goto/PanelVerdict/issues/123) — carries forward unchanged as the
rationale 076/077 build on.

## The gap

`/evaluate` takes a free-text audience description, has a model translate it into a
structured filter, draws a panel, and buys up to 200 votes — **in one request, with no
point at which a human sees the interpretation before paying for it.**

The reader types *"young professionals in Germany"* and the next thing they see is a
finished report. If the translation was wrong, they have paid for a confidently-argued
verdict about **the wrong audience**, and nothing on the report says so.

## What "human in the loop" means here, and what it does not

Worth stating because the term is loose in conversation. HITL is **pausing execution so a
human can approve or redirect before the consequential step**. That has exactly one target
in this system: the moment between *"here is the panel I resolved"* and *"here are 200 paid
votes."*

It is **not** the analyst. `build_tools`' invariant is that *"every one of them reads. None
of them spends, and none of them writes."* There is nothing in a chat turn to approve.

**And the framework primitives cannot serve this**, for the same structural reason
[045](https://github.com/Subaru-Goto/PanelVerdict/issues/143) records for rate limiting:

- LangGraph's `interrupt()` requires a graph. **`/evaluate` has no agent** — `create_agent`
  appears only in `analyst.py`, and `pipeline.py` has zero references to it.
- `langgraph` is not importable in this environment and is not a declared dependency.

So this is an HTTP-shaped change, not a graph-shaped one. Anyone reaching for `interrupt()`
here will find nothing to interrupt.

## The seam already exists

`pipeline.py:255` splits precisely where the gate belongs:

```python
selection = select_panel(conn, description, size=size, translator=translator)
if not selection.panel:
    raise EmptyPanel(...)
test_id = str(uuid4())        # <- everything above is cheap; everything below is paid
```

**Everything a human needs in order to approve is already computed before a single vote is
bought:**

| what | where it exists today |
|---|---|
| the resolved filter | `selection` → `TargetQuery`, already on `EvaluateResponse.query` |
| who actually matched | `selection.panel`, and the matched count behind `_vote_shortfall_notice` |
| shortfalls and caveats | `notices`, some of which are generated during selection |
| **the cost** | `main.py:134` already computes `size * USD_PER_VOTE` for `budget_notice` |

None of it is new work. **All of it is currently revealed only after the money is spent.**

## The objection this ticket has to answer

This codebase has a **documented stance against blocking on a warning**, and it is not
incidental. `budget_notice`:

> *"Warn-and-proceed, never refuse: a run the credit cannot finish is still worth starting,
> because every vote it casts lands in the ledger and a re-run after top-up resumes free."*

That reasoning is sound and **it does not transfer**, which is the argument for this ticket.

`vote_fingerprint` keys on `[configuration, system_prompt, option_1, option_2]`, and the
system prompt is the *rendered persona*. So:

- **Thin credit:** the votes you bought are for the right panel. Top up, re-run, and every
  one of them is a cache hit. Proceeding really is harmless.
- **Wrong target:** a corrected target draws **different personas**, so different system
  prompts, so different fingerprints. Every vote you bought is a **cache miss on the re-run
  and the money is simply gone.**

So the existing stance is right about credit and silent about interpretation. This gate is
not a second guess at `budget_notice`; it covers the case whose failure is unrecoverable.

## Not a substitute for 016

[016](https://github.com/Subaru-Goto/PanelVerdict/issues/123) measures whether the translator returns the
right filter. That reduces how often a human needs to intervene; it does not remove the need
to show an interpretation before spending on it. **Complementary, and worth saying so** —
a gate is not an excuse to skip measuring the translator, and a measured translator is not a
reason to spend without showing the reader what was understood.

## How phase 2 gets phase 1's decision

The real design decision, and the options differ in more than plumbing:

| option | cost | problem |
|---|---|---|
| **client returns the approved `TargetQuery`** | small; no new persistence | the filter is then caller-supplied, so translation becomes skippable — see below |
| server persists a pending selection, phase 2 references it by id | needs the first *pending run* state this system has ever had, plus expiry | bigger, and `ChatRequest` already records that **nothing persists a finished test** — this would be new ground |
| re-translate in phase 2 | pays the translation twice and is not guaranteed to return the same filter, since it is a model call | no |

**Recommended: the client returns the approved query.** The caller-supplied-filter concern
is worth stating and is mild — the pool is fixed synthetic data, so a hand-crafted filter
selects differently but reaches nothing it should not. It also keeps `EvaluateResponse.query`
honest as *"the filter contract the verdict was drawn under"*, because that is exactly what
it remains.

If a `tests` table is ever built — [046](https://github.com/Subaru-Goto/PanelVerdict/issues/144) wants one
for durable threads, [049](https://github.com/Subaru-Goto/PanelVerdict/issues/147) to recover a report,
[053](https://github.com/Subaru-Goto/PanelVerdict/issues/150) to reference feedback — the second
option becomes the better end state and this should migrate onto it.

## The cheap phase is not free

`docs/research/targeting-call-effort.md` opens with the reason to care: a single translation
call once cost **$0.13** — *"roughly a whole 200-vote panel run"* — by generating 65,536
completion tokens and failing to parse. It is bounded now by
`TARGET_MAX_COMPLETION_TOKENS` and `TARGET_REASONING_EFFORT`.

So *"just re-run phase 1 until the reader is happy"* has a real price, and a design that
re-translates on every edit is worse than one that lets the reader adjust the resolved
filter directly.

## Scope

- Split `/evaluate` into a phase that resolves and a phase that spends. The seam is
  `select_panel`; do not restructure the pipeline around it.
- The resolve phase returns the filter, the matched count, its notices, and the **cost
  estimate that already exists** — no new number, and none invented.
- The spend phase takes an approved filter and runs votes.
- `EmptyPanel` moves earlier in the reader's experience, which is a straight improvement:
  today *"no persona matches this target"* arrives as a 422 after a translation; under this
  flow it arrives in the phase whose job is to say so.
- A frontend step that shows the interpretation and lets the reader proceed or go back.

## Deliberately out of scope

- **Editing the resolved filter by hand.** Showing it is the ticket; making it a form is a
  larger feature and a different argument.
- **Approval on anything else.** Adaptive stopping and partial runs make automatic calls
  that save money or report honestly; [010b](010b-partial-run-threshold.md) owns the second
  and neither needs a human.
- **Persisting pending runs**, per the table above.

## Done when

A reader sees the audience the system understood, and what it will cost, **before** any vote
is bought — and a mis-read target costs a click instead of $0.145 and a report about
somebody else.
