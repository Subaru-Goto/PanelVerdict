---
title: "Build the Bayesian layer (flat Beta-Binomial + full report + adaptive stopping)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [002-decide-vote-schema]
assignee: null
status: open
---

## Goal

Pure-Python, deterministic — **no LLM** touches the statistics:

- flat binary Beta-Binomial (SciPy, conjugate — no sampler),
- full posterior report: **P(B>A)**, expected lift + 95% credible interval, **expected loss**, **ROPE** verdict (±3 pts → "practical tie — pick either or test a bolder variant"),
- **adaptive stopping**: update posterior per batch, stop at the P-threshold or the budget cap,
- neither-rate passed through descriptively (not modeled).