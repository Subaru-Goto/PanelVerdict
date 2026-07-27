---
title: "Build the report UI (Next.js)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [009-build-bayesian-layer, 010-assemble-orchestrator-graph]
assignee: null
status: open
---

## Goal

The report dashboard:

- vote split, posterior plot (P(B>A), **preference share** + CrI — see the amendment), ROPE verdict,
- ~~segment breakdown (target vs. control group)~~ — dropped 2026-07-26, see below,
- reason list (reason *clustering* is fog — see map Notes),
- **live batch-streaming progress** ("87/200 personas voted…") over SSE,
- **all model output rendered as plain text** (exfiltration-markup defense — never `dangerouslySetInnerHTML` on model output).

## Amended 2026-07-26 — never label the headline number "lift"

The panel is a **paired comparison**: one group sees both variants and each persona
makes a forced binary choice ([009](009-build-bayesian-layer.md) amendment). Two
things follow for this UI.

**The segment breakdown goes.** There is no control arm to break down against — each
persona is its own control, so there was never a second group
([007](007-build-targeting-query-translation.md) amendment). If audience comparison is
wanted later it is segment vs. segment, a deliberate feature, not a panel subdivision.

**The headline number is a preference share, and the copy has to say so.** `E[p] − 0.5`
in preference-share points is *not* a predicted click-through difference. Real users
mostly see one headline and never make the comparison the panel made, so a 70/30
forced preference can sit on top of a small click difference. A marketer who reads
"70% lift" as CTR will forecast revenue off it — the one number here capable of
producing a confidently wrong business decision.

So: label it "preference share" or "share preferring B", never a bare "lift" or "%
uplift", and carry a plain-language line near it saying the panel chose *between* the
two while real audiences usually see only one. Whether panel preference predicts field
behaviour at all is the Upworthy study, out of scope on the map — which is precisely
why the UI must not imply it.

## Amended 2026-07-27 — the panel is unvalidated on same-meaning variants

[015](015-task-framing-sensitivity.md) ran the panel on headline pairs that mean the
same thing and differ on one published lever — the regime a customer's A/B test
actually lives in. Two results change what this UI may claim.

**The panel's strongest preference falls on a lever that does nothing to real
readers.** Second-person pronouns were a rejected hypothesis in Gligorić et al.'s
24,333-pair field study; the panel picked the "you" variant 0.82–0.94 of the time
under every framing, while the three levers that *do* move real clicks landed at
chance. So on same-meaning copy the panel produces confident preferences that are
not evidence about readers.

**The number also depends on the question asked.** Framing flips 38–43% of matched
votes against a ~0.21 noise floor. The `openness` gradient — an opposed pair — was
identical across framings, so this bites specifically where the two variants are
close in meaning.

Both point the same way for the report: **when the two variants mean roughly the
same thing, the preference share must not be presented as a prediction about
readers.** That is a stronger statement than the "preference share, never lift"
naming rule above, which addresses the *unit*; this addresses whether the number
carries information at all in that regime. A caveat with a measurement behind it,
not a hedge.

Open question for this ticket, not decided here: whether that caveat is always-on
copy or triggered by an automatic same-meaning check on the submitted variants. The
second is better and needs a mechanism that does not exist yet.
