---
title: "Analyst can't answer panel-composition questions; loops into the step budget"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

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
