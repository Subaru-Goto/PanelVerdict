---
title: "Vote-usage instrumentation: measure what a panel test actually costs"
labels: [wayfinder:task]
parent: 010-assemble-orchestrator-graph
blocked_by: []
assignee: null
status: open
---

## Goal

Record `prompt_tokens`, `completion_tokens` and **`reasoning_tokens`** per vote, aggregate
them per run, then spend well under a cent measuring a real one — and write the resulting
per-test cost into [003](003-decide-panel-model-and-provider.md) and
[`panel-model-selection.md`](../docs/research/panel-model-selection.md).

First of 010's children on purpose. It is the only one whose information **expires**: a run
that finishes without these fields is a run whose cost is gone, and three sibling tickets
are guessing until it lands.

## Why this is not optional

The project currently has **no** per-test cost estimate. The old `$0.055 / 200-persona test`
was retracted rather than corrected, because it assumed a prompt cache that
[cannot exist](../docs/research/prompt-caching.md) *and* ~80 output tokens with no allowance
for reasoning. So:

- *"$10 cap ≈ ~180 full tests"* is not plannable, and the cap is a hard 402 with no overage.
- [010f](010f-budget-guard.md)'s pre-flight check has nothing to compare `limit_remaining`
  against.
- [010b](010b-partial-run-threshold.md) is reasoning about run economics without knowing them.

And there is nothing to mine: [014](014-targeting-manipulation-check.md) and
[015](015-task-framing-sensitivity.md) ran ~7,000 votes between them and logged none of it.

## The one real technical wrinkle

`ChatOpenAI.with_structured_output(PanelVoteOutput)` returns the **parsed pydantic object**,
which means the `AIMessage` — and with it `usage_metadata` — is discarded. So `usage` is not
merely unlogged today, it is unreachable through the current call.

Two ways out, and the choice is this ticket's:

- `with_structured_output(..., include_raw=True)`, which returns a dict of
  `{"raw", "parsed", "parsing_error"}` — usage lives on `raw.usage_metadata`. Changes
  `OpenRouterPanelLLM.vote`'s internals, not the `PanelLLM` protocol.
- A LangChain callback handler collecting usage out of band. Keeps the call shape but puts
  the numbers somewhere less obviously attached to the vote they belong to.

Prefer `include_raw=True`: the usage belongs to that vote, and `parsing_error` is the same
failure `vote` already converts into a raise, so nothing is lost. Confirm that
`reasoning_tokens` survives OpenRouter and reaches
`usage_metadata["output_token_details"]["reasoning"]` — if it does not, that is a finding
worth writing down rather than working around, because it would mean the dominant cost term
is invisible through this stack.

## Where the numbers go

Aggregate **per run**, not per vote — a 200-vote run wants one line, not two hundred. The
per-vote figures are only interesting as a distribution (see below), so keep them in memory
and emit totals.

`collect_panel_votes` returns `PanelVotes`; usage is a natural third field beside `records`
and `failures`. It is the same shape argument the failures made: a caller that cannot see
what a run cost cannot report it.

## The calibration run

A **10-persona** panel against the real model, which costs a fraction of a cent and settles
the order of magnitude. Do not wait for [010c](010c-panel-test-pipeline.md) — `FIXED_PANEL`
plus `collect_panel_votes` is enough to run this today.

Record, in `panel-model-selection.md`:

- mean and spread of `prompt_tokens` (the ~300–370 estimate, confirmed or corrected against
  a real request with the schema included),
- mean and spread of `completion_tokens` and `reasoning_tokens`,
- the derived cost of a 200-vote run at the sourced $0.25/$2 per M,
- **the observed per-vote latency distribution**, which is what
  [010f](010f-budget-guard.md) needs to set a read timeout instead of leaving the SDK's 600s.

Ten votes is not a distribution. State it as an order-of-magnitude reading, and note that
the 200-vote run in 010c supersedes it — the point is to stop planning against a retracted
number, not to publish a benchmark.

## Out of scope

Cost *display* in the UI, and any budget enforcement. This ticket measures; 010f decides
what to do about it.
