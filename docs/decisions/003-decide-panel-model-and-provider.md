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

Full research + live pricing: [`docs/research/panel-model-selection.md`](../research/panel-model-selection.md) (verified on openrouter.ai, 2026-07-17).

- **Provider:** OpenRouter. ~~**prompt caching** on the shared prefix (panel instructions + the two variants) — the main cost lever.~~ **Struck 2026-07-27 — see the amendment below.**
- **Panel model id (v1 default):** `openai/gpt-5-mini` — best value that plausibly clears trait enactment (≈ $0.25/$2 per M, cache-read ≈ $0.025/M, 400K ctx). Fallback: `anthropic/claude-haiku-4.5` ($1/$5, cache-read $0.10/M).
- **Structured output:** supported on both (exact param — `response_format` json-schema vs forced tool-call — confirmed at build).
- **Cost:** GPT-5 Mini is ~⅓ of Haiku and ~1/18 of flagship — the *ranking* holds. The ≈ $0.055 / 200-persona test figure does not: **measured at $0.107** on 2026-07-28, because vote output is ~3× the assumed size and two thirds of it is reasoning. That leaves **~93 tests inside the $10 cap**, not ~180 — see the measurement below.
- **Fidelity benchmark:** `openai/gpt-5.6-sol` — the **manipulation check** compares Mini's Big-Five enactment against it and confirms-or-revises the final pick (plan **B**: benchmark flagship, deploy cheapest that passes). Fidelity is a selection criterion, not just cost (Huang et al. 2026). **Answered 2026-07-26 ([014](014-targeting-manipulation-check.md), [results](../research/manipulation-check.md)):** Mini enacts Big Five *in behaviour* — 32.5% of votes change against a ~11% noise floor, with clean negative controls — which is the specific thing Han et al. 2025 found persona injection failing to do. Mini stays. The flagship comparison is no longer needed to establish that traits work; it would only rank fidelity.
- **Spend cap:** **$10** per-key credit cap. On exhaustion → **HTTP 402**, requests rejected, no overage. Handle via: pre-flight `GET /api/v1/key` budget check, graceful mid-run stop (mark run **partial**, never emit a half-panel), and resume-after-top-up via the per-vote cache (ticket 002). Distinct from 429 rate-limit (retry w/ backoff).
- **Dev vs run (config-driven):** **stub** (free, CI/plumbing) → **GPT-5-family nano** (integration path) → **GPT-5 Mini** (real runs). Panel model is a **config setting**, never hardcoded; a dev model tests plumbing, never quality.
- **Rule held:** one consistent model per panel run.
- **Analyst model:** a **reasoning model** — separate role/run, so its selection is deferred to **[012](012-build-analyst-chatbot-tools.md)** (not this ticket). Using a different model for the analyst does not violate the one-model-per-run rule.

**Downstream:** final model confirmation → manipulation check (005/006/008-era); 402 handling + resumable caching → orchestration (005/008); analyst reasoning-model pick → 012.

## Finding (2026-07-19, from the 005 build) — chosen model rejects `temperature`

`openai/gpt-5-mini` is a GPT-5 reasoning model and accepts **only the default `temperature=1`**; any other value returns **HTTP 400** ("Unsupported value: 'temperature' does not support 0 with this model"). The panel client therefore must **not send `temperature`** at all.

Consequence: the `temperature≈0` per-persona-determinism lever assumed in [002](002-decide-vote-schema.md) is **unavailable** for this model — see the 002 reproducibility amendment. Reproducibility now rests on the seeded population (002's primary variance source), best-effort `seed`, and per-vote caching (008). **Any future model swap must re-check parameter support** (temperature/seed) as a selection criterion, alongside cost + trait fidelity.
## Amended 2026-07-27 (008) — prompt caching cannot fire, and the cost estimate rests on it

Checked against provider documentation while building [008](008-build-panel-evaluation.md),
whose second bullet asks for a shared prefix for exactly this reason. Findings and every
quote: [`docs/research/prompt-caching.md`](../research/prompt-caching.md).

**Caching cannot fire on the vote prompt, for either model, for two independent reasons.**

1. **Too short.** OpenAI caches only prompts of **1,024 tokens or more** ("Caching is
   available for prompts containing 1024 tokens or more"); `claude-haiku-4.5` needs
   **4,096**, the worst end of Anthropic's per-model range. A vote request is ~171 tokens
   of messages plus a 127–198-token structured-output schema — **~300–370 tokens**, about
   a third of the OpenAI minimum. The schema does count toward the minimum, and it still
   does not close the gap.
2. **Wrong order, and unfixable at this size.** Caching matches an exact *prefix*, so
   static content must lead. `build_vote_messages` puts the **persona** — the part that
   differs every request — in the system message ahead of the shared options. The shared
   block is therefore never in a common prefix.

**Decision: do not restructure the prompt.** Moving the options ahead of the persona
would break the persona-in-system / task-in-human split that [014](014-targeting-manipulation-check.md)
and [015](015-task-framing-sensitivity.md) measured against, changing what the panel *is*
for a saving that is bounded above by **under 2¢ per test** — and it would still not reach
1,024 tokens. Padding a prompt to hit a threshold in order to win a 0.1× read on 2¢ is a
net loss twice over.

**The consequence for the spend cap is the part that matters** — and it has now been
measured, so this stops being a warning and becomes a number.

## Measured 2026-07-28 — $0.107 per test, ~93 tests inside the cap

20 votes through the shipped vote path, at two reasoning-effort arms. Full readings in
[`panel-model-selection.md`](../research/panel-model-selection.md); what this ticket
needs:

| | default effort | `reasoning_effort=low` |
|---|---|---|
| cost / 200-vote test | **$0.107** | $0.057 |
| **tests inside the $10 cap** | **~93** | ~175 |
| latency / vote | mean 4.43s, p95 7.33s | mean 2.47s, p95 4.74s |

**The suspicion above was right, and about 2× is the size of it.** ~$0.055 becomes **$0.107**,
because output is ~234 tokens per vote rather than the assumed ~80 and **68% of it is
reasoning** — invisible in the response, billed at $2/M. So *"$10 cap ≈ ~180 full tests"* was
roughly double: it is **~93**.

**The pre-flight check now has something real to compare against.** OpenRouter's reported
`cost` matched the list-price derivation *exactly* on 20/20 votes, so `limit_remaining` and an
estimate built from $0.25/$2 are in the same units and either can be used.

**Prompt caching is confirmed dead by observation**, not only by threshold arithmetic:
`cached_tokens` read 0 on every vote, and the measured prompt is 270 tokens against a
1,024-token minimum.

**A read timeout still cannot be set from this.** 10 votes per arm gives a p95 over ten points
and no p99 at all, which is the figure that matters for cutting off a hung request. The first
full 200-vote run supplies it.

**`reasoning_effort=low` halves the bill and is deliberately not adopted.** Effort changes what
the panel is, and both [014](014-targeting-manipulation-check.md)'s first-position rate and
[015](015-task-framing-sensitivity.md)'s framing sensitivity were measured at the default.
Adopting it means re-measuring those first — a separate decision with its own spend.

**One wiring trap, recorded because it silently costs the cost figure.** langchain's
`reasoning={"effort": ...}` object switches the call to the **Responses API**, which returns no
`token_usage` and therefore no `cost`. `reasoning_effort=` is the form that stays on Chat
Completions. The low arm was first measured against the wrong endpoint and discarded.

**If input cost ever does matter** (much longer personas, a many-variant test), the
preconditions are all recorded in the research doc: shared content first, ≥1,024 tokens of
it, a stable `prompt_cache_key` so the fan-out pins to one endpoint, one warm-up request
before the fan-out (a cache entry only exists after the first response begins, so 25
concurrent cold requests all miss), and `cached_tokens` logged to prove it fires.
