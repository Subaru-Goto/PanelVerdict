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
