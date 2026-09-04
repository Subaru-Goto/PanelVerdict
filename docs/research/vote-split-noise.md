# The vote split's false findings: how often a subgroup is called with nothing behind it

**Date:** 2026-09-04 · **Harness:** `backend/experiments/split_noise.py` (no model
calls; panels drawn the way the sampler draws them, trait levels through the
production `bucketize` of standard-normal scores, and read by the production
`splits_by_variant`) · **Settings:** panel 200 (the prod profile size), 300 reports
per arm, seeds 0–299, bar = `credible_mass` 0.95, band ±7 — all imported from the
app rather than restated.

## The question

`splits_by_variant` (041/#139) reads every level of every dimension at one bar. That
reuse is the design: a subgroup is a smaller panel, so it needs no statistics of its
own, and `decisive` in a cell means what `decisive` means on the report. But an
untargeted prod panel produces **44 readings**, and 44 simultaneous tests at a 95%
bar will clear some of them with nothing behind them. Nothing in the ticket had
costed that.

## Arm 1 — no effect at all

Every vote a coin flip, independent of the voter, so **every** `decisive` row is
spurious by construction.

| | |
|---|---|
| readings per report | 44 |
| spurious decisive rows | mean **0.52**, max 5, 156 over 300 reports |
| reports carrying at least one | **116/300 = 39%** |
| of those 156 rows, marked `isolated` | **153 = 98%** |

**Two reports in five would hand the analyst a finding that is not there** — and it
would be stated as a finding, because that is what the label licenses.

## Arm 2 — one real effect

Older voters prefer B; no trait effect planted. Conscientiousness carries a lift with
age, reproducing what the sampler already builds in
([persona-seed-data.md](persona-seed-data.md)), so this arm also exhibits the
confound the payload warns about.

| | |
|---|---|
| reports that found the effect | **300/300** |
| `age_band` rows called decisive | 1,020 |
| of those, marked `isolated` | **197 = 19%** |

## What was decided, and what was rejected

**Adopted: mark the isolated rows, keep every row.** A decisive row that no
neighbouring level agrees with is annotated; one whose neighbour leans the same way
is not. Across the two arms that flag lands on **98% of noise rows and 19% of true
ones** — the only instrument here that tells them apart. Ordinal dimensions only:
country and gender have no adjacency to read, and get no claim either way.

**Rejected: raise the per-cell bar.** It works on the noise, measured over arm 1:

| per-cell bar | reports with ≥1 decisive row |
|---|---|
| 0.950 | 38.7% |
| 0.970 | 19.7% |
| 0.980 | 14.7% |
| **0.990** | **4.0%** |
| 0.995 | 1.7% |
| 0.999 | 0.0% |

0.99 brings the family-wise rate to 4%, and it is a threshold a simulation could
source. It was rejected on two grounds. It cuts true rows with the false ones and
cannot see which is which — in one arm-2 panel it removed `age_band 80+` (p=0.9590,
a real row) and `conscientiousness low` (p=0.9651, a confounded one) together, keeping
only `70-79`. And it breaks the property that made reusing `verdict.py` correct:
cells would no longer be judged at the bar the report itself uses.

**Also adopted: say the rate.** `VoteSplits.reading_note` states how many readings
the block took — computed, since a targeted panel takes fewer — and that a lone
decisive row turns up in about two of five panels with no effect. Agreement is
evidence, not proof, so the rate stays on the record rather than being corrected away.

## The three-band collapse, costed

The ticket asks for this rather than assuming it: *"Collapsing to three bands (low /
medium / high) is the obvious mitigation and should be costed against losing the
very_high row that a targeting question most often asks about."* Folding the extremes
inward (`very_low`+`low` → `low`, `high`+`very_high` → `high`) over the same panels,
trait dimensions only:

| | five bands | three bands |
|---|---|---|
| noise arm: reports with a decisive trait row | 83/300 (28%) | **22/300 (7.3%)** |
| effect arm: decisive trait rows | 766 | 577 |
| of those, in `very_low` / `very_high` | **221** | 0 — unreportable |

**Five bands kept.** The collapse is a genuine ~4x noise win and keeps three quarters
of the findings — merging makes cells fatter, so it gains some in the middle while
losing the extremes outright. But 29% of the five-band findings sit in the two rows
the ticket names, and the isolation flag already removes 98% of noise rows without
blinding anything. Buying most of the same reduction by deleting the rows a targeting
question asks about is the worse trade.

## The block's size

Measured by the same harness, `tiktoken` `o200k_base`, on an untargeted panel of 200
(44 rows): **10,518 characters = 3,024 tokens.** Two reductions are already in it,
each measured the same way on 2026-09-04: shares and interval bounds rounded to three
places, and the per-cell warning shortened with its standing half moved to
`reading_note` once. Before those the block was **4,511 tokens**, of which 1,760 was
the long warning repeated 44 times and 440 the full-precision interval values.

Against `docs/research/analyst-turn-cost.md` (80–96% of a thread's input read from
cache, $0.25/M cache write, $0.02/M cache read), 3,024 tokens is **~$0.00076 on a
thread's first `analyze_results` call** and **~$0.00006 per turn after**. That is
above `USD_PER_TURN = 0.0005`, so a first splits-reading turn bills more than it
charges; `app/config.py` records the widened gap.

## Limits

- **The 39% is at panel 200 and 44 readings.** A targeted panel reads fewer cells and
  carries a lower rate; the note's count moves with it, the quoted 39% does not.
- **Arm 2's effect is one shape, and a strong one.** B's share rises linearly from
  0.30 at age 25 and below to 0.85 at 70 and above (`_YOUNGEST_PREFERS_B`,
  `_AGE_SWING`, `_SWING_FROM`, `_SWING_TO` in the harness) — chosen, not measured, so
  that the flag's cost on a true finding is measurable at all. It is not a claim about
  how real readers behave, and "300/300 found the effect" should be read as "at this
  effect size", not as a power calculation. A weaker effect would be found less often;
  a non-monotone one — a preference peaking in a middle band — would be flagged
  `isolated` more often than 19%, and the flag would be wrong about it. Nothing here
  measures either case.
- **Adjacency is not inference.** The flag says neighbours disagree, not that the row
  is false. The between-group contrast that would actually test a trait's effect needs
  a ROPE on the difference scale, which is a separate domain judgement (041/#139
  records it as the follow-up).
