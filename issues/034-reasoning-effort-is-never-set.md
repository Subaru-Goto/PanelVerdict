---
title: "78% of the vote bill is reasoning nobody asked for: `reasoning_effort` is never set"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Measured, not suspected (2026-07-30)

One cold run of 25 fresh votes, the first readable since
[033](033-a-run-records-its-own-time.md) made the log visible:

```
wall=11.6s  votes=25  usage_reported=25
seconds_slowest=11.4s  seconds_total=149.0s
input=6576  output=7942  reasoning_tokens=6208  cost=$0.017528
```

**6,208 of 7,942 output tokens are reasoning — 78% of the output bill.** Spent
on a task that reads, in full: take one persona, read two headlines, pick one,
write a one-line reason.

Reasoning tokens bill at the output rate, so this is the largest single term in
the cost of every run the product does.

## Why it happens

`reasoning_effort` is fully plumbed and never used. `OpenRouterPanelLLM` accepts
it (`llm.py:220`), passes it to the model (`llm.py:273`), and the repo defines
its own closed vocabulary for it (`llm.py:32`) precisely because an
unrecognised value is silently ignored. The **only** caller that supplies one is
a test (`test_llm.py:273`). `get_panel_llm` (`main.py:54-59`) omits it, so every
production vote runs at gpt-5-mini's default effort.

The same is true of `get_translator` and `get_analyst`.

## Why this is an experiment, not a config change

Two things make a one-line edit the wrong move:

1. **Effort is inside the vote fingerprint** (`llm.py:236-242`), so changing it
   invalidates every cached vote in the ledger. That is correct behaviour — the
   ask changed — but it means the first run after the change pays for
   everything again.
2. **[015](015-task-framing-sensitivity.md) showed the verdict moves when the
   ask moves.** Effort is part of the ask. Nobody knows yet whether a
   lower-effort panel votes the same way, and "it got cheaper" is worthless if
   it also got different.

So it needs an arm-versus-arm comparison, not a commit. The infrastructure for
that already exists: `OrderSeed`/`PANEL_SEED` make the panel reproducible,
`presentation_orders` is seeded, and 015 is the precedent for running an
experimental arm as a separate instance rather than a per-call argument.

## What to measure

Same panel, same headlines, same seeds; `reasoning_effort` at default versus
`minimal` and `low`. For each arm record, from the log line this ticket's
sibling made readable:

- `cost` and `reasoning_tokens` — the saving, if any.
- `wall` and `seconds_slowest` — whether it is actually faster, or whether
  latency is dominated by something other than reasoning.
- **the tally and the verdict** — whether the panel decided the same thing.

The third is the one that decides it. A cheaper panel that votes differently is
not a saving, it is a different product.

## Baselines to compare against

- This ticket's run: 25 votes, `wall=11.6s`, `reasoning_tokens=6208`,
  `cost=$0.017528`, `seconds_slowest=11.4s`.
- `docs/research/first-full-scale-run.md`: p50 6.5s, p95 11.1s, p99 14.0s,
  slowest 18.9s over 250 timed votes, all at default effort.

## Related

- [033](033-a-run-records-its-own-time.md) — made the numbers above readable at
  all; this ticket is the first thing that instrumentation found.
- [015](015-task-framing-sensitivity.md) — why a change to the ask has to be
  measured against the verdict, not just the bill.
- [003](003-decide-panel-model-and-provider.md) — the model choice this would
  refine rather than overturn.
