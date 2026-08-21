---
title: "Does a failed structured output get told what was wrong with it? Validate, inform, retry"
labels: [wayfinder:task]
parent: 078-map-next-chapter
blocked_by: []
assignee: null
status: open
---

## Goal

Every structured-output site — the vote, the targeting translation, the screener —
handles an invalid response the same disciplined way: validate against the schema, feed
the **specific** validation errors back to the model, retry bounded, and surface a typed
failure when retries exhaust. Author's prompt (2026-08-21): TrustCall-style checking —
*"check the proper structured output and inform and retry if it is necessary."*

## First: audit what actually happens today, don't assume

The current behaviour per site is **unverified** and must be established before building:
what does each of the three sites do on a parse/validation failure right now — silent
retry? blind retry? hard fail? The one documented incident sets the stakes: a single
targeting call once generated 65,536 completion tokens, **failed to parse, and cost
$0.13** — a whole panel run — before `TARGET_MAX_COMPLETION_TOKENS` capped it
([targeting-call-effort.md](../docs/research/targeting-call-effort.md)). A blind retry
of that shape re-buys the failure; an informed retry ("field `min_age` must be an
integer, you sent a range") converges.

## Where each site lands, sized honestly

- **Targeting** — the payoff case: the largest schema (`TargetRequest` with demographics,
  traits, and the disclosure fields from the 024/037/038 arc), the most expensive
  failure, and downstream money riding on its correctness.
- **The vote** — smallest schema (a choice + a reason); a from-scratch retry is fine and
  already interacts with [051](051-a-vote-that-exhausts-its-retries-is-gone-for-good.md)'s
  retry-exhaustion question. Informed retry is likely overkill here; decide, don't
  default.
- **The screener** — fail-open/fail-closed semantics ([013](013-guardrails-mvp.md),
  [072](072-a-switched-off-screener-is-only-a-log-line.md)) must dominate: a parse
  failure is an *outage-shaped* event and must land on the documented fail-open arm,
  never look like a "clean" pass.

## The technique, not necessarily the library

TrustCall's distinctive trick — JSON-patching the invalid parts instead of regenerating
the whole output — pays off on large schemas and incremental updates. Weigh it against
the two mechanisms already in hand before adding a dependency: LangChain's
`with_structured_output` validation path, and a small hand-rolled loop that appends
pydantic's error list to the retry prompt. The repo's rule stands: only packages the
project directly needs.

**Fingerprint warning, non-negotiable:** the vote-ledger key hashes the adapter's
`configuration` and exact request strings ([010e](010e-per-vote-cache.md)). A retry
mechanism that mutates the outgoing prompt (by appending error feedback) creates a new
fingerprint — fine for a *failed* vote (it has no row), but the mechanism must provably
never touch the first-attempt request, or every cached vote is re-bought.
[036](036-init-chat-model.md) records how a "tidy" change nearly re-keyed the ledger;
this ticket walks the same ground.

## Done when

The audit's findings are written down per site; targeting retries informed and bounded;
the screener's parse failure lands on the outage arm with its log line; the vote's
decision is recorded either way; and a test pins that first-attempt request bytes are
identical before and after — the replay guarantee demonstrably untouched.
