---
title: "Menu-mode interests: weighted banks, code-owned draw, LLM as fit-filter"
labels: [wayfinder:task]
parent: 006-build-persona-pool
blocked_by: [006f-persistence]
assignee: null
status: rejected
---

## Rejected (2026-07-25) — superseded by [006i](006i-leisure-profiles.md)

Menu-mode would have worked mechanically (slice 1 shipped: weighted draw,
openness wildcard, count draw — all tested), but making it *correct* required
~430 per-entry weights and an interest-count distribution that no survey
measures. There is no obtainable ground truth for an open hobby vocabulary per
country, so the design's core input would have stayed invented — and adding a
country would have meant re-inventing it. 006i replaces generated interests
with surveyed time-use categories, where the ground truth exists and is
re-pullable. Slice 1's code is repurposed there (weighted draw over ~10 sourced
categories); slices 2-3 were never built.

## Goal

Replace suggestion-strength example anchoring with **menu-mode**: code samples each
persona's candidate interests from a popularity-weighted country bank; the LLM only
filters the menu for demographic + Big Five fit. Pool interest distribution becomes
a property we compute, not a behavior we prompt for.

Design basis: [006d](006d-interests-synthesis.md), the merged example-bank work
(PR #29), and the measured failure below.

## Why (measured, 2026-07-25 dev run)

The example-bank design (rotating per-slot prompt examples) failed its own audit:

- **Echo rate 0.03, in-bank rate 0.26** — the model ignores suggestion-strength
  anchors and paraphrases the few it takes.
- **Quirk attractor intact**: `homebrewing` in ~10% of personas (real rate <1%),
  `bonsai cultivation` ~6% (target <1%); zero mainstream hobbies (TV, video
  games, gym) in the top-20.
- Dispersion audit (1.00) and plausibility judge (1.00) both missed it; the
  **top-20 frequency table** is the instrument that caught it.

Pre-agreed escalation rule (PR #29 grill): weak echo or persistent attractor →
invert ownership. Both fired.

## Resolved (2026-07-25 grill) — design

- **D1 — Ownership: code deals, model filters; closed vocabulary.** Pool ⊆ bank.
  Every distribution has a code owner; the model owns only per-persona fit —
  free slots were re-measured as the attractor's entry point, so there are none.
- **D2 — Weights, hierarchical: `weight(entry) = category envelope × within-category
  split`.** Bank schema becomes `hobby,weight` (replacing `tier`). Envelopes from
  public time-use data (OECD API — country-scalable; adding a country = API pull +
  drafted bank + human skim). Splits survey-anchored where free (JP 社会生活基本調査
  is entry-level; US ATUS partial), drafted *ordering* elsewhere — a wrong split
  inside a correct envelope is a small error; wrong envelopes were the disaster.
  Provenance doc: `docs/research/leisure-time-use-sources.md` (research in flight);
  every CSV weight cites it.
- **D3 — The deal (per slot, deterministic):** 7 cards ∝ weight, **plus one
  rare-tail wildcard** at probability 0.10 / 0.25 / 0.50 by openness bucket
  (rare tail = bottom quartile of weight mass). Openness→variety is the one
  Big Five→distribution link, in code, literature-backed. Expected single tail
  entry ≪1% of pool (the bonsai criterion) by arithmetic.
- **D4 — Count is a distribution too:** `n` sampled per slot,
  `2: 25%, 3: 35%, 4: 25%, 5: 15%` (drafted; calibratable). Floor 2 in v1 —
  zero/one-hobby personas deferred (QC reconstruction, stereotype audit, and
  targeting all assume ≥1 interest; see v2 items).
- **D5 — Editor prompt + gate:** prompt = persona description + menu + "keep
  exactly n that best fit this person, **verbatim**." Gate: count == n, every
  interest ∈ dealt menu (casefolded). Verbatim instruction is load-bearing (the
  model paraphrases; paraphrases would churn retries). Bank wording becomes pool
  wording — standardizes phrasing as a side effect. No ordering (schema stores
  none). Existing retry path unchanged (3 attempts → skip + `failed` → resume).
- **D6 — Measurement loop:** echo audit reinterpreted — in-bank rate should be
  ~1.0 (gate-enforced); **top-20 realized frequency vs intended weights** becomes
  the calibration dial: adjust CSV, truncate, re-seed, re-measure.

## Slices (one PR each, small)

1. **Weights + deal**: bank schema `hobby,weight`, weighted loader, deal sampler
   (7 + wildcard, count draw) off the existing slot RNG. Pure logic, TDD.
2. **Editor prompt + gate**: menu prompt, membership/count validation, wire into
   `synthesize_interests`/assembly. TDD.
3. **Weights content + calibration**: fill CSVs from the research doc (envelope ×
   split), truncate + dev seed, echo-audit vs targets, adjust.

## Deferred to v2 (recorded, not lost)

- Zero/one-hobby personas (needs qc.py reconstruction fix, audit join, targeting
  semantics).
- Age/gender envelope multipliers (data exists — HETUS/e-Stat cross-tabs) — only
  if the audit shows the model's fit-filtering under-concentrates.
- Big Five modulating count `n` (extraversion/openness) — same trigger.
- Numeric split calibration for the long tail (head-only precision is v1's bar).
