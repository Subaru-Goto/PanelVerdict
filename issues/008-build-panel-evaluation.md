---
title: "Build the panel evaluation module"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [002-decide-vote-schema, 003-decide-panel-model-and-provider, 006-build-persona-pool]
assignee: null
status: closed
---

## Goal

Turn a sampled panel into votes:

- render persona → system prompt via template (**Big Five via BFI-2-Expanded-style sentences, never numeric/Likert** — Huang et al. 2026),
- **shared-prefix** (instructions + variants) for prompt caching,
- **per-agent A/B order randomization** (position-bias defense — this is also the load-bearing guardrail),
- structured output per the 002 schema,
- run in batches (~25), returning votes + reasons + order labels.
## Closed 2026-07-27 — what shipped

Four of the five bullets are code; the fifth turned out to be impossible and is recorded
as such rather than built.

- **Persona → prompt via template**, BFI-2-Expanded-style sentences. Already shipped in
  [006j](006j-persona-summary-embedding.md); what 008 added is the **test** that no trait
  score can reach either rendering. The digits in the vote prompt and the persona summary
  are asserted to be exactly the age, because a reworded template that interpolated a
  score would still render, still read fluently, and quietly turn every panelist into a
  questionnaire respondent — the thing Huang, Zhang, Soto & Evans 2026 says not to do.
- **Order assignment** — `vote.presentation_orders`. See the section below; this was a
  correctness fix, not new work.
- **Structured output** per [002](002-decide-vote-schema.md) — already shipped;
  `PanelVoteOutput` via `response_format` json-schema (which is what LangChain's
  `with_structured_output` sends by default, not a forced tool call — this settles the
  "confirmed at build time" note in [003](003-decide-panel-model-and-provider.md)).
- **Batches (~25)** — a `ThreadPoolExecutor` capped at 25, returning `PanelVotes`
  (records with reasons and order labels, plus failures).
- **Shared prefix for prompt caching** — **not built. It cannot work here.** See the 003
  amendment and [`docs/research/prompt-caching.md`](../docs/research/prompt-caching.md):
  the request is ~300–370 tokens against a 1,024-token minimum, and the saving is bounded
  above by under 2¢ per test. Chasing it would mean reordering the prompt that 014 and
  015 measured against.

## The order assignment was a bug, not a feature

[002](002-decide-vote-schema.md) had already written down that what shipped in
[005](005-tracer-bullet.md) was inadequate: *"an odd-sized panel does not deliver it
(index-parity alternation leaves the imbalance correlated with whatever the panel is
ordered by)"*. `presentation_orders` builds the exact 50/50 split, then shuffles it with a
seed — which is both halves of 002's own sentence, *"order randomised and stored per vote;
overall 50/50 counterbalanced"*.

Why each half is load-bearing:

- **Exact split**, because gpt-5-mini picks the first-shown option **0.66** of the time
  (014, 5,400 votes). A surplus of one order is a bias on the top line, not noise that
  averages out.
- **Shuffled**, because assigning by index ties who-sees-which-order to however the panel
  arrived — and the caller chooses that. `load_pool` returns id order, which groups by
  country.

That second one is not hypothetical. `experiments/design.py` documents hitting it: a
five-level trait sweep put `VERY_LOW` at index 0 every time, so the imbalance landed on
the level under test and a position-biased model would have manufactured a gradient that
looked exactly like the effect. Its own answer — run *both* orders per persona — is
stronger than counterbalancing and remains right for a within-persona comparison.

## Deliberately left out

**Per-vote caching.** 002 assigns it to this ticket (*"per-vote caching keyed on
`(persona, test, order)` (008) for exact replay"*) and 003 leans on it for
resume-after-402. It is **not** in this ticket's own Goal, and it needs a `votes` table
plus a decision about whether `test_id` is a persisted entity — which is
[010](010-assemble-orchestrator-graph.md)'s, since 010 creates the run. Building the table
here would pre-empt that. `VoteRecord` already carries every column such a table needs, so
this is deferred, not blocked.

**A read timeout and the pre-flight budget check** — both need numbers only a real
200-vote run produces, and both are recorded in 010. No circuit breaker on 402 either: a
rejected request is not charged, so a mid-run 402 costs latency rather than money, and the
stop policy is 010's to set from measured cost rather than 008's to guess.

## What a failed vote does

`PanelVotes` carries `records` and `failures` together. A vote that fails after the
client's retries (the OpenAI SDK's default 2, with backoff, now stated explicitly because
25-way fan-out makes 429s expected traffic) costs that panelist and no other — 200
requested personas can return 194 votes.

This is the same division retrieval already draws: the mechanism reports what happened,
the caller decides whether a thinner panel still deserves a verdict. It also means the
panel can thin out **twice** — retrieval matching fewer than asked, then votes failing —
and reconciling the two, including 003's *"mark run partial, never emit a half-panel"*, is
recorded in 010.
