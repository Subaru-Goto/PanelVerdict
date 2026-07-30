---
title: "The analyst cannot read what the panel said: no tool serves vote reasons"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Problem

Ask the dock *"why did they prefer B?"* and it has nothing to read. Checked
tool by tool:

- `analyze_results` — verdict, tally, counts, polling, region match, notices,
  panel demographics. No reasons.
- `search_personas` — `persona_summary`, which is a *profile* ("A 34-year-old
  female living in Japan, who…"). No reason.
- `run_panel_test` — the same facts shape.

This is [025](025-analyst-panel-composition-facts.md) exactly: the data rides
in every request as `result.votes[].reason` — the very text `VoteList` prints
on screen — and nothing hands it to the model. The server already holds it;
there is no door.

Surfaced by a reading problem rather than a chat one: 25 free-text reasons are
too many to read, so the report needs a summary of them
([030](030-report-reading-order.md)) — and a summary of prose is a model job,
which cannot happen while the model cannot see the prose.

## Fix

A new tool, `read_reasons`, rather than more fields on `analyze_results`.
Twenty-five reasons run to roughly 750 tokens, and paying that on every
question about the tally is waste; the model should buy them only when the
question is about *why*.

Grouped by the variant chosen, with each variant's headline beside its
reasons, because the real question is always what the B-choosers said that the
A-choosers did not — an ungrouped list makes the model do that join itself,
badly.

Per 025's rule, the tool's **description ships with the capability**: a
capability the description does not mention is one the model does not have.

## Not capping the list

A 200-panelist run would send ~6,000 tokens per call. No cap ships, because
any number here would be invented: `_SEARCH_LIMIT`'s 5 carries an explicit
sign-off note, and this would carry nothing. v1's dev profile runs 25, which
is comfortable. Recorded as a known limit that grows with panel size rather
than papered over with a guess.

## Security note, recorded rather than solved

This is the **first** path putting another model's free text into the
analyst's context. Everything the analyst reads today is ours: the system
prompt is a constant with zero interpolation, `persona_summary` is
code-composed, notices are backend-composed sentences, and every verdict
figure is recomputed rather than trusted. A reason is written by the vote
model, whose prompt contains the **user's headlines** — so a crafted headline
is a path, however thin, to text that reaches the analyst.

What it cannot do is move a number: the analyst's figures come from
`verdict.py`, recomputed, and no reason touches them. The exposure is prose
only. Belongs to [013](013-guardrails-mvp.md) if it is ever worth hardening;
noted here so the next reader knows the boundary moved.

## The step budget moved, and this is the case it was built for

`2 * len(tools) + 2` went 8 → 10 with the fourth tool, and the stream test's
pinned sentence moved with it. That is the formula working, not the thing
[025](025-analyst-panel-composition-facts.md) forbade: 025 refused to *raise*
the budget to accommodate a capability gap, because a budget raised to hide a
gap hides it. Here a genuinely new tool earns a genuinely new round. The
tripwire still fires at one round per tool plus a close.

## Two descriptions changed, not one

`analyze_results` opened with "Everything known about this test", which stopped
being true the moment a word of it lived elsewhere — and an overclaiming
description steers the model away from the tool it now needs. It leads with
"Every number and every count for this test — but not a word anyone said,
which is read_reasons."

This is 025's blind spot repeating on schedule, and it is worth naming as a
pattern rather than an incident: **adding a tool changes the descriptions of
the tools it takes work away from.** The suite cannot see it —
`ScriptedChatModel` picks the tool on the model's behalf, so routing stays
unassertable.

## Related

- [025](025-analyst-panel-composition-facts.md) — the same shape of gap, and
  the source of the description-ships-with-the-capability rule.
- [030](030-report-reading-order.md) — the reader-facing half this unblocks.
