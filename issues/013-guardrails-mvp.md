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

- random-nonce delimiters around the variants (attackers can't escape the wrapper),
- strict {A, B, neither} enum output (injection can't break the pipeline's shape),
- position randomization (from 008) as an architectural defense,
- plain-text output rendering,
- size/format limits,
- ONE screening layer (OpenRouter Guardrails in *flag* mode, or Mistral Moderation).

Document the "least privilege by design" argument: panel agents have no tools, no memory, no shared state → worst-case successful injection = one biased vote, absorbed by position randomization + anomaly detection.
