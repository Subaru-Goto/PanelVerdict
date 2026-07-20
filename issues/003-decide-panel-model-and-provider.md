---
title: "Decide panel model + OpenRouter provider config"
labels: [wayfinder:research]
parent: 000-map
blocked_by: []
assignee: subaru
status: closed
---

## Question

Which **single cheap model** (Haiku / 4o-mini / Gemini Flash class) via OpenRouter for the v1 panel, and what provider config?

Verify (current pricing/limits — don't trust memory):
- prompt-caching availability through OpenRouter for the chosen model (the shared instructions+variants prefix is the main cost lever),
- structured-output / forced-function-call support,
- per-key **spend cap** as a hard budget brake.
- **trait-enactment fidelity on the cheap model** — Big Five enactment is model-dependent (frontier models ≫ GPT-3.5; Huang et al. 2026). Verify the chosen cheap model actually enacts Big Five (the manipulation check will also expose this); personality fidelity is a selection criterion, not just cost.

Rule: pick ONE consistent model and never mix models within a run.

**Answer records:** the chosen model id, the provider config, and the spend cap set.

---

## Resolution (2026-07-17)

Full research + live pricing: [`docs/research/panel-model-selection.md`](../docs/research/panel-model-selection.md) (verified on openrouter.ai, 2026-07-17).

- **Provider:** OpenRouter, **prompt caching** on the shared prefix (panel instructions + the two variants) — the main cost lever.
- **Panel model id (v1 default):** `openai/gpt-5-mini` — best value that plausibly clears trait enactment (≈ $0.25/$2 per M, cache-read ≈ $0.025/M, 400K ctx). Fallback: `anthropic/claude-haiku-4.5` ($1/$5, cache-read $0.10/M).
- **Structured output:** supported on both (exact param — `response_format` json-schema vs forced tool-call — confirmed at build).
- **Cost:** GPT-5 Mini ≈ **$0.055 / 200-persona test** (~⅓ of Haiku, ~1/18 of flagship).
- **Fidelity benchmark:** `openai/gpt-5.6-sol` — the **manipulation check** compares Mini's Big-Five enactment against it and confirms-or-revises the final pick (plan **B**: benchmark flagship, deploy cheapest that passes). Fidelity is a selection criterion, not just cost (Huang et al. 2026).
- **Spend cap:** **$10** per-key credit cap. On exhaustion → **HTTP 402**, requests rejected, no overage. Handle via: pre-flight `GET /api/v1/key` budget check, graceful mid-run stop (mark run **partial**, never emit a half-panel), and resume-after-top-up via the per-vote cache (ticket 002). Distinct from 429 rate-limit (retry w/ backoff).
- **Dev vs run (config-driven):** **stub** (free, CI/plumbing) → **GPT-5-family nano** (integration path) → **GPT-5 Mini** (real runs). Panel model is a **config setting**, never hardcoded; a dev model tests plumbing, never quality.
- **Rule held:** one consistent model per panel run.
- **Analyst model:** a **reasoning model** — separate role/run, so its selection is deferred to **[012](012-build-analyst-chatbot-tools.md)** (not this ticket). Using a different model for the analyst does not violate the one-model-per-run rule.

**Downstream:** final model confirmation → manipulation check (005/006/008-era); 402 handling + resumable caching → orchestration (005/008); analyst reasoning-model pick → 012.

## Finding (2026-07-19, from the 005 build) — chosen model rejects `temperature`

`openai/gpt-5-mini` is a GPT-5 reasoning model and accepts **only the default `temperature=1`**; any other value returns **HTTP 400** ("Unsupported value: 'temperature' does not support 0 with this model"). The panel client therefore must **not send `temperature`** at all.

Consequence: the `temperature≈0` per-persona-determinism lever assumed in [002](002-decide-vote-schema.md) is **unavailable** for this model — see the 002 reproducibility amendment. Reproducibility now rests on the seeded population (002's primary variance source), best-effort `seed`, and per-vote caching (008). **Any future model swap must re-check parameter support** (temperature/seed) as a selection criterion, alongside cost + trait fidelity.