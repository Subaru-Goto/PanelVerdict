---
title: "Targeting manipulation check: does a persona attribute move a vote?"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Goal

Falsify or support the hypothesis the whole product rests on — **that a persona
attribute steers a vote** — cheaply, before any further persona field is added.

Deliverables: a harness that collects the votes, the raw votes on disk, and
`docs/research/manipulation-check.md` stating what moved, what didn't, and by how
much.

## Why this is a map-level ticket

It has been referenced as a gate by four tickets and two research notes, and
owned by none of them:

- [001](001-decide-persona-schema-and-seed.md) — NFC / maximizing / CSII are added
  "only when the **targeting manipulation check** shows it moves votes".
- [003](003-decide-panel-model-and-provider.md) — the panel model pick is
  "confirmed-or-revised by the **manipulation check**", with GPT-5.6 Sol reserved
  as its fidelity benchmark rather than as a runtime model.
- [006b](006b-demographics-sampler.md) — education stays at 3 ISCED levels and
  splits finer "only if the manipulation check earns it".
- [006j](006j-persona-summary-embedding.md) D7 — re-derived the same question from
  scratch as an unbuilt slice 4, and D1b's five-level rendering rests on the
  untested assumption that a model votes differently given "extremely organized"
  versus "organized".
- `docs/research/persona-attributes-grounding.md` — trait-targeting "remains an
  unproven **hypothesis**", and this check exists "to falsify [it] cheaply, before
  any weight is placed on it".
- `docs/project-idea.md` — specifies the design (below) and orders it *before* the
  Upworthy study, on the grounds that if it fails there is no point spending
  budget on the full study.

Graduated out of 006j on 2026-07-26: 006j's deliverable is the summary column and
the text 007 retrieves on, which slices 1–3 shipped. This asks a different
question, its consumers are 001/003/006b, and keeping it inside 006j meant 006j
could not close.

## Design

**Target vs. control vs. opposite-segment**, per `docs/project-idea.md`:

> the evidence is that the target segment's preference *diverges from the control
> group* in the predicted direction, not merely that it picked the "expected"
> variant (which could just mean that variant is objectively better)

That confound is the reason a bare arm-comparison is not enough. A high-openness
panel choosing the novel headline proves nothing if every panel chooses it; the
opposite segment has to move the other way.

Three measurements, in this order — each one sizes the next:

1. **Noise floor.** Run the *same* persona on the *same* pair twice.
   `OpenRouterPanelLLM` runs gpt-5-mini at default temperature, so some personas
   flip with no manipulation at all. Everything downstream is a comparison against
   this number, and it also sets how many replicates the rest of the run needs —
   which is why it cannot be guessed in advance.
2. **Any effect.** Paired flip rate between arms over the same personas. Paired,
   because aggregate verdicts can be identical across two arms while every persona
   flipped: 100/100 both ways is consistent with "no effect" *and* with "200 flips,
   half each way". The statistic is the flip, not the margin.
3. **Directional effect — the gate.** Sweep one trait through all five levels with
   every other field fixed, against a pair loaded on that trait. Support looks like
   a monotone gradient in the predicted direction with the extremes on opposite
   sides of the control; failure looks like a flat line, or movement that ignores
   which end of the trait the persona is on.

**Constructed personas, not the pool.** Fixing every field but one is what makes
this causal rather than correlational, and it needs no database, no seeded pool
and no retrieval. Sizing is `5 levels × 5 traits × pairs × replicates`.

**The pairs are the weakest joint.** Two headlines that differ only in wording
("Save 20% today" / "Get 20% off now") will move nothing, and the resulting null
is indistinguishable from "personas don't work" — so each pair must be *loaded* on
one trait, and one **positive-control pair** must have an answer no persona should
dispute (a manipulation check on the manipulation check: if that pair isn't
lopsided, the model isn't reading the options and no other number in the run means
anything).

**Three levels vs. five, without confounding wording.** Render the 3-level arm by
collapsing `VERY_LOW → LOW` and `VERY_HIGH → HIGH` through the *same*
`_TRAIT_PHRASES` table, rather than restoring the pre-006j phrasing — otherwise
granularity and wording move together. Only personas with at least one extreme
trait render differently at all: `P(|z| > 1.5) = 0.134` per trait, so
`1 − 0.866⁵ ≈ 51%` of a sampled population. Constructed sweeps sidestep this;
it matters if the pool-level comparison is ever run.

**Collect and analyse are separate.** LLM calls cost money and don't reproduce, so
the collector writes raw rows (`arm, persona_id, pair_id, replicate, chosen,
reason`) to disk and the analysis is pure functions over those rows — re-runnable
for free, and the only part that needs tests.

## Scope

**In:** the constructed-persona trait sweep, all five traits, the noise floor, and
the write-up.

**Out (for now):** the 200-persona pool-level arm comparison
[006j](006j-persona-summary-embedding.md) D7 describes. It needs the pool seeded
and roughly an order of magnitude more calls, and the sweep answers the question
it was asked to answer more directly. Revisit only if the sweep is positive and
something needs measuring at panel scale.

## Consumers of the answer

- **Negative result** outranks every design decision on the map: the problem is the
  prompt, and no attribute set fixes it. 001, 003 and 006j D1b all reopen.
- **Positive result** unblocks the deferred fields in 001, confirms the 003 model
  pick against its benchmark, and settles whether 006j's five levels earn their
  churn over three.
