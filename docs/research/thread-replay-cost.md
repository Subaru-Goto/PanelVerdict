# Thread replay cost — what re-sending the analyst's history actually bills (2026-09-02)

Ticket [104/#223](https://github.com/Subaru-Goto/PanelVerdict/issues/223). The
ticket's claim: retrieved corpus passages land in the analyst thread's checkpointed
history and are re-sent as input on every later model call, nothing trims them, and
a long thread therefore pays for the same passages many times over. The ticket was
written before [`analyst-turn-cost.md`](analyst-turn-cost.md) existed and costs the
replay at full input price. This document re-costs it with the caching that
measurement observed — and with the one case that measurement did not cover, a
reader who returns to a thread after the cache has expired.

Method: **no paid call was made.** Code facts are cited `file:line` from this branch;
token counts were measured locally with `tiktoken` `o200k_base` (the tokenizer
[`prompt-caching.md`](prompt-caching.md) used) over the exact strings the code sends;
provider documentation was read live 2026-09-02 and is quoted verbatim; everything
labelled *computed* or *inferred* is this document's own arithmetic over those
inputs, not a measurement. The installed packages under
`backend/.venv/lib/python3.13/site-packages/` are the source of truth over their docs.

## Bottom line

**Measured, and the ticket's premise is correct but its arithmetic is not.** The
history is replayed in full on every call, and nothing prunes it. But within a
cache lifetime the replay is read at $0.02/M — a tenth of the input price — so a
30-turn thread of the measured shape costs about **$0.018 against the $0.015 the
gate charged for it** (*computed*, §4B). The number that matters is the **cold
return**: a reader who comes back to a thread more than 30 minutes later pays the
cache-*write* rate, $0.25/M, on the whole replayed history, and at turn 30 of a
corpus-heavy thread that single turn costs **18× what the gate charged** (§4A).
Whether that matters depends on one quantity nobody has measured: how often a real
turn arrives cold. The `analyst usage` log line already records what would settle
it (`cached_tokens` against `input_tokens`, `analyst.py:588-602`), so the honest
next step is to read that log, not to add middleware. Details and the one
recommendation follow.

Three corrections to the ticket's text, from code:

- The step budget is no longer `2 * len(tools) + 2`. It is a declared constant,
  `CALLS_PER_TURN = 5` (`backend/app/analyst.py:69`), adopted by
  [052/#149](https://github.com/Subaru-Goto/PanelVerdict/issues/149);
  the retired arithmetic is named in the comment above it (`analyst.py:61-68`).
- "Re-sends those passages on the order of a hundred times" overstates the bound.
  A thread is capped at 30 turns a day (`backend/app/config.py:189`) and a turn at
  5 model calls, so the ceiling is 150 replays a day; the six measured turns used
  1–3 calls each ([`analyst-turn-cost.md`](analyst-turn-cost.md), table).
- "No per-turn token figure exists yet" was true when written; 070/#161 has since
  measured six turns, and this document builds on them.

## 1. The thread's shape today, from code

**How the agent is built.** `stream_analyst` rebuilds the agent per request with
`create_agent(model=…, tools=…, system_prompt=_SYSTEM_PROMPT, checkpointer=…,
middleware=[_BudgetEndsTheTurn(run_limit=CALLS_PER_TURN)])`
(`backend/app/analyst.py:636-642`). There is no trimming, summarising or
context-editing middleware and no pre-model hook; the only middleware is the call
budget. The checkpointer is an `AsyncPostgresSaver` over an `AsyncConnectionPool`
with `min_size=1, max_size=1` (`backend/app/main.py:196-203`), which confirms the
ticket's pool claim. The agent state's `messages` channel uses langgraph's
`add_messages` reducer (installed `langchain/agents/middleware/types.py:350`), so
every message ever appended — `HumanMessage`, tool-calling `AIMessage`,
`ToolMessage`, answer — is restored from the checkpoint and sent to the model on
each call. That retention is deliberate, per the module docstring: "the
checkpointed transcript keeps ToolMessages, so a follow-up is answered from
context instead of re-buying tool calls a text-only replay would drop"
(`analyst.py:5-7`).

**The rewrite per superstep.** The saver's `_dump_blobs` serialises every channel
whose version changed at that checkpoint (installed
`langgraph/checkpoint/postgres/base.py:548-570`); the `messages` channel changes on
every superstep, so the whole list is re-serialised each time. Confirmed. It is bytes to Postgres, not dollars to OpenRouter, so this document
does not cost it; the half of the ticket's claim that matters — one connection
shared by every concurrent stream — is a throughput ceiling, deferred here, and
of a kind with the connection ceilings
[112/#242](https://github.com/Subaru-Goto/PanelVerdict/issues/242) asks about.

**What the RAG tool returns.** `explain_the_report` calls
`search_corpus(deps.conn, question, deps.embedder)` and returns a JSON list of
`{"citation", "passage"}` objects (`analyst.py:498-515`); `search_corpus` defaults to
`limit: int = 4` (`backend/app/corpus.py:249-254`). Four passages per call, so the
ticket's "four passages" is right; its "~950 tokens" is measured in §2.

**What is sent on every call.** The system prompt (`analyst.py:147-223`, a constant
with no interpolation) and the four tool schemas are bound into every request; they
are the cacheable prefix. The client-supplied `EvaluateResponse` is *not* model
input — the tools close over it (`analyst.py:433-517`) and only what a tool returns
reaches the transcript.

**The caps and the price.** 30 turns per thread per day (`config.py:189`), 120 per
caller (`config.py:194`), a $1.00 global daily pool (`config.py:207`). `USD_PER_TURN = 0.0005` (`config.py:129`) is flat, and the
comment above it records why: "a thread's replayed history is 80-96% cache reads at
a tenth of the input price, so turn cost grows far slower than the transcript, and
the thread-level bound is the per-thread daily turn cap" (`config.py:118-121`).
That reasoning is what §4 tests.

**The rules that bear on pruning.** The system prompt's second rule says of this
test's figures: "comes from a tool every time: never from memory, never estimated,
never inferred from what you were told earlier in the conversation"
(`analyst.py:178-179`), and of concepts: "comes from explain_the_report … Call it
even when you think you know the answer" (`analyst.py:183-185`). Both rules tell
the model *not* to reuse earlier tool results, which cuts against the docstring's
reason for keeping them; §5 returns to this.

## 2. Token sizes, measured offline

`tiktoken` 0.13.0, `o200k_base`, over the exact strings the code sends. Scripts ran
from `backend/` with `PYTHONPATH=.`; `build_tools` was called with a `None` result
and empty deps (the closures were never invoked), tool schemas were serialised with
`langchain_core.utils.function_calling.convert_to_openai_tool` in compact JSON,
and the four-passage result was serialised exactly as `explain_the_report` does.

| payload | tokens | source |
|---|---|---|
| system prompt `_SYSTEM_PROMPT` | **697** (3,189 chars) | `analyst.py:147-223` |
| tool schemas: `analyze_results` 160, `search_personas` 104, `read_reasons` 100, `explain_the_report` 186 | **550** | `analyst.py:450-517` |
| **cacheable prefix** (prompt + schemas) | **1,247** | *computed*, sum |
| corpus: 15 chunks, per-chunk passage 49 … 298 (median 191) | **2,623** total | `app/data/corpus/*.md` via `corpus.DOCUMENTS` |
| whole corpus joined as one string (the static-copy shape, §6) | **2,624** | *computed* |
| raw markdown files (with the grounding comments the splitter drops) | 2,888 | `app/data/corpus/*.md` |
| one `explain_the_report` result (4 passages, JSON) — all 1,365 four-chunk combinations | min 483, **median 871, mean 869**, max 1,224 | *computed* over `DOCUMENTS` |
| JSON + citation overhead per passage | ~170 per result | *computed*, mean result − 4 × mean passage |
| `analyze_results` result on the demo capture's votes (50 / 200 votes) | 285 / 267 | `analysis_facts` over `app/data/demo/free-delivery.json` |
| `read_reasons` result (50 / 200 votes, original reasons) | **1,249 / 4,739** | `vote_reasons` over the same |
| one tool-calling `AIMessage` as OpenAI JSON | ~65 | *computed*, representative call |
| a question ("what does credible mass mean") | 5–8 | *computed* |

So the ticket's "~950 tokens" for four passages is 869 on the mean and 1,224 at
worst; a thread that asked only corpus questions would carry the whole 2,624-token
corpus in its history after three turns and more than the corpus contains after
four — the ticket's "more corpus text in its history than the corpus contains" is
right, and it happens early.

> **Correction (2026-09-04, [084/#175](https://github.com/Subaru-Goto/PanelVerdict/issues/175)):**
> `search_personas` is retired, so the tool-schema row above now describes three
> tools and its total is 550 − 104 = **446** on the same tokenizer. The measured
> figures are left as recorded; the paragraph below's first sentence is moot.

**Not measured, and why.** `search_personas` needed the database (`persistence.nearest_panelists`,
both since removed); its result was bounded by `_SEARCH_LIMIT = 5` summaries
("near 200 tokens" by the sign-off there). Whether reasoning content is replayed into later
calls was not measured; at `reasoning_effort="low"` (`llm.py:537`) the measured
reasoning was 0–19 tokens a turn, so it cannot move the totals. `tiktoken` counts
of JSON are an approximation of the provider's rendering; the calibration in §4
puts the approximation at 2–17% high on whole-turn input.

## 3. Caching rules, read live 2026-09-02

### OpenAI, <https://developers.openai.com/api/docs/guides/prompt-caching>

(`platform.openai.com/docs/guides/prompt-caching` redirects here. The page has been
rewritten since [`prompt-caching.md`](prompt-caching.md) read it on 2026-07-27; the
quotes below are from today's text.)

Minimum, now split by model family:

> The minimum cacheable prompt length is 1,024 tokens for GPT-5.6 and later and
> 2,048 tokens for models older than GPT-5.6.

What is cached, and the prefix rule:

> OpenAI caches the model's full rendered context including OpenAI-provided
> instructions, developer messages, tool definitions, and conversation history
> containing text, images, documents, and supported audio. Cache reuse requires the
> entire rendered prefix to match.

> The first request writes an eligible prefix to the cache and a later request looks
> for the longest matching cached prefix available, working backward through
> eligible breakpoints until it finds a match.

Implicit (automatic) breakpoints, which is what a Chat Completions request through
langchain uses:

> Implicit mode: OpenAI chooses breakpoint locations out of the box that work well
> for most use cases. When `prompt_cache_options.mode` is implicit, OpenAI places a
> breakpoint at the end of the latest eligible message.

Price — the part the ticket and the previous measurement did not have:

> For GPT-5.6 and later, cache writes cost 1.25× the standard, uncached input-token
> rate. It is worth incurring this charge when a prefix will be reused, because
> subsequent reads cost only 0.1× that rate. Writing a prefix once and fully reusing
> it once costs 1.35× its ordinary input cost, compared with 2× for processing it
> twice without caching.

Lifetime:

> Cache entries are not stored indefinitely. A later request can reuse a cached
> prefix only while its entry remains available, and reusing the prefix refreshes
> its lifetime without another cache-write charge.

> GPT-5.6 and later: Use `prompt_cache_options.ttl` to control the minimum cache
> lifetime. The only supported value, `30m`, is also the default. A cached prefix
> remains eligible for reuse for 30 minutes after its most recent write or reuse,
> though OpenAI may retain it longer.

> Earlier models: … `in_memory`: Entries typically remain active for around 5 to 10
> minutes of inactivity, up to one hour.

Granularity of what is reported (this is the 128-token statement
[`prompt-caching.md`](prompt-caching.md) could not find on 2026-07-27; it is back):

> Reported `cached_tokens` is calculated by subtracting the hidden system tokens
> from the last matched breakpoint, then rounding down to the nearest multiple of
> 128.

The six measured turns do not show that rounding: their `cached_tokens` (2,412,
5,688, 2,964, 2,412, 3,374, 2,363) are not multiples of 128. Those counts arrived
through OpenRouter's normalised `usage`, so either OpenRouter reports the
unrounded figure or the rule does not apply as quoted. The family inference below
rests on the write price, not on this quote, and §4 ignores the rounding.

The page names `gpt-5.6-sol` in an example and never `gpt-5.6-luna`. *Inferred:* the
shipped `analyst_model` carries the family name, and OpenRouter's catalogue (below)
prices its cache writes at exactly 1.25× input — the GPT-5.6-family signature both
documents describe — so the 5.6 rules (1,024-token minimum, 30-minute lifetime,
1.25× writes, 0.1× reads) are taken as the ones that apply. The measured 80–96% cache
share on 2,400–7,000-token prompts is consistent with a 1,024 minimum and not with
2,048.

### OpenRouter, <https://openrouter.ai/docs/features/prompt-caching>

(machine-readable copy at `…/prompt-caching.md`, fetched for exact text.)

> Prompt caching with OpenAI is automated and does not require any additional
> configuration. There is a minimum prompt size of 1024 tokens.

> * **Cache writes**: no cost on models before the GPT-5.6 family. GPT-5.6 and later
>   charge cache writes at 1.25x the price of the original input pricing, even with
>   automatic caching — no opt-in required.
> * **Cache reads**: (depending on the model) charged at 0.25x or 0.50x the price of
>   the original input pricing

The 0.25x/0.50x prose disagrees with OpenRouter's own catalogue, as
[`prompt-caching.md`](prompt-caching.md) §1 found for gpt-5-mini. `GET
https://openrouter.ai/api/v1/models`, read 2026-09-02, `openai/gpt-5.6-luna`:
`"prompt": "0.0000002"`, `"completion": "0.0000012"`, `"input_cache_read":
"0.00000002"`, `"input_cache_write": "0.00000025"` — **$0.20/M input, $1.20/M
output, $0.02/M cache read (0.1×), $0.25/M cache write (1.25×)**. These four are
the prices used below; the first three match
[`analyst-turn-cost.md`](analyst-turn-cost.md)'s quoted list prices, the fourth is
new to this document.

How cache activity is reported:

> Cache activity is reported in `usage.input_tokens_details` (Responses) and
> `usage.prompt_tokens_details` (Chat Completions): `cache_write_tokens` counts
> prompt tokens written to the cache, and `cached_tokens` counts prompt tokens read
> from it.

Routing, which a cold return also loses:

> Sticky sessions expire after **10 minutes** of inactivity. Each successful request
> resets the timer.

> By default, OpenRouter identifies conversations by hashing the first system (or
> developer) message and the first non-system message in each request

*Inferred:* the analyst's first system message is a constant and its first
non-system message is the thread's first question, so every call in a thread hashes
to the same sticky key without a `session_id` — good — but the 10-minute sticky
window is shorter than the 30-minute cache lifetime, so a return between 10 and 30
minutes may be routed to a different endpoint. Whether that costs the cache is not
documented and not measured here.

### What the code logs, and what it does not

`_TurnUsage.take` reads `input_token_details.cache_read` (`analyst.py:579`).
`langchain_openai` 1.3.5 also maps `cache_write_tokens` to
`input_token_details.cache_creation` (installed
`langchain_openai/chat_models/base.py:4150-4153`), and the code ignores it. So the
log can show a cold turn (near-zero `cached_tokens` on a large `input_tokens`) but
cannot show how many tokens were billed at the write rate. **Consequence for
[`analyst-turn-cost.md`](analyst-turn-cost.md):** its derivation priced every
uncached token at $0.20/M; on a GPT-5.6-family model the uncached tokens ahead of
the implicit breakpoint are writes at $0.25/M (how many is *inferred* below, not
logged). *Computed:* the worst low-effort turn
had 405 uncached tokens; at $0.25/M instead of $0.20/M that is +$0.00002, taking
$0.000429 to ~$0.00045 — still under `USD_PER_TURN`. The gate holds; the derivation
should say "write rate" where it says "input".

### The calibration point the measurement gives for free

The six measured turns constrain *where* the implicit breakpoint falls. The
low-effort thread's follow-up turn was one call of 2,471 input tokens with 2,363
cached (analyst-turn-cost.md, table): only ~108 tokens were uncached — about the
previous answer plus the new question. Had the breakpoint sat at the latest *user*
message, the previous turn's tool call and 4-passage result (≈ 65 + 500–900
tokens) would have been uncached too. *Inferred from the measured counts:* each call
writes the whole prompt it sends, and the next call reads all of it back. The
model in §4 uses that rule: **each call reads what the previous call sent at
$0.02/M and writes what is new at $0.25/M; a cold turn's first call writes
everything.**

## 4. The cost model — arithmetic on measured token counts

This is not a live measurement. Inputs: prefix 1,247; question 8; tool-call
message 65; four-passage result 869 (mean); `analyze_results` 285; visible answer
per turn shape, from the measured low-effort turns' `output − reasoning`: figures
231, corpus 117, follow-up 49 (scenario C, a figures-shaped answer, uses 231; D
uses 117);
prices from §3. Per turn *t* the history *H* is the sum of every earlier turn's
question + tool calls + tool results + answer. "Warm" means every call in the
thread arrived within the 30-minute lifetime of the previous one; "cold" means the
turn's first call found nothing cached (a return after the lifetime — *or* the
first turn of a new thread, which finds only the shared 1,247-token prefix warm if
another thread used it recently). Output is priced at $1.20/M on the visible
answer only; low-effort reasoning was 0–19 tokens. The gate is `USD_PER_TURN =
0.0005`. The `cached_tokens` 128-token rounding is ignored. The rule per call, from
§3: warm, `(prompt − new) × $0.02/M + new × $0.25/M`; cold first call, `prompt ×
$0.25/M`; each later call in the turn reads the previous prompt at $0.02/M and
writes the tool call + result at $0.25/M. The arithmetic is reproducible from the
inputs above and small enough to check by hand — see the calibration row.

**Calibration against the measured low-effort thread** (*computed*): the model's
input-token totals for the figures / corpus / follow-up turns are 2,860 / 4,622 /
2,903 against measured 2,817 / 4,138 / 2,471. It runs 2–17% high, because the mean
869-token passage result is larger than what that thread retrieved (the measured
follow-up implies a history of ~1,216 tokens after two turns, against the model's
1,648). Every dollar figure below is therefore conservative by roughly that margin.

### A. Every turn a corpus question (2 calls; 4-passage result each)

| turn | model calls | history before turn (tokens) | warm: input $ | warm: turn $ | cold: input $ | cold: turn $ | cold turn ÷ gate |
|---|---|---|---|---|---|---|---|
| 1 | 2 | 0 | 0.00029 | 0.00043 | 0.00057 | 0.00071 | 1.4× |
| 2 | 2 | 1,059 | 0.00035 | 0.00050 | 0.00086 | 0.00100 | 2.0× |
| 5 | 2 | 4,236 | 0.00048 | 0.00062 | 0.00172 | 0.00186 | 3.7× |
| 10 | 2 | 9,531 | 0.00069 | 0.00083 | 0.00315 | 0.00329 | 6.6× |
| 20 | 2 | 20,121 | 0.00112 | 0.00126 | 0.00601 | 0.00615 | 12.3× |
| 30 | 2 | 30,711 | 0.00154 | 0.00168 | 0.00886 | 0.00900 | 18.0× |
| **30 turns, cumulative** | | | | **0.0320** | | **0.1458** | gate charged **0.0150** |

First turn whose cost exceeds the gate: warm turn 3 (turn 2 prints as $0.00050
but is $0.000495), cold turn 1.

### B. The measured mix — figures, corpus, follow-up, repeating

| turn | shape | model calls | history before turn (tokens) | warm: input $ | warm: turn $ | cold: input $ | cold: turn $ | cold turn ÷ gate |
|---|---|---|---|---|---|---|---|---|
| 1 | figures | 2 | 0 | 0.00014 | 0.00042 | 0.00043 | 0.00070 | 1.4× |
| 2 | corpus | 2 | 589 | 0.00036 | 0.00050 | 0.00073 | 0.00087 | 1.7× |
| 5 | corpus | 2 | 2,294 | 0.00043 | 0.00057 | 0.00119 | 0.00133 | 2.7× |
| 10 | figures | 2 | 5,115 | 0.00036 | 0.00063 | 0.00181 | 0.00208 | 4.2× |
| 20 | corpus | 2 | 10,819 | 0.00077 | 0.00091 | 0.00349 | 0.00363 | 7.3× |
| 30 | follow-up | 1 | 16,993 | 0.00039 | 0.00045 | 0.00456 | 0.00462 | 9.2× |
| **30 turns, cumulative** | | | | | **0.0184** | | **0.0842** | gate charged **0.0150** |

The warm column here is the model's version of the thread 070 measured; its turn 2
($0.00050) sits 34% above the measured $0.000373, which is the conservatism noted
above. The warm column dips at turn 10 because that turn is figures-shaped — a
285-token result and no passages. Warm, a 30-turn thread costs ~1.2× what the
gate charged; cold on every turn, ~5.6×.

### C. Every turn at the 5-call budget, four passage retrievals each (the ceiling, given honest tool results)

| turn | model calls | history before turn (tokens) | warm: input $ | warm: turn $ | cold: input $ | cold: turn $ | cold turn ÷ gate |
|---|---|---|---|---|---|---|---|
| 1 | 5 | 0 | 0.00117 | 0.00145 | 0.00146 | 0.00174 | 3.5× |
| 5 | 5 | 15,900 | 0.00282 | 0.00309 | 0.00671 | 0.00698 | 14.0× |
| 10 | 5 | 35,775 | 0.00480 | 0.00508 | 0.01327 | 0.01354 | 27.1× |
| 30 | 5 | 115,275 | 0.01275 | 0.01303 | 0.03950 | 0.03978 | 79.6× |
| **30 turns, cumulative** | | | | **0.2180** | | **0.6227** | gate charged **0.0150** |

No measured turn looks like this — the worst real turn used 3 calls — but it is what
the declared budget permits, and it is the case `config.py`'s note "a capped turn a
larger multiple of `USD_PER_TURN`" refers to. Cold, one such thread bills 62% of the
$1.00 daily pool while being charged 1.5% of it.

### What pruning old tool results would change (*computed*, same model)

If a turn's `ToolMessage`s left the history once the turn had answered (the
tool-calling `AIMessage`s stay, so the transcript still shows a tool was used):

| scenario | turn 30 history | warm turn 30 | cold turn 30 | 30 turns warm / cold |
|---|---|---|---|---|
| A as above | 30,711 | 0.00168 | 0.00900 (18×) | 0.0320 / 0.1458 |
| A, tool results pruned | 5,510 | 0.00067 | 0.00220 (4.4×) | 0.0169 / 0.0437 |
| C as above | 115,275 | 0.01303 | 0.03978 (80×) | 0.2180 / 0.6227 |
| C, tool results pruned | 14,471 | 0.00295 | 0.00651 (13×) | 0.0668 / 0.1238 |

Pruning divides the cold-return cost by 4–6 and brings a warm corpus-only thread
to within 13% of what the gate charged. It does not touch the intra-turn cost (the
passages are still written and read within the turn that fetched them), which is
why turn 1 is unchanged.

### Reading the tables

1. **Warm, the flat gate is nearly right.** For the measured mix a 30-turn thread
   bills ~$0.018 against $0.015 charged; the per-turn cost drifts above $0.0005 from
   about turn 2–3 in the model and, correcting for its conservatism, somewhat later
   in life. This is the case `config.py:118-121` reasoned from, and the reasoning
   holds.
2. **Cold, it is wrong by an order of magnitude at the end of a thread.** A cold
   turn's cost is ~$0.25/M × (1,247 + *H*), and *H* grows ~500–1,100 tokens a turn,
   so the cold price rises ~$0.00013–0.00027 per turn of history: past the gate at
   turn 1, 4× at turn 10, 10–18× at turn 30.
3. **The pool still bounds the day**, because the pool is a ceiling on *charges* and
   the caps are counts: the worst a single caller can do is 120 turns. But at
   scenario-C-cold rates that is ~$2.50 billed per caller (*computed*: 4 ×
   $0.6227) — and the pool admits 2,000 turns a day ($1.00 / $0.0005), ~67 such
   threads across 17 callers, **~$41 billed against $1.00** (*computed*: 66.7 ×
   $0.6227). That is the structural ceiling `docs/least-privilege.md` Asset 2
   names — the global cap times the worst charge-to-bill ratio — with the ratio
   now measured. The pool's protection is the model's observed
   behaviour (1–3 calls, mostly warm), not the arithmetic.
4. **The corpus passages are not the largest thing replayed.** A `read_reasons`
   result on a 200-vote run is 4,739 tokens — five four-passage results — and it is
   replayed on the same terms. Its text is the client-supplied `reason` strings,
   which nothing sizes (tech-debt #171, item 1) — so scenario C is a ceiling only
   for honest inputs. Any pruning rule that names only `explain_the_report`
   misses the bigger item.

## 5. What the installed libraries offer

Versions from `*.dist-info/METADATA`: `langchain 1.3.14`, `langchain_core 1.4.9`,
`langgraph 1.2.10`, `langgraph_prebuilt 1.1.0`, `langgraph_checkpoint_postgres
3.1.2`, `langchain_openai 1.3.5`, `openai 2.46.0`, `tiktoken 0.13.0`.

**No `pre_model_hook` on the agent the repo uses.** `langchain.agents.create_agent`'s
signature (installed `langchain/agents/factory.py:808-825`) takes `model, tools,
system_prompt, middleware, response_format, state_schema, context_schema,
checkpointer, store, interrupt_before, interrupt_after, debug, name, cache,
transformers` — no hook argument. The `pre_model_hook: RunnableLike | None = None`
the ticket may have had in mind belongs to the older
`langgraph.prebuilt.create_react_agent` (installed
`langgraph/prebuilt/chat_agent_executor.py:296`), which this codebase does not
call. In `create_agent` the equivalent is a middleware hook: `before_model(state,
runtime)` (`langchain/agents/middleware/types.py:443`) or `wrap_model_call(request,
handler)` (`types.py:491`) — the same mechanism `_BudgetEndsTheTurn` already rides.

Three shipped options, and the primitive under them:

- **`ContextEditingMiddleware`** (`langchain/agents/middleware/context_editing.py:187`):
  "Automatically prune tool results to manage context size. The middleware applies
  a sequence of edits when the total input token count exceeds configured
  thresholds." Its one strategy is `ClearToolUsesEdit` (`:58-75`): `trigger: int =
  100_000` ("Token count that triggers the edit"), `clear_at_least: int = 0`, `keep:
  int = 3` ("Number of most recent tool results that must be preserved"),
  `clear_tool_inputs: bool = False`, `exclude_tools: Sequence[str] = ()`. Applied in
  `wrap_model_call`, so it edits the request, not the checkpoint — the stored
  transcript keeps the passages, only the model stops seeing the old ones. The
  default trigger of 100,000 tokens would never fire here (scenario C reaches
  115,275 only at turn 30); it would need setting to a few thousand.
- **`SummarizationMiddleware`** (`summarization.py:219-235`): "Summarizes
  conversation history when token limits are approached … preserving recent
  messages and maintaining context continuity by ensuring AI/Tool message pairs
  remain together." Takes a `model` — a second paid call per summarisation, output
  tokens at $1.20/M — plus `trigger`, `keep` (default `("messages", 20)`,
  `_DEFAULT_MESSAGES_TO_KEEP = 20`, `:91`), `trim_tokens_to_summarize` (default
  4,000, `:92`). It writes the summary into the checkpoint.
- **`trim_messages`** (`langchain_core/messages/utils.py:1133-1147`):
  `trim_messages(messages, *, max_tokens, token_counter, strategy="last",
  allow_partial=False, end_on=None, start_on=None, include_system=False,
  text_splitter=None)`. A pure function; it needs a `before_model` or
  `wrap_model_call` wrapper to reach the loop.

**What each would lose here.**

- *Pruning tool results* (`ClearToolUsesEdit`, or a `before_model` that drops
  `ToolMessage`s from earlier turns): the prompt already forbids reusing them for
  figures ("never inferred from what you were told earlier in the conversation",
  `analyst.py:178-179`) and tells the model to call `explain_the_report` "even when
  you think you know the answer" (`:185`) — so for the two-kinds rule pruning
  removes something the model was instructed not to lean on. What it does lose is
  the docstring's property (`analyst.py:5-7`): a follow-up like "say that passage
  more simply" would re-retrieve instead of re-reading, i.e. one more tool round
  (~$0.0003 warm). It also loses a citation's *verbatim* text from the context —
  the model would cite from a re-fetch, which is what the rule asks anyway. And
  every prune rewrites the prefix: the first call after a prune misses the cache
  for everything past the edit and writes it again at $0.25/M — bounded by the
  pruned history itself, so a one-off cost the tables above already dominate.
- *Trimming the window* (`trim_messages`, `strategy="last"`): drops the oldest
  turns whole, including the reader's own questions and the analyst's answers, so
  a long thread forgets its own beginning; and a partial trim can orphan a
  `ToolMessage` from its `AIMessage`, which the OpenAI API rejects — `end_on` /
  `start_on` exist for that.
- *Summarising*: the summary is model text about passages, so a "citation" in it
  is no longer a passage the reader can check — it converts grounded text into
  memory, the exact failure the 018 corpus was built to prevent; and it spends
  output tokens to save input tokens priced at a tenth of them.

## 6. The static-corpus alternative, costed and constrained

The whole corpus is **2,624 tokens** as one string (§2). Placed in the system
prompt, with `explain_the_report` removed (−186 schema tokens), the cacheable prefix
becomes 697 + 364 + 2,624 = **3,685 tokens** (*computed*), and a corpus question
needs no tool round.

### D. Static corpus in the system prompt, every turn a corpus question (1 call)

| turn | model calls | history before turn (tokens) | warm: input $ | warm: turn $ | cold: input $ | cold: turn $ | cold turn ÷ gate |
|---|---|---|---|---|---|---|---|
| 1 | 1 | 0 | 0.00008 | 0.00022 | 0.00092 | 0.00106 | 2.1× |
| 10 | 1 | 1,125 | 0.00013 | 0.00027 | 0.00120 | 0.00134 | 2.7× |
| 30 | 1 | 3,625 | 0.00018 | 0.00032 | 0.00183 | 0.00197 | 3.9× |
| **30 turns, cumulative** | | | | **0.0084** | | **0.0455** | gate charged **0.0150** |

On cost alone it wins: warm, a corpus-only thread costs 56% of what the gate
charged (against 213% for retrieval, §4A); cold at turn 30 it is 3.9× the gate
against 18×. The price is paid by every thread, including ones that never ask a
corpus question — each turn's first call reads 2,624 more tokens (~$0.00005 warm,
$0.00066 cold) — and the passages lose the retrieval ranking, so "the corpus does
not cover it" (`analyst.py:507-508`) becomes a judgement the model makes over the
whole text rather than an empty result the code returns.

**The constraint the numbers cannot override.** The project's requirement set names
RAG: "agent, LangGraph, RAG, human-in-the-loop, deployed, production-ready"
(`CLAUDE.md`, "Standing conventions"). The retrieval design was decided by
[018/#124](https://github.com/Subaru-Goto/PanelVerdict/issues/124) ("How-to-read-
this-report knowledge base: the RAG the reader actually needs", closed), and
[079](../decisions/079-the-analyst-explains-the-statistics-grounded-in-the-docs.md)
records that 018's 2026-08-21 addendum "now carries the RAG requirement" for the
map, with hybrid `tsvector` + pgvector retrieval folded in on the author's own
request. A static copy in the prompt un-meets that requirement as the author framed
it. This document costs the alternative because the ticket asked for it to be
argued on numbers; it does not recommend it, and the choice is the author's.

## Findings

1. The ticket's mechanism is confirmed from code: `create_agent` with a
   `PostgresSaver`, no trimming or summarising middleware, `add_messages` state —
   every message is replayed on every call (`analyst.py:636-642`,
   `types.py:350`).
2. Three of the ticket's numbers are stale or off: the budget is `CALLS_PER_TURN
   = 5`, not `2 * len(tools) + 2`; the replay bound is 150 calls a day, not "on
   the order of a hundred" per thread lifetime; four passages are 869 tokens on
   the mean (483–1,224), not ~950.
3. The cacheable prefix is 1,247 tokens (697 prompt + 550 schemas) — over the
   1,024 minimum from the first call. Caching fires on every analyst call; the
   measured 80–96% cache share is the warm case.
4. Read live: cache reads $0.02/M, cache **writes $0.25/M** on this model family
   (OpenAI docs and OpenRouter's catalogue agree). The previous derivation priced
   uncached tokens at $0.20/M; the correction is +$0.00002 on the worst low-effort
   turn and does not breach `USD_PER_TURN`.
5. Cache lifetime is 30 minutes after last use (GPT-5.6+). A reader returning
   later pays the write rate on the whole replayed history.
6. Warm, a 30-turn thread of the measured shape bills ~$0.018 against $0.015
   charged (*computed*, conservative). The flat gate's reasoning holds while the
   thread stays warm.
7. Cold, a turn late in a corpus-heavy thread bills 10–18× the gate; a cold
   budget-maximal thread bills $0.62 against $0.015 charged. Nothing measured
   looks like the latter; nothing measured rules out the former.
8. `read_reasons` on a full 200-vote run is 4,739 tokens a result — the largest
   replayed item, five times a passage result.
9. Pruning earlier turns' tool results divides the cold cost by 4–6 and costs the
   design property `analyst.py:5-7` names; the two-kinds rule already forbids the
   reuse that property enables for figures.
10. The installed `create_agent` has no `pre_model_hook`; the hooks are middleware
    (`before_model`, `wrap_model_call`), and `ContextEditingMiddleware` /
    `ClearToolUsesEdit` is the shipped prune-tool-results option.
11. The static-corpus copy is cheapest on every row of the table and un-meets the
    RAG requirement as the author framed it in 018/#124.
12. The quantity that decides between "no change" and "prune" — the share of
    production turns that arrive cold — is already observable from the
    `analyst usage` log line (`cached_tokens` vs `input_tokens`) and has never
    been read for that purpose.

## What this argues for

**One recommendation: no code change now; read the log first, and adopt one
numeric trigger.** The warm case, which is the only case measured, is within ~25%
of what the gate charges over a whole thread, and the day is bounded by count caps
and a $1.00 pool. Adding middleware to fix a cost curve whose steep branch has never
been observed would be a control sized by no measurement. What *is* warranted is cheap: over the next stretch of production use,
read the `analyst usage` lines and record, per turn, `cached_tokens / input_tokens`
and the thread's turn index. If turns with a cache share under ~50% (a cold return
under the model in §3, allowing for the 128-token rounding and a new thread's
first call) make up more than about **10% of turns past turn 5**, the cold branch
is real and the cheapest fix is pruning earlier turns' `ToolMessage`s in a
`before_model` hook — the shipped `ClearToolUsesEdit` with `trigger` set to a few
thousand tokens and `keep` to the current turn's results, or a dozen lines of the
repo's own — which §4 shows cuts the cold cost 4–6× while leaving warm turns
essentially unchanged. If the cold share is below that, the thread is behaving as
`config.py:118-121` assumed and the ticket closes as "measured, no change
warranted."

Why 10%: *computed* from §4B — at a 10% cold share the expected cost of a 30-turn
mixed thread is 0.9 × $0.0184 + 0.1 × $0.0842 ≈ $0.025, 1.7× the gate; below it the
gate's error is the same order as the model's own conservatism, above it the gate
is measurably undercharging. It is a threshold for *acting*, not a measurement; the
author may set it elsewhere.

What would change this recommendation:

- **A price change** — cache reads above ~0.25× input, or writes above 1.25× —
  moves the warm column toward the cold one and makes pruning worth doing on the
  arithmetic alone.
- **A longer thread cap** — `chat_turns_per_thread_per_day` above 30 lengthens the
  history linearly; the cold cost at the cap scales with it.
- **A measurement showing cold returns dominate** — the trigger above.
- **A model change** to one outside the GPT-5.6 family — the minimum becomes 2,048
  (the prefix would no longer cache from the first call) and the lifetime 5–10
  minutes (the `in_memory` default; a `24h` TTL is documented), which makes
  nearly every return cold; re-run §4 before shipping it.
- **Removing `read_reasons`'s full-text result** — it is the largest replayed
  item, and shrinking it would do more for scenario C than pruning passages.

Independently of the decision, [`analyst-turn-cost.md`](analyst-turn-cost.md)
and `docs/least-privilege.md` (Asset 2) carry dated corrections from this branch:
the write rate, and the input-side charge-to-bill ratio. One correction is code
and is not made here: `_TurnUsage` should log `cache_creation` beside
`cache_read` so the write count is observable (recorded on tech-debt #171).

Decision (author, date): —

## Sources

All provider documentation read live 2026-09-02.

- OpenAI, *Prompt caching* — <https://developers.openai.com/api/docs/guides/prompt-caching>
  (`platform.openai.com/docs/guides/prompt-caching` redirects here)
- OpenRouter, *Prompt Caching* — <https://openrouter.ai/docs/features/prompt-caching>
  (machine-readable copy at `…/prompt-caching.md`)
- OpenRouter model catalogue — `GET https://openrouter.ai/api/v1/models`, entry
  `openai/gpt-5.6-luna`
- Ticket [104/#223](https://github.com/Subaru-Goto/PanelVerdict/issues/223);
  [018/#124](https://github.com/Subaru-Goto/PanelVerdict/issues/124);
  [052/#149](https://github.com/Subaru-Goto/PanelVerdict/issues/149);
  [079](../decisions/079-the-analyst-explains-the-statistics-grounded-in-the-docs.md)
- This repo: [`analyst-turn-cost.md`](analyst-turn-cost.md),
  [`prompt-caching.md`](prompt-caching.md), `backend/app/analyst.py`,
  `backend/app/corpus.py`, `backend/app/config.py`, `backend/app/llm.py`,
  `backend/app/main.py`, `backend/app/data/corpus/*.md`,
  `backend/app/data/demo/free-delivery.json`, `backend/tests/test_analyst.py`
  (`_result`), `backend/tests/factories.py` (`make_panel_vote`); `CLAUDE.md`
- Installed packages, `backend/.venv/lib/python3.13/site-packages/`:
  `langchain/agents/factory.py`, `langchain/agents/middleware/{types,summarization,context_editing}.py`,
  `langchain_core/messages/utils.py`, `langchain_openai/chat_models/base.py`,
  `langgraph/prebuilt/chat_agent_executor.py`,
  `langgraph/checkpoint/postgres/base.py`; token counts via `tiktoken` 0.13.0,
  `o200k_base`.
