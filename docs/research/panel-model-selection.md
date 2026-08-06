# Panel model + OpenRouter provider — selection research

Resolves ticket **[003 — Decide panel model + OpenRouter provider config](../../issues/003-decide-panel-model-and-provider.md)**.
Pricing/features verified **live on openrouter.ai, 2026-07-17** (the ticket requires not trusting memory — model catalog + prices shift monthly).

## TL;DR

- **Provider:** OpenRouter. ~~with **prompt caching** on the shared prefix (panel instructions + the two variants) — the main cost lever.~~ **Struck 2026-07-27:** caching cannot fire on this prompt at all — it needs 1,024 tokens (4,096 on Haiku 4.5) and the whole request is ~300–370. See [prompt-caching.md](prompt-caching.md). The cost lever is **output/reasoning tokens and the number of requests**.
- **Panel model (v1 default):** ~~**GPT-5 Mini** (`openai/gpt-5-mini`) — best value that plausibly clears the trait-enactment bar. **Haiku 4.5** (`anthropic/claude-haiku-4.5`) is the drop-in fallback.~~ **Struck 2026-08-05:** the panel now runs **`openai/gpt-5.6-luna`**, on price. OpenRouter's model list (read 2026-08-05) prices it at **$0.10 / $0.60** per Mtok against GPT-5 Mini's $0.25 / $2.00 — a 3.3× cut on output, the dominant term per the line above. `openai/gpt-5.6-luna-pro` is *the same model served with `reasoning.mode=pro`*, so it costs the same per token and emits more of them; plain Luna was chosen first because plan B below says deploy the cheapest that matches enactment, and a pass ends the search. **The enactment half of that plan has not run yet** — everything below about fidelity deciding the model still binds, and [071](../../issues/071-the-panel-model-changed-without-its-gate.md) is the gate. Haiku 4.5 remains the untested fallback.
- **Fidelity benchmark:** **GPT-5.6 Sol** — the manipulation check compares Mini's Big-Five enactment against it; keep Mini if it matches, else fall back.
- **Spend cap:** **$10** per-key credit cap on OpenRouter (hard 402 stop; see handling below).
- **Analyst model:** a **reasoning model** — a separate role/run, so its selection is deferred to **[012](../../issues/012-build-analyst-chatbot-tools.md)** (not this ticket).
- **Final panel model** is confirmed-or-revised by the **manipulation check** (fidelity is a selection criterion, not just cost — Huang et al. 2026).

## Verified pricing (OpenRouter, 2026-07-17)

| Model | Slug | Input $/M | Output $/M | Cache-read $/M | Context | Role |
|---|---|---|---|---|---|---|
| **GPT-5 Mini** | `openai/gpt-5-mini` | 0.25 | 2 | ~0.025 | 400K | **panel (primary)** |
| **Haiku 4.5** | `anthropic/claude-haiku-4.5` | 1 | 5 | 0.10 | 200K | panel (fallback) |
| GPT-5.4 nano | `openai/gpt-5.4-nano` | 0.20 | 1.25 | — | 400K | dev/integration |
| GPT-5.6 Sol | `openai/gpt-5.6-sol` | 5 | 30 | — | 1.05M | fidelity benchmark |
| GPT-5.5 | `openai/gpt-5.5` | 5 | 30 | — | 1M+ | (alt benchmark) |

Both panel candidates support **prompt caching** (cache-read column) and **structured output / tool-calling** (standard for OpenAI + Anthropic; OpenRouter exposes it and offers an "Exacto" tool-accuracy routing mode). The exact param — `response_format` json-schema vs a forced tool-call — is confirmed at build time.

## Measured cost (gpt-5-mini, 2026-07-28)

**20 votes through the shipped vote path** — `collect_panel_votes` against `FIXED_PANEL`, two
reasoning-effort arms of 10 votes each. This replaces the estimate below, which was wrong in
the direction that mattered.

| | default effort | `reasoning_effort=low` |
|---|---|---|
| prompt tokens / vote | 262–283, mean **270.8** | identical (same prompts) |
| output tokens / vote | 184–296, mean **234** | 91–128, mean **108.9** |
| — of which reasoning | 128–192, mean **160** (**68%** of output) | 0–94, mean 47.8 (44%) |
| cached prompt tokens | **0** in 10/10 | **0** in 10/10 |
| cost / vote | **$0.000536** | $0.000286 |
| **cost / 200-vote test** | **$0.107** | $0.057 |
| **tests within the $10 cap** | **~93** | ~175 |
| latency / vote | mean **4.43s**, p95 7.33s | mean 2.47s, p95 4.74s |
| votes failing to parse | 0/10 | 0/10 |

Four things worth reading off this:

**The retracted ~$0.055 was low by about 2×, and output is why.** The old figure assumed ~80
output tokens with no reasoning allowance; the real output is ~234 tokens, of which **68% is
reasoning** — invisible in the response and billed at $2/M. Input was over-estimated at the
same time (270 tokens, not 300–370), but input is a sixth of the bill, so it barely moves.

**The provider's reported `cost` equals the list-price derivation exactly** — bit-for-bit on
20/20 votes, so `cost` is computed from the $0.25/$2 above rather than from anything opaque.
Either number can be planned against, which is what a pre-flight budget check needs.

**Caching is confirmed dead, not merely predicted.** `cached_tokens` read 0 on every vote, and
the measured 270-token prompt is a quarter of OpenAI's 1,024-token minimum — a wider margin
than [prompt-caching.md](prompt-caching.md) derived from published thresholds.

**`reasoning_effort=low` halves the bill** ($0.057 vs $0.107 per test) and cuts latency by 44%,
with no parse failures at this sample size. It is **not adopted**: effort changes what the
panel is, and the measured first-position rate and question-wording sensitivity were both taken
at the default. Adopting it means re-measuring those first.

**Read this as an order of magnitude, not a distribution.** Ten votes per arm cannot support a
p99 — which is the figure a read timeout wants — and the p95s above are over 10 points. The
first full 200-vote run supersedes them.

### The superseded estimate

Assumed, when written: ~1.5k-token cached prefix, ~300-token per-persona input, ~80-token vote output.

| Model | ≈ cost / 200-persona test | Relative |
|---|---|---|
| **GPT-5 Mini** | ~~~$0.055~~ → **$0.107 measured** | 1× |
| Haiku 4.5 | ~$0.17 (unmeasured) | ~3× |
| GPT-5.6 Sol (flagship) | ~$1.00 (unmeasured) | ~18× |

Only the first row has been measured. The other two remain list-price estimates built on the
same wrong output assumption, so expect them to be low by a similar factor; the **ranking** is
unaffected, since it follows list prices that have not changed.

GPT-5 Mini is cheaper than Haiku on **every** axis (4× input, 2.5× output, 4× cache) with **2× the context** — the clear value pick, contingent on fidelity.

### What is actually known about the cost, and what is not

**Resolved by the measurement above.** Both halves of this section were right about the shape
and wrong about the size.

**Input** came in at 270 tokens/vote rather than 300–370, so ~54K tokens per test ≈ **$0.0135**.
The conclusion holds and strengthens: a perfect cache would save about a penny.

**Output was indeed the term that mattered.** It is ~234 tokens/vote against the assumed ~80,
and 68% of it is reasoning — so the output side is **$0.094 per test**, seven times the input
side. That single correction accounts for nearly all of the gap between ~$0.055 and $0.107.

**"$10 cap ≈ ~180 full tests" was roughly double the truth: it is ~93** at default effort. That
figure is now safe to plan against, and it is what a pre-flight budget check can compare
`limit_remaining` to.

One trap found while wiring this up, worth knowing before anyone touches the effort parameter:
passing langchain's `reasoning={"effort": ...}` object switches the call to the **Responses
API**, whose response carries no `token_usage` and therefore **no cost at all**. `reasoning_effort`
is the form that stays on Chat Completions. The first version of the low arm was measured
against the wrong endpoint and had to be thrown away.

## Cost vs fidelity — why not just the cheapest, and why not flagship

The panel runs ~200×/test (plus reruns for reproducibility QA + dev iteration), so its per-token price is the dominant cost. But trait enactment is **model-dependent** — weak models (GPT-3.5-era) barely enact Big Five; frontier models do it well (Huang, Zhang, Soto & Evans 2026). A cheap model that enacts *badly* is worth zero regardless of price. Resolution (plan **B**): **benchmark a flagship, deploy the cheapest model that matches its enactment.** GPT-5 Mini is far beyond the GPT-3.5 that failed, so it likely passes — but the **manipulation check decides**, not assumption. Flagship-on-the-panel (~18× cost) is reserved as the benchmark, not the runtime.

## Dev vs run — model tiering (config-driven)

Building the pipeline needs many iterations that don't test output *quality*, only that data flows. So:

1. **Plumbing / logic / CI** → a **stub** returning a canned structured vote. Free, instant, deterministic; doubles as a test fixture.
2. **Integration path** (real OpenRouter auth + structured-output parsing + caching) → **GPT-5-family nano** (~$0.20/$1.25) — same OpenAI structured-output stack as Mini, so behavior transfers.
3. **Real runs / quality** → **GPT-5 Mini**.

**Rules:** the panel model is a **config setting** (never hardcoded), so dev↔run is one env change; and a **dev model tests plumbing, never quality** — the manipulation check + any fidelity eval must run on Mini.

## Spend cap behaviour (verified from OpenRouter docs)

The $10 is a **per-key credit cap**. On exhaustion the next request returns **HTTP 402** and is **rejected** — no overage, a true hard stop. `GET /api/v1/key` returns `limit`, `limit_remaining`, `usage` for **proactive monitoring**. Resolve by raising the cap / adding credits / waiting for a configured reset. (Distinct from **429** rate-limit errors, which are transient → retry with backoff.)

**System handling (so a cap-hit is boring, not corrupting):**
1. **Pre-flight check** — read `limit_remaining`, estimate run cost (personas × per-vote); refuse/warn up front if it won't fit.
2. **Graceful mid-run stop** — catch 402, halt cleanly, mark the run **partial**; never emit a half-panel as a finished verdict.
3. **Resumable via per-vote caching** — with the `(persona, test, order)→vote` cache from ticket 002, top-up-and-resume reuses completed votes and fetches only the missing ones.

## Open item

The **final panel model** is confirmed (keep GPT-5 Mini) or revised (→ Haiku 4.5 → escalate) by the **manipulation-check** fidelity result, run on the real model. Until then GPT-5 Mini is the working default.

## Sources

- OpenRouter model pages (pricing/caching/context, 2026-07-17): `openrouter.ai/openai/gpt-5-mini`, `openrouter.ai/anthropic/claude-haiku-4.5`, `openrouter.ai/models?q=gpt-5`.
- OpenRouter limits docs (402/429 behaviour, `GET /api/v1/key`): `openrouter.ai/docs/api-reference/limits`.
- Huang, Zhang, Soto & Evans (2026), *Personality Science* — model-dependent Big-Five enactment; BFI-2-Expanded rendering.
