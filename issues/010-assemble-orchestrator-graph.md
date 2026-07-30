---
title: "Assemble the orchestrator (plain Python; LangGraph deferred to v2)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [007-build-targeting-query-translation, 008-build-panel-evaluation, 009-build-bayesian-layer]
assignee: null
status: closed
---

## Goal

Wire the real pieces into one pipeline, replacing the tracer bullet's stubs:

parse target (007) → retrieve + sample personas → fan out panel batches (008) → update posterior (009) → **adaptive stopping** back to fan-out → aggregate & build the report payload.

## Closed 2026-07-30 — all six children closed, on this ticket's own terms

"This ticket closes when every child does" — 010a through 010f are all
closed, and the pipeline they add up to is what `/evaluate` runs: target
description in, chunked voting with adaptive stopping, per-vote cache,
budget guard, verdict out.

**The v1/v2 line this ticket drew was itself revisited, and moved once.**
010 deferred LangGraph to v2 and told [012](012-build-analyst-chatbot-tools.md)
it could not reach for it either. 012 then established what the deferral was
actually protecting v1 from — **authoring graphs** (nodes, edges,
human-in-the-loop), not the langgraph *runtime* as a transitive dependency —
and adopted `create_agent` for the analyst on that basis. The hand-rolled
loop's own evidence is on the record: ~30 lines, not painful, so the
framework was taken for idiom and learning value rather than necessity.
Graph authoring remains v2, and the evidence for it is now concrete rather
than anticipated: both of the recorded v2 wants — an `interrupt()` spend
gate before `run_panel_test`, and carrying the current test in graph state
so `analyze_results` follows a re-run — are edge-level problems that
authoring solves and `create_agent` cannot.

**Agent middleware, the question this branch left open**, got its final
answer at 012's close: never needed. The three-tool loop wanted neither
effort escalation nor per-turn model swaps.

## Split into children 2026-07-27

This ticket had accumulated **eight** deliverables, three of which cannot be decided without
numbers a real run produces. One PR for all of that would be unreviewable, so the work moves
to children and this ticket keeps the decisions that span them — the same shape
[006](006-build-persona-pool.md) took with 006a–006j.

| | ticket | blocked by |
|---|---|---|
| **[010a](010a-vote-usage-instrumentation.md)** | Vote-usage instrumentation + a sub-cent calibration run | — |
| **[010b](010b-partial-run-threshold.md)** | *Decision:* the partial-run threshold | 010a |
| **[010c](010c-panel-test-pipeline.md)** | The pipeline: target description in, verdict out | — |
| **[010d](010d-adaptive-stopping.md)** | Adaptive stopping — the chunked loop | 010c |
| **[010e](010e-per-vote-cache.md)** | Per-vote cache: exact replay and resume | 010c |
| **[010f](010f-budget-guard.md)** | Budget guard: pre-flight, 402 stop, read timeout | 010a, 010e |

**010a runs first** (signed off 2026-07-27), even though it is instrumentation rather than
visible progress. It is the only child whose information *expires*: a run that finishes
without usage logging is a run whose cost is gone, and 010b and 010f are both guessing until
it lands. The one hard ordering constraint across the whole branch is that **no real 200-vote
run may happen before 010a**.

This ticket closes when every child does.

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

## Where the amendments went

The rulings this ticket accumulated are now in the child that owns each, rather than in one
list nobody reads to the end:

- **Panel size** — n=200 default, the 100–300 bound, and why `select_panel` accepts any size
  ≥ 1 → [010c](010c-panel-test-pipeline.md).
- **The panel thins twice** — retrieval matching fewer *and* votes failing, which compound, so
  the verdict rests on `len(votes.records)` → counts emitted by
  [010c](010c-panel-test-pipeline.md), the threshold decided by
  [010b](010b-partial-run-threshold.md).
- **Token instrumentation** and why it cannot wait → [010a](010a-vote-usage-instrumentation.md).
- **Read timeout** (the SDK's 600s default) and the **pre-flight budget check**, both deferred
  here from [008](008-build-panel-evaluation.md) → [010f](010f-budget-guard.md).
- **Per-vote caching**, and that it is the only exact-replay mechanism left now that
  `temperature≈0` is unavailable → [010e](010e-per-vote-cache.md).
