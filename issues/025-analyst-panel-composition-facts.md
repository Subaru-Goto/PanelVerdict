---
title: "Analyst can't answer panel-composition questions; loops into the step budget"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: closed
---

## Closed 2026-07-30 — delivered in PR #75, and the diagnosis grew twice

One incident turned out to have **three** causes, only the first of which
this ticket originally named:

1. **The tools lacked the facts** — fixed by `PanelComposition` on
   `analyze_results` (age min/median/max, spread by country, gender,
   education level and income band, from votes the request already carries;
   no new paid call).
2. **Nothing told the model those facts existed** — `analyze_results`'
   description never mentioned the panel while `search_personas` advertised
   "who was on the panel" and returns profiles, not a distribution. Found by
   review; see the blind-spot section below.
3. **The prompt forbade the model to think** — "answer only from tool
   results" made looping the obedient response when no tool fit. Found by
   the user; see the second-cause section below.

The step budget was never touched, as this ticket demanded. It now has a
clean job again: if looping recurs *after* all three fixes, that is real
evidence about the budget rather than about a gap it was hiding — and it
would need a sourced number, not a guess.

## Problem (found in real use, 2026-07-30)

Asked "I told you to target young Japanese people, but it includes 90 year
olds?", the analyst burned every step re-calling tools and the turn died on
the tripwire: "analyst was still calling tools after 8 steps". No answer was
communicated — the looping rounds had no text to stream.

Root cause is a capability gap, not the budget: **no tool can answer a
question about the panel's composition.** `analyze_results` carries verdict,
tally, counts, stop reason — no ages. `search_personas` returns the 5
panelists most similar to a description — it cannot enumerate the panel or
report a distribution. The model judged the answer one-more-call away and
kept calling, which is exactly the failure mode the budget converts into a
visible error.

The data already exists in the request: `result.votes[].voter` carries every
voter's age, gender, country, education and income band. Nothing serves it.

## Fix

Extend `AnalysisFacts` (and so `analyze_results`) with a small
panel-composition summary computed from `result.votes` — zero new paid
calls. Sketch: voter age min/max/median, counts by country and gender,
education spread. Shape is the implementer's; the pin is that "why does the
panel include 90-year-olds?" becomes a one-tool-call answer.

## Amended 2026-07-30 — a second live finding, folded in

Same session, same surface: the analyst was **quoting persona ids** at the
user and **narrating its own machinery** ("I ran the test-results tool for
this panel…"). Both are about what the analyst says rather than what it
knows, so they ship with the composition facts rather than as a second
one-file PR.

- **Ids are gone by construction, not by instruction.** `search_personas`
  now returns summaries only. [023](023-vote-feed-voter-details.md) already
  ruled for the report that "an id identifies a row, not a reader"; the
  analyst was breaking that rule because the tool handed it ids. A model
  cannot quote a handle it was never given — the same unconstructible-by-
  design move as 012b's event union.
- **Two prompt rules added:** never name a tool, function, field or step;
  describe panelists as people, never as handles.

**Honest limit on the second one:** a prompt rule's *effect* cannot be
asserted — asserting the constant contains the sentence would be
tautological, and whether the model actually obeys is a
quality-with-degrees question, i.e. judge territory (see the map's
DeepEval/CI note). What ships tested is the mechanical half: the id is
absent from the tool result. The prose half is verified by using it.

## Second cause of the same loop (user, 2026-07-30)

The problem statement above blamed the loop on a capability gap alone. The
user identified a second cause, in the prompt: the first rule read **"answer
only from tool results"**, flatly. A model asked something no tool covers
had therefore been *told* it may not answer from its own knowledge — so
calling another tool was the obedient move, not a malfunction. The escape
hatch ("say so when they cannot answer") was one clause competing against a
blanket prohibition, and lost.

The boundary the rule was missing, and now states: **facts about this test
come from tools every time — never memory, never estimate, never inference
from earlier turns — while general questions are answered directly, with no
tool call at all.** Hallucinated statistics are the cardinal sin here; a
hallucinated definition of "credible interval" is just an answer.

So the fix for the incident is really three-part: give the tools the missing
facts, tell the model those facts exist (the blind spot below), and stop
forbidding the model from thinking. Only the first was in the original
diagnosis.

## The suite's blind spot, found by review 2026-07-30

The first cut of this fix added the composition facts but left both tool
**descriptions** untouched — so `search_personas` still advertised "who was
on the panel" while `analyze_results` never mentioned the panel at all. On
this ticket's own motivating question the model would still have been
steered to the tool that returns five profiles and no distribution, i.e.
straight back into the loop 025 exists to kill. The data was there; the
signpost pointed the other way.

**The suite could not have caught it, and still cannot.** `ScriptedChatModel`
chooses the tool on the model's behalf, so every agent test proves what
happens *after* a tool is called and nothing about which tool a real model
would reach for. Tool routing is therefore the same kind of unassertable
question as prompt obedience: quality-with-degrees, judge territory.

Practical consequence, worth remembering beyond this ticket: **whenever a
tool gains a capability, its description is part of the change** — the
description is the only thing the model actually reads. A capability the
description doesn't mention is a capability the model doesn't have.

## Deliberately NOT changing (yet)

The step budget `2 * len(tools) + 2` encodes "each tool used about once per
turn", and real usage broke that assumption on day one. Do not raise it as
part of this ticket: a budget raised to accommodate a capability gap hides
the gap. Reconsider (with a sourced or signed-off number) only if looping
persists after the composition facts land.

## Related

- Found together with [024-fuzzy-age-words-in-targeting](024-fuzzy-age-words-in-targeting.md);
  with this fix the analyst's first reply would have shown the 23–91 spread
  and surfaced that bug in-chat.
- Ticket 012's closed decision log records the budget's tripwire-not-gate
  framing.
