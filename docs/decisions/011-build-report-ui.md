---
title: "Build the report UI (Next.js)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [009-build-bayesian-layer, 010-assemble-orchestrator-graph]
assignee: Subaru-Goto
status: closed
---

**Delivered 2026-07-28** in two PRs as decided: #63 (011a, wire fix + typed
response + vitest suite) and #64 (011b, the decided dashboard + annotated
posterior). Post-merge follow-ups ticketed: [022](022-rename-worth-acting-on-field.md)
(wire field rename born from the tile-copy iteration),
[023](023-vote-feed-voter-details.md) (voter details in the reasons feed),
[021](https://github.com/Subaru-Goto/PanelVerdict/issues/126) (progress UX, v2).

## Goal

The report dashboard:

- vote split, posterior plot (P(B>A), **preference share** + CrI — see the amendment), the band
  as probabilities plus the panel's resolution ([020](020-probability-not-label.md) retired the
  three-way label; the placeholder UI derives the headline, this ticket designs it),
- ~~segment breakdown (target vs. control group)~~ — dropped 2026-07-26, see below,
- reason list (reason *clustering* is fog — see map Notes),
- ~~**live batch-streaming progress** ("87/200 personas voted…") over SSE~~ — moved
  to [021](https://github.com/Subaru-Goto/PanelVerdict/issues/126) (v2) with the replay animation, 2026-07-28,
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

## Amended 2026-07-27 ([007](007-build-targeting-query-translation.md)) — the report must read `coverage`, not just `countries`

`TargetQuery.coverage` is `requested` | `approximated` | `unmatched`, and **a report
that shows the country list alone will present a fallback as a deliberate choice.** A
target for Nigeria resolves to the United States, Japan and Germany — byte-identical to
a target that named no country at all — so the panel cannot be distinguished from a
genuine global one by its members.

- `unmatched` → the panel carries **no geographic targeting**. Say so where the verdict
  is, not in a footnote; it is a read on the wording only.
- `approximated` → a stand-in region was used. The warning already names it.
- `requested` → nothing to flag.

`PanelSelection.notices` carries the prose for all of this, split by severity:
`warning` means the panel is not what was asked for, `reading` means it is and here is
the interpretation. Both belong in the report — the readings are how a customer catches
a mis-read target, e.g. "cautious" taken as conscientiousness rather than neuroticism.
Write from [`docs/reading-the-posterior.md`](../reading-the-posterior.md) for the
verdict numbers themselves.

**Amended 2026-07-27 ([017](017-representative-sampling.md)):** the trait reading is
available as **data**, not only as notice prose. `TargetQuery.traits` is a tuple of
`TraitRequest` — `trait`, `level`, and the `source_phrase` it was read from — so a chip
reading *"conscientiousness: high — from "cautious""* needs no string parsing. Show the
source phrase, not just the trait: it is the only part a customer can check.

## Design decided 2026-07-28 — prototype verdict (user)

Three structurally different variants were prototyped on the live page against mock
data from the real stopped run; the user picked a hybrid:

- **Layout: the "evidence dashboard"** (prototype variant B). Verdict as one compact
  chip line — not a banner — over a grid of stat tiles (share + CrI, both
  "shipping X is the mistake" probabilities — renamed "Chance X is preferred /
  by a gap big enough to matter" 2026-07-28 (user: no blame, no win-lose
  framing; note the wire fields cross over: shipping_b feeds A's tile) —,
  tie + resolution), a panel-composition
  card (country chips, trait chips showing the `source_phrase`, coverage badge when
  not `requested`, notices listed inside with warnings dotted red), and the reasons
  as an always-visible feed.
- **The posterior: variant A's annotated distribution block**, dropped into that
  layout in place of B's compact strip. The full construction is the decision: a
  caption saying what the curve *is* ("how likely each possible split of the whole
  audience is, given those N votes"); axis ends labelled with the actual headline
  text ("← everyone prefers A: '…'"), because the first reader instinctively read
  the winner's share into an axis that shows B's — the labels exist for that flip;
  a legend naming every mark with its number (dashed mean line, CrI bar, gray
  too-small-to-matter band); area filled and curve stroked as separate paths (a
  stroked closed area draws its baseline as a fake datum — caught by the user).
- **The density is computed client-side from the tally** — Beta(b+1, a+1), log-space,
  ~30 lines of hand-rolled SVG. No chart library (minimal-dependencies rule; nothing
  a library adds is needed).
- **Principle, learned the empirical way** (three consecutive "what is this line?"
  questions): every visible mark either carries an on-screen name and number, or it
  is deleted. Legends are not decoration in this product.

The prototype was deleted after capture; 011b re-implements the winner properly.

**Delivery decided 2026-07-28 (user):** two PRs — **011a** un-breaks the frontend
against the current backend (send `target_description`; type and minimally render
`counts`, `notices`, `stop_reason`, `query`), **011b** builds the decided report
design. The live batch-streaming line item and the replay animation both move to
[021](https://github.com/Subaru-Goto/PanelVerdict/issues/126) (v2); 011 ships with a plain pending state. The
same-meaning caveat is always-on copy (the automatic check has no mechanism yet).
