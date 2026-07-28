# The first full-scale run: cost, latency, the cache, and the stop — all measured at once

**Date:** 2026-07-28 · **Harness:** `backend/experiments/panel_run.py` (drives
`run_panel_test`, the exact path `/evaluate` ships — chunking, adaptive stopping, the
vote cache, and per-chunk commits under real 25-way concurrency) · **Pool:** the seeded
200 (66 DE / 67 JP / 67 US), targeted with a description naming all three countries so
the whole pool matches · **Raw rows:** `backend/experiments/out/panel_run.jsonl`
(gitignored, like every experiment artifact — this document is the durable record).

Three runs, ~$0.17 total:

| run | headlines | votes | cost | stop | tally |
|---|---|---|---|---|---|
| `fixed-200` | identical pair (a true tie by construction) | 200/200 | $0.1373 | none — ran to cap | 96 / 104 |
| `replay` | same request again | 200/200 | **$0.0000** | none | 96 / 104, byte-identical |
| `stopped` | clear winner vs filler | 50/200 | $0.0363 | `decisive` at the 2-chunk floor | 36 / 14 |

The identical-headline trick is what bought the full-length reading: the tie stop is
first reachable at the cap (adaptive-stopping.md), so a constructed tie cannot end
early, and the run yields the complete latency distribution the read timeout needs.

## Cost at scale: $0.00069/vote, superseding 010a's $0.000536

010a's own closing note said its 10-vote figures would be superseded by the first full
run. They were, upward: **$0.000687/vote** on the tied pair (200 votes) and
**$0.000726/vote** on the decisive pair (50 votes) — output ran ~310 tokens/vote against
010a's 234, reasoning still the dominant term. A 200-vote test is therefore **~$0.14**,
and the $10 cap is **~70 fixed-length tests** (more in practice: a decisive pair stopped
at 50 votes for $0.036). The `PROFILES` table's comment carries the corrected figure.

## Latency: the read timeout finally has a source

Over the 250 timed votes (nearest-rank):

```
p50 6.5s   p95 11.1s   p99 14.0s   slowest 18.9s
```

**The vote read timeout is set to 60s** (`VOTE_READ_TIMEOUT_SECONDS`, app/llm.py):
~3× the slowest vote ever observed and ~4× the p99, so no valid-but-slow reasoning
response observed to date comes anywhere near it, while a hung request now costs a
worker one minute instead of the SDK default's ten. The margin is deliberately wide —
cutting off a valid vote thins the panel, and a hang costs latency, not money.

## The cache, proven at scale

The replay run answered 200 votes with **one** HTTP request (the translation): zero
model calls, $0, ~19s wall against the paid run's minutes, tally and verdict
byte-identical. That is 010e's exact-replay promise observed, not argued — including
the per-chunk commits under real concurrency.

## The stop, proven live

The decisive pair stopped at 50 votes — the earliest the two-confirmation rule allows —
with P(shipping B is the mistake) = 0.984 and the early-stop notice reading exactly as
designed ("the rest went unasked … an answer, not a shortfall"). 75% of the cap
unspent. The tied pair, conversely, ran to 200 with P(practical tie) = 0.919: under the
0.95 bar, exactly as the simulation said equivalence would be — cap-priced.

## Two behavioural findings the runs threw in for free

- **Position bias saturates on identical options.** With the two headlines the same
  string, the model picked the first-shown option in **200 of 200** votes (the decisive
  pair sat at the familiar 0.68 ≈ 014's 0.66). Content differences dilute the position
  pull; remove content and position is all that remains. No action — but a reminder that
  the counterbalancing is not a nicety.
- **A fixed order seed repeats its surplus every chunk.** The tied run's 96/104 is not
  noise: chunks of 25 split 12/13, the surplus side is chosen by `ORDER_SEED` — which is
  the same for every chunk — so all 8 chunks tilted the same way, a systematic
  ⌈200/25⌉ = 8-vote lean made visible by the saturated position bias. At the normal 0.66
  rate the tilt is ~2.6 votes per 200 — real but small, about a third of one
  percentage point. Recorded rather than fixed: seeding per chunk index would remove
  it, and that decision belongs to a ticket, not a footnote.

## Reliability

250 paid votes, 0 failures, 0 parse errors. The 402 path remains unexercised (credit
was never near exhaustion); its handling is tested with doubles instead.
