# What a rewrite and a check actually cost

**Run 2026-08-26.** `openai/gpt-5.6-luna` via OpenRouter, the generator's shipped
parameters (`TARGET_MAX_COMPLETION_TOKENS`, `TARGET_REASONING_EFFORT`, structured
output). **48 calls, every one with the provider's own `cost` reported** — this is the
bill, not a derivation. Ticket:
[094 · #200](https://github.com/Subaru-Goto/PanelVerdict/issues/200).

```
uv run python -m experiments.roleplay_cost --replicates 3 \
    --out experiments/out/roleplay-cost.jsonl
```

Eight ordinary audiences (the guard run's legitimate probes), each **rewritten** into a
panelist instruction and that instruction then **checked** — chained, because that is the
shipped sequence: every checked sentence starts life as a draft.

## The numbers

| call    | n  | prompt tokens | output tokens | reported cost (min / mean / max)    |
| ------- | -- | ------------- | ------------- | ----------------------------------- |
| rewrite | 24 | 706–709       | 25–35         | $0.000171 / $0.000173 / **$0.000184** |
| check   | 24 | 517–527       | 16–44         | $0.000123 / $0.000127 / **$0.000156** |

Reasoning tokens were 0 on every rewrite and near-0 on checks (max 26). Latency ran
0.8–1.9 s per call. Full rows: `experiments/out/roleplay-cost.jsonl`.

## What this settles

- **The per-caller bound on checks has its figure.** 094 decided checks get their own
  per-caller daily bound, sized from a measurement rather than a figure invented to fill
  the blank. `evaluate_checks_per_caller_per_day = 50` — twice the preview allowance,
  because iterating on the sentence is the product's core loop — has a worst case of
  50 × $0.000156 ≈ **$0.008 per caller per day**, a fifth of one panel
  (200 × USD_PER_VOTE = $0.04).
- **`USD_PER_ROLEPLAY` stays the ceiling it is.** The measured max is ~15% of the
  $0.0012 the pool is charged per call. Over-charging the pool is the safe direction —
  the cap closes early, never late — so the constant is not lowered here. Anyone
  re-deriving pool capacity can use these numbers.

## Honest limits

- Eight probes, one Tuesday, one model. An order of magnitude, not a distribution —
  the same caveat as `vote_cost`.
- All probes are short English audiences. `MAX_AUDIENCE_CHARS = 200` and
  `MAX_INSTRUCTION_CHARS = 400` bound how much longer real input can run; prompt cost
  scales with those, output cost does not obviously.
