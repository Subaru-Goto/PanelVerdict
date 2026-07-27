---
title: "Assemble the orchestrator (plain Python; LangGraph deferred to v2)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [007-build-targeting-query-translation, 008-build-panel-evaluation, 009-build-bayesian-layer]
assignee: null
status: open
---

## Goal

Wire the real pieces into one pipeline, replacing the tracer bullet's stubs:

parse target (007) → retrieve + sample personas → fan out panel batches (008) → update posterior (009) → **adaptive-stopping conditional edge** back to fan-out → aggregate & build the report payload (winner, posterior).

**Token logging ships with the first run, not after it** (signed off 2026-07-27) — see
[Instrument the first real run](#instrument-the-first-real-run-008-2026-07-27) below. It is
a handful of lines, and skipping it means the first real 200-vote run happens and teaches
us nothing about what it cost. The project currently has **no** per-test cost estimate; the
old one was retracted, not replaced.

**Amended 2026-07-26 ([007](007-build-targeting-query-translation.md)):** the payload's "segment breakdown target vs. control" is dropped — a production panel is one target group and the posterior is read off it. Controls live in the testing track, not the product path.

Gap-fill persona generation is **fog** (see map Notes) — do not build it here unless the frontier has graduated it.

## Decided 2026-07-27 — plain Python for v1, LangGraph at v2

**LangGraph is not a v1 dependency.** It was never installed: [004](004-standup-skeleton-infra.md)
deferred it to "the first ticket that actually uses it", and that ticket is this one, which
is where the cost would finally be paid. It is also **not a graded requirement** — those are
advanced RAG, tool calling, LangChain + OpenRouter, and the UI. The graph was an
architectural preference recorded in `docs/project-idea.md`, not a commitment.

**Because the flow is linear apart from one loop.** A conditional edge back to a node is a
`while`, and [009](009-build-bayesian-layer.md) chose conjugacy precisely so a batch update
is arithmetic rather than a re-fit:

```python
while undecided(posterior) and voted < max_n:
    votes = collect_panel_votes(panel[voted:voted + step], ...)
    posterior = update(posterior, votes)
    voted += step
```

What LangGraph would have supplied, against what already exists:

| feature | v1 answer |
|---|---|
| checkpoint / resume | the **per-vote cache** below resumes at *vote* granularity; a node checkpoint resumes at a chunk boundary and loses up to a chunk |
| parallel fan-out (`Send`) | [008](008-build-panel-evaluation.md)'s `ThreadPoolExecutor`, already built and tested — adopting `Send` would mean two mechanisms for one job |
| streaming state to the UI | wanted for *"87/200 personas voted…"*, but that is a callback plus SSE, not a graph |
| LangSmith tracing | driven by LangChain callbacks, not LangGraph-specific |
| human-in-the-loop interrupts | not in v1 |

Against that: a dependency, and a `State` schema plus graph wiring becoming the thing under
test instead of the pipeline logic.

**This does not foreclose v2.** Well-factored functions become nodes almost mechanically;
unpicking a graph is the expensive direction. The place LangGraph would genuinely earn its
keep is [012](012-build-analyst-chatbot-tools.md) — multi-turn chat, a tool loop, message
history across turns — so that is where v2 should adopt it, on evidence, rather than here.

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
   vote that fails after the client's retries costs that panelist and no other, so a
   run can return fewer votes than the panel it was drawn for. `failures` carries the
   persona id and the error for each. **How often, and how many, is unmeasured** — no
   real 200-vote run has happened yet, which is one more reason this ticket cannot set
   the partial-run threshold from anything but its own first run.

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

**Signed off as part of this ticket, not a follow-up.** Three numbers per vote, off the
response's own `usage`:

| field | why |
|---|---|
| `prompt_tokens` | confirms the ~300–370 input figure computed in [`prompt-caching.md`](../docs/research/prompt-caching.md) against a real request, schema included |
| `completion_tokens` | the visible vote — the only part the retracted estimate ever modelled |
| `completion_tokens_details.reasoning_tokens` | **the unknown.** Bills at the output rate ($2/M) and never appears in the response, so this single field is what makes the per-test cost knowable |

Aggregate them per run, not per vote, and record the totals wherever the run is recorded.

Why it cannot wait. The `$0.055`/200-persona figure is **retracted, not corrected**
([003](003-decide-panel-model-and-provider.md) amendment): it assumed a prompt cache that
cannot exist *and* ~80 output tokens with no reasoning allowance, so the true cost is
unmeasured and more likely above it than below. Consequences that are live right now:

- *"$10 cap ≈ ~180 full tests"* is not plannable, and the cap is a hard 402.
- The **pre-flight budget check** this ticket owns needs a per-run cost to compare against
  `limit_remaining`. Without these numbers that check is a guess wearing a decimal point.
- 014 and 015 ran ~7,000 votes between them and logged nothing, so there is no historical
  data to mine — the information only exists while a run is happening.

One 200-vote run settles it exactly. A 10-persona run settles it approximately for well
under a cent, which is worth doing first if the graph is not yet end-to-end.

The reason this is stated as a deliverable rather than a note: a run that completes without
these three fields is a run whose cost is gone. There is no way to recover it afterwards.
