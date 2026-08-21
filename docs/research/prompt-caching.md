# Prompt caching — can it fire on a vote prompt?

Checks the claim in [003 — Decide panel model + OpenRouter provider config](../decisions/003-decide-panel-model-and-provider.md),
restated in [`panel-model-selection.md`](panel-model-selection.md): that **prompt
caching on the shared prefix (panel instructions + the two variants) is "the main
cost lever"**.

All provider documentation read **live, 2026-07-27**. Quotes are verbatim; anything
labelled *inferred* or *computed* is this document's own reasoning over those
quotes, not a provider statement. No paid API calls were made — pricing came from
OpenRouter's public `GET /api/v1/models` and OpenAI's published pricing page, and
the token counts below were measured locally.

## Bottom line

**No. Prompt caching cannot fire on the current vote prompt, for either model, and
it is not the main cost lever.** Two reasons. The first is a hard provider constraint
and settles it on its own; the second is a property of our code, which we could change
but which means caching would not fire *even if* the prompt were long enough:

1. **Too short.** OpenAI caches only prompts of **1,024 tokens or more**; Claude
   Haiku 4.5 needs **4,096**. The vote request is ~171 tokens of messages plus
   ~130–200 tokens of JSON schema — roughly **300–370 tokens**, a third of the
   OpenAI minimum and under a tenth of Haiku's.
2. **Wrong order** — fixable in principle, but not worth fixing. Caching matches the
   *longest common prefix*, and `build_vote_messages` puts the **persona** (the part
   that differs per request) in the *system* message, ahead of the shared options and
   instructions in the *human* message. Across the ~200 requests of a run the common
   prefix is only the structured-output schema. Reordering is a code change, not a
   constraint — but on its own it buys nothing, because reason 1 still applies.

**What size would be needed** (for gpt-5-mini): a **shared, identical, request-leading
prefix of ≥1,024 tokens** — i.e. the two variants and instructions would have to be
moved *ahead* of the persona *and* grow past 1,024 tokens. For
`anthropic/claude-haiku-4.5` the same prefix would need **≥4,096 tokens** plus an
explicit `cache_control` breakpoint. Neither is a natural shape for this prompt.

**Computed** from the sourced prices below: 200 votes × ~300–370 input tokens
(messages *plus* the schema, which §4 confirms is billed per request) ≈ 60–74K tokens
≈ **$0.015–0.019** per run at gpt-5-mini's $0.25/M. Even a *perfect* 0.1× cache read
would therefore save **under 2¢ per run**, which is the number that settles whether
this is worth chasing.

**The output side is not computed here, because it cannot be.** gpt-5-mini is a
reasoning model, so reasoning tokens bill at the output rate ($2/M) and never appear
in the response. Any output figure would have to come from `usage`, and nothing in
this repo has ever logged it — 014 and 015 ran ~7,000 votes between them and recorded
no spend. So: input is small and now known; output is unknown and is the term that
decides the bill. **The cost lever is output/reasoning tokens and the number of
requests, not input caching** — that direction follows from the $2/M vs $0.25/M rates
alone, without needing a ratio.

## 1. OpenRouter prompt caching, OpenAI models

Source: <https://openrouter.ai/docs/features/prompt-caching> (read 2026-07-27; the
machine-readable copy at `.../prompt-caching.md` was used for exact text).

Automatic, no breakpoints needed:

> Prompt caching with OpenAI is automated and does not require any additional
> configuration. There is a minimum prompt size of 1024 tokens.

> Most providers automatically enable prompt caching, but note that some (see
> Alibaba and Anthropic below) require you to enable it on a per-message basis.

Cost:

> * **Cache writes**: no cost on models before the GPT-5.6 family. GPT-5.6 and later
>   charge cache writes at 1.25x the price of the original input pricing, even with
>   automatic caching — no opt-in required.
> * **Cache reads**: (depending on the model) charged at 0.25x or 0.50x the price of
>   the original input pricing

⚠️ That 0.25x/0.50x range does **not** match `gpt-5-mini`'s actual published
numbers, which are **0.1x** — see §2. OpenRouter's own catalogue agrees with OpenAI,
not with its own prose: `GET https://openrouter.ai/api/v1/models` returns for
`openai/gpt-5-mini` `"prompt": "0.00000025"`, `"input_cache_read": "0.000000025"`
and **no** `input_cache_write` field at all (read 2026-07-27). *Inferred:* cache
reads are 0.1× input and cache writes are free on gpt-5-mini, consistent with
"no cost on models before the GPT-5.6 family".

TTL: OpenRouter states a TTL only for the *explicit* (GPT-5.6+) path —

> Explicit prompt caching works on both the Chat Completions and Responses APIs …
> Cached prefixes have a minimum 30-minute TTL.

and gates it:

> OpenAI explicit prompt caching is only supported by OpenAI GPT-5.6 and newer.

*Not confirmable from OpenRouter:* the automatic-cache TTL for a pre-5.6 model like
`gpt-5-mini`. OpenAI's own doc gives it — see §2.

Also relevant, since ~200 requests fan out concurrently:

> After a request that uses prompt caching, OpenRouter remembers which provider
> served your request.

> Sticky routing is tracked at the account level, per model, and per conversation.
> By default, OpenRouter identifies conversations by hashing the first system (or
> developer) message and the first non-system message in each request, so requests
> that share the same opening messages are routed to the same provider.

*Inferred:* because the current design varies the **first system message** per
persona, OpenRouter's default sticky-routing key differs for every one of the ~200
requests, so they are not even guaranteed to land on the same provider endpoint.
`session_id` / `prompt_cache_key` would be needed to pin them.

## 2. OpenAI's own prompt caching docs

Source: <https://developers.openai.com/api/docs/guides/prompt-caching> (read
2026-07-27; `platform.openai.com/docs/guides/prompt-caching` 301-redirects here).

Threshold, stated twice:

> By default, caching is enabled automatically for prompts that are 1024 tokens or
> longer.

> Caching is available for prompts containing 1024 tokens or more.

> All requests, including those with fewer than 1024 tokens, display a
> `cached_tokens` field in the usage token details. … For requests under 1024
> tokens, `cached_tokens` is zero.

**Increment / granularity — not confirmable.** Earlier revisions of this guide
described caching in 128-token increments above 1,024. The current page contains no
such statement; `grep -i '128\|increment\|granular'` over the full page text returns
nothing. Do not carry a 128-token increment claim without re-sourcing it. What the
page *does* give is the routing hash granularity, which is a different thing:

> Requests are routed to a machine based on a hash of the initial prefix of the
> prompt. The hash typically uses the first 256 tokens, though the exact length
> varies depending on the model.

What portion is matched:

> **Cache Lookup**: The system checks if the initial portion (prefix) of your prompt
> exists in the cache on the selected machine.

Model coverage — this is the gpt-5-family confirmation:

> It is enabled for all recent [models](https://developers.openai.com/api/docs/models),
> `gpt-4o` and newer.

`gpt-5-mini` specifically has a published cached-input price, which is the concrete
confirmation that caching applies to it. From
<https://developers.openai.com/api/docs/pricing> (read 2026-07-27), standard tier,
"Prices per 1M tokens", row: `["gpt-5-mini", 0.25, 0.025, 2]` — input **$0.25**,
cached input **$0.025**, output **$2**. So **cache read = 0.1× input** for
gpt-5-mini.

TTL / eviction. gpt-5-mini is *not* in the GPT-5.6+ family and *not* in the
extended-retention list (`gpt-5.5`, `gpt-5.4`, `gpt-5.2`, `gpt-5.1*`, `gpt-5`,
`gpt-5-codex`, `gpt-4.1` — `gpt-5-mini` is absent), so the applicable text is:

> When using the in-memory policy, cached prefixes generally remain active for 5 to
> 10 minutes of inactivity, up to a maximum of one hour. In-memory cached prefixes
> are only held within volatile GPU memory.

> For models before the GPT-5.6 family that use in-memory retention, typical cache
> evictions occur after 5-10 minutes of inactivity, though entries can remain for up
> to one hour during off-peak periods.

(For contrast, GPT-5.6+ : "A cached prefix remains eligible for reuse for at least
30 minutes, but OpenAI may retain it longer." — the number OpenRouter quotes.)

Cache writes free on this model:

> Cache writes have no additional fee on models before the GPT-5.6 family.

## 3. Ordering requirement — longest common prefix

> Cache hits are only possible for exact prefix matches within a prompt. To realize
> caching benefits, place static content like instructions and examples at the
> beginning of your prompt, and put variable content, such as user-specific
> information, at the end. This also applies to images and tools, which must be
> identical between requests.

> Structure prompts with **static or repeated content at the beginning** and
> dynamic, user-specific content at the end.

> When several breakpoints match cached content, the service reads from the longest
> matching prefix.

Anthropic states the same requirement:

> Place static content (tool definitions, system instructions, context, examples) at
> the beginning of your prompt. Mark the end of the reusable content for caching
> using the `cache_control` parameter.

> Because the hash is cumulative, covering everything up to and including the
> breakpoint, changing any block at or before the breakpoint produces a different
> hash on the next request.

(<https://platform.claude.com/docs/en/build-with-claude/prompt-caching>, read
2026-07-27.)

**Consequence for this codebase.** `backend/app/llm.py:52` returns
`[SystemMessage(content=system_prompt), HumanMessage(content=task)]` — the persona
first, the shared options + question + `_ANSWER_INSTRUCTION` second. *Inferred, but
directly from the quotes above:* the shared block sits **after** the variable block,
so it is never part of a common prefix. Across a 200-persona run the longest common
prefix is whatever precedes the system message — i.e. the structured-output schema
alone.

## 4. What counts toward the prefix and the minimum

OpenAI enumerates this explicitly:

> ### What can be cached
>
> - **Messages:** The complete messages array, encompassing system, user, and
>   assistant interactions.
> - **Images:** Images included in user messages, either as links or as
>   base64-encoded data, as well as multiple images can be sent. Ensure the detail
>   parameter is set identically, as it impacts image tokenization.
> - **Tool use:** Both the messages array and the list of available `tools` can be
>   cached, contributing to the minimum 1024 token requirement.
> - **Structured outputs:** The structured output schema serves as a prefix to the
>   system message and can be cached.

So both answers are yes: the whole messages array in order participates, and **tool
definitions and structured-output schemas both participate and both count toward the
1,024-token minimum**. The schema sits **before** the system message in the request
ordering.

Anthropic's ordering is stated as an explicit hierarchy:

> Prompt caching references the entire prompt - `tools`, `system`, and `messages`
> (in that order) up to and including the block designated with `cache_control`.

> the cache follows the hierarchy: `tools` → `system` → `messages`. Changes at each
> level invalidate that level and all subsequent levels.

and its cacheable list includes "Tools: Tool definitions in the `tools` array" and
"System messages: Content blocks in the `system` array".

### What this project actually sends, and how big it is

*Measured locally, 2026-07-27, no API call.* `ChatOpenAI.with_structured_output`
defaults to `method="json_schema"`, **not** function calling —
`.venv/lib/python3.13/site-packages/langchain_openai/chat_models/base.py:3519`:

```python
method: Literal["function_calling", "json_mode", "json_schema"] = "json_schema",
```

(The `BaseChatOpenAI` override at line 2315 defaults to `"function_calling"`, but
`app/llm.py` uses `ChatOpenAI`, which is the subclass at line 2612 and wins.) So
`PanelVoteOutput` travels as `response_format: {"type": "json_schema", ...}` — the
"Structured outputs" bullet above, not the "Tool use" bullet.

Token counts, `tiktoken` `o200k_base` over the exact JSON the OpenAI SDK serialises
(`openai.lib._parsing._completions.type_to_response_format_param(PanelVoteOutput)`):

| payload | tokens |
|---|---|
| `response_format` JSON, compact separators | **127** |
| `response_format` JSON, `indent=2` | **198** |
| messages (system persona + human task), per the ticket | ~171 |
| **total, generously** | **~300–370** |

⚠️ *Caveat:* OpenAI does not document how it renders or tokenises the schema
internally, so 127–198 is the token count of the JSON **as sent**, not a provider
figure for what lands in the prefix. It is the right order of magnitude for a
feasibility check and nothing more.

**So the schema does not rescue the threshold.** It is the only shared prefix in the
current ordering, and at ~130–200 tokens it is ~13–19% of the 1,024 needed. The
combined request is still under 40% of the minimum.

## 5. anthropic/claude-haiku-4.5 (documented fallback)

Both OpenRouter and Anthropic state 4,096 tokens for this model.

OpenRouter (<https://openrouter.ai/docs/features/prompt-caching>):

> ### Minimum token requirements
>
> Each model has a minimum cacheable prompt length (see Anthropic's cache
> limitations):
>
> * **4,096 tokens**: Claude Opus 4.8, Claude Opus 4.7, Claude Opus 4.6, Claude Opus
>   4.5, Claude Haiku 4.5
> * **2,048 tokens**: Claude Haiku 3.5
> * **1,024 tokens**: Claude Sonnet 4.6, Claude Sonnet 4.5, Claude Opus 4.1, Claude
>   Opus 4, Claude Sonnet 4
>
> Prompts shorter than these minimums will not be cached.

Anthropic (<https://platform.claude.com/docs/en/build-with-claude/prompt-caching#cache-limitations>):

> On the Claude API, Claude Platform on AWS, Google Cloud, and Microsoft Foundry, the
> minimum cacheable prompt length is:
>
> * 512 tokens for Claude Opus 5, Claude Fable 5, and Claude Mythos 5
> * 2,048 tokens for Claude Mythos Preview and Claude Opus 4.7
> * 4,096 tokens for Claude Opus 4.6 and Claude Opus 4.5
> * 1,024 tokens for Claude Opus 4.8, Claude Sonnet 5, Claude Sonnet 4.6, Claude
>   Sonnet 4.5, Claude Opus 4.1 …, Claude Opus 4 …, and Claude Sonnet 4
> * **4,096 tokens for Claude Haiku 4.5**
> * 2,048 tokens for Claude Haiku 3.5 …
>
> These minimums apply on every platform where each model is available.

Yes, the minimums differ per model, by a factor of 8 across the range (512 → 4,096),
and **Haiku 4.5 sits at the worst end**. Note the two lists disagree on Opus 4.7 and
Opus 4.8 — Anthropic's own page is authoritative — but they agree exactly on Haiku
4.5, which is the one this project cares about.

Failure mode is silent:

> Shorter prompts cannot be cached, even if marked with `cache_control`. Any requests
> to cache fewer than this number of tokens will be processed without caching, and no
> error is returned. To verify whether a prompt was cached, check the response usage
> fields: if both `cache_creation_input_tokens` and `cache_read_input_tokens` are 0,
> the prompt was not cached (likely because it did not meet the minimum length
> requirement).

Explicit opt-in is required — there is no purely-automatic Anthropic path:

> There are two ways to enable prompt caching with Anthropic:
>
> * **Automatic caching**: Add a single `cache_control` field at the top level of your
>   request. The system automatically applies the cache breakpoint to the last
>   cacheable block and advances it forward as conversations grow. …
> * **Explicit cache breakpoints**: Place `cache_control` directly on individual
>   content blocks for fine-grained control over exactly what gets cached. There is a
>   limit of four explicit breakpoints.

*Note:* Anthropic's "automatic caching" still requires sending a `cache_control`
field — it only automates *where* the breakpoint goes, not whether caching is on.
This is a real difference from OpenAI, where nothing at all is sent.

Pricing (Anthropic's table, and OpenRouter's catalogue agrees:
`"prompt": "0.000001"`, `"input_cache_read": "0.0000001"`,
`"input_cache_write": "0.00000125"`, `"input_cache_write_1h": "0.000002"`):

| Claude Haiku 4.5 | Base input | 5m cache write | 1h cache write | Cache hits | Output |
|---|---|---|---|---|---|
| $/MTok | $1 | $1.25 | $2 | $0.10 | $5 |

> By default, the cache expires after 5 minutes, but you can extend this to 1 hour by
> specifying `"ttl": "1h"` in the `cache_control` object.

One more trap if caching is ever revisited with 200 parallel requests:

> For concurrent requests, note that a cache entry only becomes available after the
> first response begins. If you need cache hits for parallel requests, wait for the
> first response before sending subsequent requests.

*Inferred:* with a `--workers 8`-style fan-out, the first batch of concurrent
requests would all miss and all pay cache-write price. A warm-up request would be
required first.

## What this settles for ticket 003

- The line "**with prompt caching** on the shared prefix (panel instructions + the
  two variants) — the main cost lever" in
  [`panel-model-selection.md`](panel-model-selection.md) is **wrong at this prompt
  size** and should be struck or rewritten.
- The cost table in that document assumes "a ~1.5k-token cached prefix, ~300-token
  per-persona input". Neither figure describes the shipped prompt: the whole request
  is ~300–370 tokens, and no part of it is cached. Its per-test cost estimates need
  redoing on uncached input + output/reasoning tokens.
- **Do not** restructure the prompt to chase caching. Moving the shared options ahead
  of the persona would break the design property that
  [`manipulation-check.md`](manipulation-check.md) relies on (persona in the system
  turn, task in the human turn), and it still would not reach 1,024 tokens. Padding a
  prompt to 1,024 tokens to unlock a 0.1× read on ~1¢/run is a net loss.
- If input cost ever does matter (much longer personas, or a many-variant test), the
  preconditions are: shared content first, ≥1,024 tokens of it for gpt-5-mini,
  a stable `prompt_cache_key` (or OpenRouter `session_id`) so the ~200 requests pin to
  one endpoint, one warm-up request before the fan-out, and `cached_tokens` /
  `cache_write_tokens` logged from `prompt_tokens_details` to prove it is actually
  firing.

## It does fire on the *targeting* prompt (observed 2026-07-31)

This document's scope is the vote prompt, and its conclusion holds there. But the
same account, model and endpoint **do** cache on the targeting call: every
translation measured in
[targeting-call-effort.md](targeting-call-effort.md) reports `prompt_tokens`
≈ 1,355–1,362 with `cached_tokens` ≈ 1,280.

Nothing above is wrong — reason 1 is a threshold, and the target prompt simply
clears it where the vote prompt cannot. The target system prompt enumerates the
whole attribute vocabulary and carries a larger structured-output schema, which
puts it over 1,024 tokens; the vote request is ~300–370.

Worth stating because the shorthand "prompt caching cannot fire" has travelled
into [003](../decisions/003-decide-panel-model-and-provider.md) and
[008](../decisions/008-build-panel-evaluation.md) without the qualifier, and it is
only true of votes. It does not change the cost picture much — the targeting call
is one request per run against ~200 votes — but a future reader deriving a cost
model from those tickets should know which path the claim covers.

## Sources

All read 2026-07-27.

- OpenRouter, *Prompt Caching* — <https://openrouter.ai/docs/features/prompt-caching>
- OpenRouter model catalogue (pricing fields) — `GET https://openrouter.ai/api/v1/models`
- OpenAI, *Prompt caching* — <https://developers.openai.com/api/docs/guides/prompt-caching>
  (`platform.openai.com/docs/guides/prompt-caching` redirects here)
- OpenAI, *Pricing* — <https://developers.openai.com/api/docs/pricing>
- Anthropic, *Prompt caching* — <https://platform.claude.com/docs/en/build-with-claude/prompt-caching>
  (minimums at `#cache-limitations`)
- Local, this repo: `backend/app/llm.py`, `backend/app/schemas.py`,
  `langchain_openai/chat_models/base.py:3519`; token counts via `tiktoken` `o200k_base`.
