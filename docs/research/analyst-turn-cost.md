# What an analyst turn costs — measured (2026-09-02)

Ticket [070/#161](https://github.com/Subaru-Goto/PanelVerdict/issues/161). Until
this measurement, `USD_PER_TURN` was a stand-in equal to one vote's price, and
the ticket's finding held: the analyst's cost had never been measured.

## Method

Six real turns against `openai/gpt-5.6-luna` (the shipped `analyst_model`),
driven through `stream_analyst` itself — real system prompt, real tool schemas,
real tools over a seeded database — so the measured turn is the turn production
runs, not an approximation of one. The payload was a real early-stopped run:
the demo capture's 50 votes with their original reasons (~20 KB serialized).
Three questions per arm, one thread per arm:

1. a figures question that must call `analyze_results`,
2. a corpus question ("what does credible mass mean") that must hit the RAG
   explainer,
3. a one-sentence follow-up — the cheap-turn shape.

Token counts were read from the `analyst usage` log line this ticket added
(the `message-finish` usage the provider reports under `stream_usage=True`).
Dollar figures are derived from those tokens at OpenRouter's list prices for
`gpt-5.6-luna`, quoted 2026-09-02: **$0.20/M input, $1.20/M output (reasoning
bills as output, inside `output_tokens`), $0.02/M cached input.** Streamed
responses carry no provider `cost` field (langchain drops it on the streaming
path), so derivation from tokens × dated price is the instrument here; the
same session's OpenRouter activity view is the cross-check, as in the
per-vote measurement.

> **Correction (2026-09-02, [104/#223](https://github.com/Subaru-Goto/PanelVerdict/issues/223)):**
> on the GPT-5.6 family, uncached prompt tokens ahead of the cache breakpoint are
> *cache writes* billed at 1.25× input — $0.25/M, not $0.20/M (OpenRouter
> catalogue, read 2026-09-02). Re-priced, the worst low-effort turn moves from
> $0.000429 to ~$0.00045; `USD_PER_TURN` still holds. Derivation and sources in
> [`thread-replay-cost.md`](thread-replay-cost.md) §3.

## Results

| arm | turn | model calls | input (cached) | output (reasoning) | derived USD |
|---|---|---|---|---|---|
| default | figures | 2 | 2,810 (2,412) | 544 (332) | $0.000781 |
| default | corpus | 3 | 7,063 (5,688) | 479 (305) | $0.000964 |
| default | follow-up | 1 | 3,063 (2,964) | 57 (0) | $0.000147 |
| low | figures | 2 | 2,817 (2,412) | 250 (19) | $0.000429 |
| low | corpus | 2 | 4,138 (3,374) | 127 (10) | $0.000373 |
| low | follow-up | 1 | 2,471 (2,363) | 49 (0) | $0.000128 |

- **Default effort: ~$0.00063/turn average, $0.00096 worst.** The old
  stand-in ($0.0002/turn) *undercharged* the pool by 3–5× — the one direction
  a ceiling must not err.
- **`reasoning_effort=low`: ~$0.00031/turn, −51%** — the same 2× the panel
  measurement found, now measured on the analyst itself.
- **Cache hits are real here** (unlike votes, whose prompts are below the
  provider's cache minimum): 80–96% of input tokens read from cache within a
  thread, at a tenth of the input price.

## The obedience check (the one real risk, checked live)

The two-kinds rule — figures never from memory — is unassertable by the suite
(025: doubles route the tools). Checked live on both arms: the figures
question called `analyze_results` at default **and** at low effort, every
cited number matched the tool's recomputation (42–8, 84%/16%), and the corpus
question retrieved rather than improvised. A 3-question live probe is
evidence of function, not a calibration study; the check should be repeated
if `analyst_model` ever changes, per the same rule 106/#226 pins for the
guard.

## Decisions taken (author, 2026-09-02)

- **`reasoning_effort="low"` is adopted for the analyst** (in
  `analyst_chat_model`): half the bill, no invalidation cost — no published
  number was taken at analyst-default effort — and the live obedience check
  passed.
- **`USD_PER_TURN = 0.0005`**: the worst measured low-effort turn ($0.00043)
  plus margin, erring toward overcharging the pool, as `USD_PER_VOTE` does.
- The author's 2026-08-23 expectation ("Luna >50% cheaper than mini") was
  already confirmed for the panel; for reference, list prices 2026-09-02:
  Luna $0.20/$1.20 per M vs mini $0.25/$2.00 per M.
