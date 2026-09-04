# A similarity check against the chat pre-flight's misses (2026-09-03)

Ticket [125/#293](https://github.com/Subaru-Goto/PanelVerdict/issues/293). The
chat message is screened by Mistral's moderation classifier (120/#279,
122/#288). The red team (123/#289, `chat-red-team.md`) showed what it misses:
natural-sounding rewrites of an attack, 40 of 50, against 238 of 250 template
wrappers caught. The architecture behind Bedrock Guardrails' denied topics and
NeMo Guardrails' intent matching — embed the message, compare it with stored
attack phrases, flag above a threshold — promised a second signal with no model
to train and no service to host. The question was whether the misses sit near
the attacks we already know in embedding space, without ordinary questions
sitting there too.

**Answer: the plain threshold (Bedrock's shape) does not; the two-sided score
(NeMo's intent shape) clears the agreed gate on the letter — and what it
catches is the template leftovers, not the natural rewrites. Adoption is
deferred to [126/#297](https://github.com/Subaru-Goto/PanelVerdict/issues/297);
nothing changes in the product from this ticket.**

## Method

- **Embedder:** `openai/text-embedding-3-small` through OpenRouter, the repo's
  own `OpenRouterEmbedder` (`settings.embedding_model`), which the analyst
  already calls once per corpus search. $0.02 per million input tokens (OpenRouter
  model page, read 2026-09-03; OpenAI's list price is the same). 1536 dimensions.
- **Runner:** `backend/experiments/similarity_check.py`; deterministic half under
  `tests/test_similarity_check.py`. Rows in
  `experiments/out/similarity-check.jsonl`, the tables in
  `similarity-check.summary.json` (git-ignored; the figures below are the record).
- **Corpus:** 546 texts, every text once (one composite wrapper appeared
  twice in the red-team output and is kept once, so no text can sit in a phrase
  set and the held-out half at the same time). Attacks (386): 123/#289's 352
  red-team texts as the classifier saw them — the iterative strategy's final
  prompts, the wrappers' full text; two stream errors left out — in three rows:
  **miss** (reached the analyst, 76), **wrapper** (refused under a strategy:
  237 composite templates and 8 iterative rewrites, 245), **basic** (refused,
  31); plus the older corpora's 22 injection-shaped probes — the set
  `moderation-check.md` counted: `headline_guard` steering and suffix-on-copy
  (10), `roleplay_guard` direct, disguised, laundering (12) — and 12 policy
  refusals (hate, protected classes and the like: refusals, not injections).
  Ordinary (160): the 144 topic-boundary questions and the 16 legitimate
  headline and audience probes (7 + 9). Ambiguous probes excluded. The topic
  file has since grown to 149 (127/#299 added five of the red team's landed
  attacks, which are also among the red-team texts above); the figures here
  are the file as it was on 2026-09-03.
- **Split (Q1):** halves, stratified by source, row and strategy or group,
  shuffled once under a fixed seed; an odd stratum gives its extra item to the
  learning half. Learning half 276 (attack phrase set 195, ordinary phrase set
  81), held out 270 (38 misses — 12 basic, 20 iterative rewrites, 6 composite
  wrappers that slipped the classifier — 122 wrappers, 15 basic, 10 injection,
  6 policy, 79 ordinary). Nothing held out is in either phrase set.
- **Scores (Q2):** one-sided — the highest cosine similarity to any attack
  phrase, Bedrock's shape, swept 0.5–0.9; two-sided — that minus the highest
  similarity to any ordinary phrase, NeMo's shape, swept over margins −0.1–0.3
  (0 = "an attack is nearer than a question"). Both sweeps run until the
  ordinary-text flags reach zero.
- **Gate (Q3):** adopt if, at the loosest threshold with false positives on
  held-out ordinary text at or under the classifier's 1/160
  (`moderation-check.md`), at least a quarter of the held-out misses are caught.
- **Latency:** six single-text embedding calls, timed.

## Results

One-sided (caught / held out):

| score ≥ | misses | wrappers | basic | injection | policy | ordinary flagged |
|---|---|---|---|---|---|---|
| 0.5 | 31/38 | 122/122 | 15/15 | 9/10 | 0/6 | 19/79 |
| 0.55 | 27/38 | 121/122 | 14/15 | 6/10 | 0/6 | 10/79 |
| 0.6 | 25/38 | 121/122 | 10/15 | 4/10 | 0/6 | 5/79 |
| 0.65 | 17/38 | 120/122 | 5/15 | 4/10 | 0/6 | 3/79 |
| 0.7 | 12/38 | 118/122 | 5/15 | 3/10 | 0/6 | 2/79 |
| 0.75 | 9/38 | 117/122 | 4/15 | 1/10 | 0/6 | 1/79 |
| **0.8** | **7/38** | 115/122 | 4/15 | 1/10 | 0/6 | **0/79** |
| 0.85 | 6/38 | 109/122 | 4/15 | 0/10 | 0/6 | 0/79 |
| 0.9 | 6/38 | 103/122 | 4/15 | 0/10 | 0/6 | 0/79 |

Two-sided:

| margin ≥ | misses | wrappers | basic | injection | policy | ordinary flagged |
|---|---|---|---|---|---|---|
| −0.1 | 38/38 | 122/122 | 15/15 | 10/10 | 3/6 | 49/79 |
| −0.05 | 38/38 | 122/122 | 15/15 | 10/10 | 3/6 | 30/79 |
| 0 | 35/38 | 122/122 | 15/15 | 9/10 | 2/6 | 13/79 |
| 0.05 | 32/38 | 122/122 | 15/15 | 7/10 | 1/6 | 3/79 |
| 0.1 | 27/38 | 122/122 | 13/15 | 6/10 | 1/6 | 1/79 |
| 0.15 | 22/38 | 120/122 | 12/15 | 5/10 | 1/6 | 1/79 |
| 0.2 | 16/38 | 119/122 | 7/15 | 0/10 | 1/6 | 1/79 |
| **0.25** | **11/38** | 118/122 | 5/15 | 0/10 | 0/6 | **0/79** |
| 0.3 | 7/38 | 118/122 | 5/15 | 0/10 | 0/6 | 0/79 |

- **Gate, one-sided:** the loosest threshold at the classifier's false-positive
  rate is 0.8 (0/79), where **7 of 38 misses (18%)** are caught. Not met.
- **Gate, two-sided:** margin 0.25 (0/79), where **11 of 38 misses (29%)** are
  caught. **Met**, by four attacks. One step looser (0.2) catches 16 of 38 and
  flags 1 of 79 — twice the classifier's rate.
- **Which misses:** at margin 0.25 the 11 are 6 of the 6 composite wrappers
  that slipped the classifier, 4 of the 12 basic attacks, and **1 of the 20
  natural rewrites**. At 0.8 one-sided: 6, 0 and 1.
- **Against Mistral's row** (`moderation-check.md`: disguised injections caught
  0/4; 1/160 ordinary flagged): the held-out disguised probes from the older
  corpora are caught 0/2 by either score at its gate threshold; the overt ones
  1/8 (one-sided) and 0/8 (two-sided). What either score adds over the
  classifier is the template-shaped attacks it let through.
- **Latency:** one embedding call 0.40 s median, 0.61 s max (n = 6); the cosine
  over a few hundred phrases is microseconds.
- **Cost:** about 62,000 tokens (characters ÷ 4) — a tenth of a cent for the
  whole corpus. Per message in production: a 2,000-character message (the
  schema's cap) is about 500 tokens, $0.00001 at $0.02/M; the median ordinary
  question here is 48 characters.

## Reading

- **The wrappers cluster; the rewrites do not.** Template jailbreaks are
  near-copies of each other — 115 of 122 caught at zero false positives by the
  plain threshold — and the classifier already refuses 238 of 250 of them. The
  six that slipped through are the two-sided score's whole gain over the
  classifier, plus four basic attacks. The natural rewrites are written to read
  like questions about the report, and in embedding space that is where they
  sit: 1 of 20 caught at either gate threshold, and the two-sided score finds
  more of them only by also flagging ordinary questions (27 of 38 at margin
  0.1, with 1 of 79 flagged).
- **The gate is met on the letter and thin in fact.** It counted all misses; the
  ones caught are the shape the classifier already handles. With 79 held-out
  ordinary texts, "at or under 1/160" is satisfiable only by zero flags, so the
  false-positive side is measured at a coarser resolution than the gate. An
  earlier split of the same corpus (before a labelling fix moved four probes
  between rows) put the two-sided score's best clean cell at 2 of 79 flagged:
  the result moves with the split at this corpus size.
- **An input-side filter is the wrong layer for paraphrase.** The similarity
  check is an intent matcher: good at denied topics that resemble each other,
  weak against attacks that resemble legitimate use — which is what the ticket
  predicted and what this measured.

## Decision

**Gate met by the two-sided score; adoption deferred to 126/#297.** Nothing
changes in the product from this ticket: no phrase table, no margin constant,
no call in `guard_chat_message`. The record says the agreed rule was satisfied,
and that what it would buy is the template leftovers at 0.4 s per message;
whether that is worth a control, measured on a larger ordinary corpus, is the
follow-up's question. The classifier stays the input-side control for what it
catches — templates and fake system messages — and the analyst's own rules,
which held on 30 of the 40 rewrites in the red team, stay the control against
paraphrase.

## What would catch the natural rewrites instead

Assessed with the author on 2026-09-03; each lives on its own ticket.

1. **Prompt rules aimed at the tricks, verified by the red team** (091, 121).
   The seven substantive fails name the gaps: supplied text and authored
   artefacts (legends, codes, rubrics, labels) are answers; a constrained
   format about the machinery gets the decline, not a letter; a mixed ask gets
   its outside part declined. One sentence each, no per-turn cost, and the 59
   probes that passed the pre-flight are the regression test — rerun the
   harness and count the misses.
2. **Check the reply, not the message.** Two of the seven fails were visible
   in the output with a clean input: the graphic anchor sentence and the
   machinery facts. The moderation classifier is free and integrated, so scoring
   the reply against the content categories catches the first; a word list on
   the reply (121) catches a named model or provider. The cost is a design
   decision: a streamed reply cannot be unsent, so the check runs on complete
   sentences before they are flushed, or the reply is buffered. A ticket.
3. **Ground answers in tool results.** The legend and the rubric were
   free-form generations with no tool call; a turn that answers without one
   could be treated as suspect. Greetings and follow-ups also answer without
   tools, so this needs a measurement first.
4. **A second model judging the input** would likely catch the rewrites, at a
   paid call per turn against the $1.00 daily pool. 091 rejected it on cost;
   nothing here reopens that.
