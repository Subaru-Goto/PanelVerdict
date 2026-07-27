---
title: "Assemble the orchestrator graph (LangGraph)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [007-build-targeting-query-translation, 008-build-panel-evaluation, 009-build-bayesian-layer]
assignee: null
status: open
---

## Goal

Wire the real pieces into one LangGraph graph, replacing the tracer bullet's stubs:

parse target (007) → retrieve + sample personas → fan out panel batches (008) → update posterior (009) → **adaptive-stopping conditional edge** back to fan-out → aggregate & build the report payload (winner, posterior).

**Amended 2026-07-26 ([007](007-build-targeting-query-translation.md)):** the payload's "segment breakdown target vs. control" is dropped — a production panel is one target group and the posterior is read off it. Controls live in the testing track, not the product path.

Gap-fill persona generation is **fog** (see map Notes) — do not build it here unless the frontier has graduated it.

## Amended 2026-07-27 ([007](007-build-targeting-query-translation.md)) — this ticket owns the panel size

`select_panel(size=...)` takes any size ≥ 1 on purpose: it is a mechanism, and a
retrieval function that refused a small draw would block the tests and any
segment-vs-segment comparison that wants fewer. So **the panel-size policy lands here**:

- 007's Goal asks for **100–300 personas**, all target-matched.
- **n=200 is the signed-off default** (2026-07-27), chosen so a `practical_tie` is
  reachable at the ±7 ROPE — see [009](009-build-bayesian-layer.md).

Two things to get right rather than discover:

- A target may match **fewer** personas than requested; `PanelSelection.notices`
  carries a shortfall warning when it does. A thin panel changes what the verdict can
  say — at ±7 a `practical_tie` needs roughly 1,100 votes to be expressible at all —
  so the report must not present a 40-persona panel's verdict as a 200-persona one's.
- `settings.targeting_model` is declared and unread until this ticket constructs
  `OpenRouterTargetTranslator`.

## Amended 2026-07-27 ([008](008-build-panel-evaluation.md)) — a panel can now thin out twice

The shortfall above is one of **two** ways the panel reaching the posterior is smaller
than the one requested, and they compound:

1. **Retrieval** matched fewer personas than asked for ([007](007-build-targeting-query-translation.md)/[017](017-representative-sampling.md)) — carried by `PanelSelection.notices`.
2. **Votes failed.** `collect_panel_votes` returns `PanelVotes(records, failures)`: a
   vote that fails after the client's retries costs that panelist and no other, so 200
   requested personas can return 194 votes. `failures` carries the persona id and the
   error for each.

So the number the verdict rests on is `len(votes.records)`, not the requested size, and
**this ticket owns reconciling the two** — including 003's *"mark run partial, never emit
a half-panel"*, which needs a threshold nothing has set yet. Suggested shape rather than
a decision: the report states requested / matched / voted, and the run is partial when
voted falls below whatever fraction 009's interval width makes acceptable.

Two related things 008 deliberately left here, both because they are run-level:

- **A read timeout.** The OpenAI SDK's default is 600s, long enough that one hung
  request holds a worker for ten minutes. A shorter one turns slow-but-valid reasoning
  responses into failures, so it needs a measured latency distribution — and this is the
  ticket that first runs 200 real votes and can measure one.
- **The pre-flight budget check.** 003 asks for `GET /api/v1/key` before a run plus a
  graceful mid-run stop on 402. A rejected request is not charged, so a mid-run 402
  costs latency rather than money, which is why 008 has no circuit breaker: it would be
  guessing a policy this ticket can set from the real per-run cost. Note that 008 fans
  out with a concurrency cap rather than discrete batches, so there is no batch boundary
  for a stop to land on — the natural checkpoint is between panel *chunks* if this ticket
  wants one.
- **Per-vote caching**, keyed on `(persona, test, order)`. [002](002-decide-vote-schema.md)
  assigns it to 008 and 003 leans on it for resume-after-top-up, but it is not in 008's
  Goal and it cannot be built without deciding whether `test_id` is a persisted entity —
  which is this ticket's, because this ticket creates the run. It matters more than a
  cost saving: 003 removed `temperature≈0` (gpt-5-mini rejects it), so **this cache is now
  the only exact-replay mechanism the project has**, and 002's test-retest QA metric
  depends on it. `VoteRecord` already carries every column the table needs.

## Instrument the first real run (008, 2026-07-27)

Log `prompt_tokens`, `completion_tokens` and
`usage.completion_tokens_details.reasoning_tokens` on the first 200-vote run. Reasoning
tokens bill at the output rate and never appear in the response, so the per-test cost is
currently unmeasured and the retracted `$0.055` estimate could be several times low — see
the [003](003-decide-panel-model-and-provider.md) amendment. One run settles it, and the
same numbers are what the pre-flight check needs to be more than a guess.
