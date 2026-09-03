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

**Answer: no, at a false-positive rate the reader would not notice. Declined
and recorded.**

## Method

- **Embedder:** `openai/text-embedding-3-small` through OpenRouter, the repo's
  own `OpenRouterEmbedder` (`settings.embedding_model`), which the analyst
  already calls once per corpus search. $0.02 per million input tokens (OpenRouter
  model page, read 2026-09-03; OpenAI's list price is the same). 1536 dimensions.
- **Runner:** `backend/experiments/similarity_check.py`; deterministic half under
  `tests/test_similarity_check.py`. Rows in
  `experiments/out/similarity-check.jsonl`, the tables in
  `similarity-check.summary.json` (git-ignored; the figures below are the record).
- **Corpus:** 547 texts. Attacks (387): 123/#289's 353 red-team texts as the
  classifier saw them — the iterative strategy's final prompts, the wrappers'
  full text; two stream errors left out — in three rows: **miss** (reached the
  analyst, 76), **wrapper** (composite template, refused, 238), **basic**
  (refused, 31); plus the older corpora's 16 injection-shaped probes
  (`headline_guard`: steering, disguised, suffixes; `roleplay_guard`: direct,
  disguised, laundering) and 18 policy refusals (hate, protected classes —
  refusals, not injections). Ordinary (160): the 144 topic-boundary questions
  and the 16 legitimate headline and audience probes. Ambiguous probes excluded.
- **Split (Q1):** halves, stratified by source, row and strategy or group,
  shuffled once under a fixed seed. Learning half 276 (attack phrase set 197,
  ordinary phrase set 81 — one item of the 160 lands on the learning side of an
  odd stratum), held out 271 (38 misses, 123 wrappers, 15 basic, 8 injection,
  8 policy, 79 ordinary). Nothing held out is in either phrase set.
- **Scores (Q2):** one-sided — the highest cosine similarity to any attack
  phrase, Bedrock's shape, swept 0.5–0.9; two-sided — that minus the highest
  similarity to any ordinary phrase, NeMo's shape, swept over margins −0.1–0.1
  (0 = "an attack is nearer than a question").
- **Gate (Q3):** adopt if, at the loosest threshold with false positives on
  held-out ordinary text at or under the classifier's 1/160
  (`moderation-check.md`), at least a quarter of the held-out misses are caught.
- **Latency:** six single-text embedding calls, timed.

## Results

One-sided (caught / held out):

| score ≥ | misses | wrappers | basic | injection | policy | ordinary flagged |
|---|---|---|---|---|---|---|
| 0.5 | 30/38 | 123/123 | 15/15 | 7/8 | 2/8 | 21/79 |
| 0.55 | 30/38 | 122/123 | 14/15 | 4/8 | 2/8 | 9/79 |
| 0.6 | 27/38 | 121/123 | 11/15 | 2/8 | 2/8 | 4/79 |
| 0.65 | 21/38 | 120/123 | 7/15 | 2/8 | 2/8 | 3/79 |
| 0.7 | 13/38 | 119/123 | 5/15 | 1/8 | 2/8 | 1/79 |
| 0.75 | 9/38 | 119/123 | 4/15 | 0/8 | 2/8 | 1/79 |
| **0.8** | **8/38** | 116/123 | 4/15 | 0/8 | 2/8 | **0/79** |
| 0.85 | 6/38 | 110/123 | 4/15 | 0/8 | 1/8 | 0/79 |
| 0.9 | 6/38 | 104/123 | 4/15 | 0/8 | 0/8 | 0/79 |

Two-sided:

| margin ≥ | misses | wrappers | basic | injection | policy | ordinary flagged |
|---|---|---|---|---|---|---|
| −0.1 | 38/38 | 123/123 | 15/15 | 8/8 | 5/8 | 48/79 |
| −0.05 | 38/38 | 123/123 | 15/15 | 8/8 | 5/8 | 28/79 |
| 0 | 37/38 | 123/123 | 15/15 | 7/8 | 4/8 | 14/79 |
| 0.05 | 33/38 | 123/123 | 14/15 | 5/8 | 3/8 | 6/79 |
| 0.1 | 28/38 | 123/123 | 13/15 | 5/8 | 2/8 | 2/79 |

- **Gate, one-sided:** the loosest threshold at the classifier's false-positive
  rate is 0.8 (0/79), where **8 of 38 misses (21%)** are caught. Under the
  quarter asked for. One step looser, 0.7, catches 13 of 38 (34%) and flags 1 of
  79 ordinary questions — twice the classifier's rate.
- **Gate, two-sided:** no margin keeps false positives at the classifier's
  rate; the best cell (margin 0.1) flags 2 of 79 while catching 28 of 38.
- **Latency:** one embedding call 0.32 s median, 0.42 s max (n = 6); the cosine
  over a few hundred phrases is microseconds.
- **Cost:** about 62,000 tokens — a tenth of a cent for the whole corpus; in
  production, one embedding call per message at $0.02/M.

## Reading

- **The wrappers cluster; the rewrites do not.** Template jailbreaks are
  near-copies of each other — 116 of 123 caught at zero false positives — but
  those are the attacks the classifier already refuses 238 of 250 times. The
  natural rewrites are written to read like questions about the report, and in
  embedding space that is where they sit: the two-sided score, which asks
  whether an attack or an ordinary question is nearer, finds most of them only
  by also flagging one ordinary question in six.
- **The gate is stricter than it reads at this corpus size.** With 79 held-out
  ordinary texts, "at or under 1/160" is satisfiable only by zero flags. A
  larger ordinary corpus would let 0.7 be judged at its true rate; it would not
  change the shape of the table.
- **An input-side filter is the wrong layer for paraphrase.** The similarity
  check is an intent matcher: good at denied topics that resemble each other,
  weak against attacks that resemble legitimate use — which is what the ticket
  predicted and what this measured.

## Decision

**Declined.** No phrase-set similarity check in `guard_chat_message`, no
pgvector table of attack phrases, no threshold constant. The classifier stays
the input-side control for what it catches — templates and fake system
messages — and the analyst's own rules, which held on 30 of the 40 rewrites in
the red team, stay the control against paraphrase.

## What would catch the misses instead

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
