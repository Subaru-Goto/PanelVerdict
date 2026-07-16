---
title: "Decide the panel vote + structured-output schema"
labels: [wayfinder:grilling]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Question

Define the panel agent's structured output. The vote is a **preference/choice** between the two variants (or neither) — "click" is just the headline instantiation; for a design/image the same choice surfaces as "which would you pick".

- **Vote enum** — decision leans **3-way {A, B, neither}** (prefer A / prefer B / would choose neither) for forward-compat with the zero-inflated model (see map Notes + `docs/project-idea.md`). Confirm.
- **Reason** — a 1-line rationale field.
- **Order field** — which variant was shown first (needed to audit / correct position bias).

Confirm the v1 treatment: the neither-rate is **reported descriptively but NOT modeled** — the Beta-Binomial runs over those who chose A or B only. Lock the exact JSON/enum shape the panel and the Bayesian layer both depend on.

**Answer records:** the final structured-output schema.