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
