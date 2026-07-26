---
title: "Build the guardrails MVP (security requirement)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [008-build-panel-evaluation]
assignee: null
status: open
---

## Goal

The minimum defensible slice for the security requirement:

- random-nonce delimiters around **all interpolated content** (per the 006e grill: a static XML tag is forgeable, a per-request nonce can't be escaped/closed; delimiting is designed once here, not piecemeal in 006e which ships only the denylist),
- strict {A, B, neither} enum output (injection can't break the pipeline's shape),
- position randomization (from 008) as an architectural defense,
- plain-text output rendering,
- size/format limits,
- ONE screening layer (OpenRouter Guardrails in *flag* mode, or Mistral Moderation).
- ~~**shared with ticket 006:** LLM-written persona content (interests + prose) is run through this same screening **before persisting** to the pool.~~ **Amended 2026-07-26 ([006j](006j-persona-summary-embedding.md)):** no LLM-written persona content survives — every persona field is sampled or templated, so there is nothing to screen before persisting and the pool-poisoning path closes by construction. **The interpolated content that remains untrusted is the user's: headline variants and the natural-language target description.** 006e's local denylist has no caller left after 006j slice 3 and should be absorbed here, where the untrusted input actually enters, rather than kept alive in the pool build.

Document the "least privilege by design" argument: panel agents have no tools, no memory, no shared state → worst-case successful injection = one biased vote, absorbed by position randomization + anomaly detection.
