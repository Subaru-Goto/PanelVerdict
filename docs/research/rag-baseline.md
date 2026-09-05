# The analyst's RAG, measured: a first Ragas baseline

**Date:** 2026-09-05 · **Harness:** `backend/experiments/rag_eval.py` over
`backend/experiments/rag_cases.json` (110/#238) · **Settings:** analyst and judge both
`openai/gpt-5.6-luna` (`settings.analyst_model`, `settings.judge_model`), analyst at
`reasoning_effort="low"` as shipped; Ragas 0.4.3 `Faithfulness`, `ContextPrecision`
(with reference), `ContextRecall`, judge through `llm_factory` on an OpenRouter client,
layered on with `uv run --with-requirements evals/requirements.txt` — never in the lock,
whose production resolution it would downgrade;
fixture report `experiments.corpus_check.sample_result()` (an undecided 22–28 of 50);
the local database seeded with the 15-chunk corpus · **Runs:**
`backend/experiments/out/rag-eval-sample-10.{jsonl,usage.json}` and
`rag-eval-baseline-30.{jsonl,usage.json}` (gitignored, as 091's are).

## The question

018 built the corpus to overwrite the model's most probable — and wrong — answers about
this product: that traits were collected from people, that openness tracks nationality,
that a lean inside the band is a result. `test_corpus_retrieval.py` proves the mechanics
(a query returns chunks, ranked). Nothing measured whether the *answer* is grounded in
them. Faithfulness is that measure; context precision and recall say whether a bad
answer was a retrieval miss or a grounding miss.

## Method

Each case is one real `stream_analyst` turn on a fresh thread — the same path a reader
gets — asked about the fixture report. What the turn retrieved is read back off its
checkpointed transcript (the corpus tool's JSON result), so what Ragas judges is what
the analyst actually saw; a turn that never called the corpus tool is recorded as
"no retrieval" and not scored. The reference for each case is a person's reading of the
named passage (decision Q2: a generated set would grade the model against its own
reading of the source). Thirty cases, two per chunk — one in the reader's jargon, one in
their own words.

**Cost is measured, not estimated.** The analyst's own `analyst usage` log line is
summed; every judge call's `usage` is read off the HTTP response. Dollars are derived at
the prices [thread-replay-cost.md](thread-replay-cost.md) §3 quotes from the OpenRouter
catalogue (2026-09-02): $0.25/M uncached input, $0.02/M cached input, $1.20/M output;
the judge's prompts sit under the 1,024-token cache minimum and are priced at $0.20/M.

## The 10-case sample, and what it changed

| | |
|---|---|
| cases scored / never reached the corpus | 8 / 2 |
| faithfulness · precision · recall (mean) | 0.969 · 0.937 · 1.000 |
| reference passage retrieved | 7 / 8 |
| analyst: 19 calls, 38,563 in (81% cached), 1,225 out | $0.0039 |
| judge: 43 calls, 59,170 in, 10,941 out (~1,376 / ~254 a call) | $0.0250 |
| **total** | **$0.0288 — $0.0029 a case** |

The two unrouted cases were the finding: *"Is this page going to tell me my numbers?"*
and *"Is the panel representative?"* were read as questions about **this test** and sent
to the report's tools — which is what 025's two-kinds rule tells the analyst to do. They
measured routing, not grounding. **Six questions were reworded** to ask about the method
in general (`v-title-1`, `v-answers-2`, `v-stop-1`, `p-invented-2`, `p-demo-2`,
`p-limit-2`); the analyst's wording was not touched. An instrument correction after a
sample, which is what the sample was for.

## The baseline: 30 cases

| | |
|---|---|
| cases scored / never reached the corpus | 29 / 1 (`v-nocall-2`) |
| **faithfulness** (mean over 29) | **0.835** |
| **context precision** | **0.862** |
| **context recall** | **0.879** |
| reference passage retrieved | **24 / 29** |
| analyst: 60 calls, 88% of input cached | $0.0113 |
| judge: 150 calls, ~1,385 in / ~258 out a call | $0.0880 |
| **total** | **$0.0993 — $0.0033 a case** |

Below 1.0 on any metric (counting a score under 0.999 — Ragas returns 0.9999… for a perfect precision): 15 of 29 cases on faithfulness, 5 on precision, 4 on recall.
Three cases score zero on both retrieval metrics (`p-title-1`, `p-title-2`, `p-limit-1`).

## Hand review of every imperfect case

Decision Q3: a judged metric's failures are read by a person before they mean anything.
091 found judge errors among its own; so did this.

**Real retrieval misses — the finding.**

- **`p-limit-1` — "What has the panel actually been validated on?" did not retrieve
  "What this panel cannot tell you"**, the passage written to answer exactly that, and the
  single most important honesty passage in the corpus. It retrieved "What the panel is
  actually measuring" instead. The reply was still substantially right (see the artefact
  below), but the retriever missed its own target. Filed as
  [129/#313](https://github.com/Subaru-Goto/PanelVerdict/issues/313).
- `p-title-1` retrieved an unrelated verdict section, and the analyst answered honestly
  that the guide "does not specify" — correct behaviour on a wrong passage.
- `p-traits-1` ("What is openness?") retrieved the trait-*level* passage, not the trait
  definitions; recall 0.5, the reply correct from the level passage's own words.

**Judge strictness on correct answers.** `v-measure-1` scored 0.5 with the right passage
retrieved and a correct reply — the judge held "display order balanced" unsupported when
the passage says "half of them see your first option first". `v-measure-2` (0.5) and
`p-cond-1` (0.57) are the same shape: paraphrase read as invention. These are the
judge's variance, and the reason the bar is a baseline rather than a threshold.

**Instrument artefacts, recorded so the next run does not re-discover them.**

1. **The analyst has two grounded sources and Ragas sees one.** Its system prompt
   carries caveats of its own — "unvalidated where two variants say the same thing
   differently" among them — so a true, prompt-grounded sentence in a reply is scored
   unfaithful against the retrieved passages. `p-limit-1`'s 0.67 is partly this.
2. **Title-chunk cases punish the right retrieval.** Both documents' first chunk is an
   intro paragraph whose content every section also covers; a question written against
   it is answered better by the specific section, which precision and recall against the
   intro then score as a miss (`p-title-1`, `p-title-2`). Two of the five reference misses
   are this. The cases stay — dropping them after the run would be tuning — but the
   reading is recorded.

## What this baseline is, and is not

- **It is the bar.** A later run at the same wording scoring below it is a finding to
  hand-review, then a ticket or a documented reason (Q3). It is not a threshold; a
  threshold would be an unsourced constant, and the judge's variance above is why.
- **Retrieval is the weaker half.** 24/29 reference hits, three outright misses. Grounding
  as judged is 0.835 with two known artefacts pulling it down; a reader of the imperfect
  replies finds one honest decline and no invented number.
- **106's tripwire owes a rerun** when `analyst_model` or `judge_model` moves; this record
  is the one it names for the RAG.
- **Not done:** a tolerance for run-to-run noise (needs a second run at the same wording);
  DeepEval's own RAG metrics as a cross-check on the judge; a case set for the report's
  *figures* questions (those go to `analyze_results`, not the corpus, by design).
