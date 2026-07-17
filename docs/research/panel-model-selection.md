# Panel model + OpenRouter provider — selection research

Resolves ticket **[003 — Decide panel model + OpenRouter provider config](../../issues/003-decide-panel-model-and-provider.md)**.
Pricing/features verified **live on openrouter.ai, 2026-07-17** (the ticket requires not trusting memory — model catalog + prices shift monthly).

## TL;DR

- **Provider:** OpenRouter, with **prompt caching** on the shared prefix (panel instructions + the two variants) — the main cost lever.
- **Panel model (v1 default):** **GPT-5 Mini** (`openai/gpt-5-mini`) — best value that plausibly clears the trait-enactment bar. **Haiku 4.5** (`anthropic/claude-haiku-4.5`) is the drop-in fallback.
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

## Cost analysis (200-persona test, shared prefix cached)

Assumes ~1.5k-token cached prefix, ~300-token per-persona input, ~80-token vote output:

| Model | ≈ cost / 200-persona test | Relative |
|---|---|---|
| **GPT-5 Mini** | **~$0.055** | 1× |
| Haiku 4.5 | ~$0.17 | ~3× |
| GPT-5.6 Sol (flagship) | ~$1.00 | ~18× |

GPT-5 Mini is cheaper than Haiku on **every** axis (4× input, 2.5× output, 4× cache) with **2× the context** — the clear value pick, contingent on fidelity. At ~5.5¢/test, the **$10 cap ≈ ~180 full tests**.

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
