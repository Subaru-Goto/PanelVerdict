---
title: "LangSmith tracing behind an env flag, with a disclosure line"
labels: [wayfinder:task]
parent: 055-map-public-demo
blocked_by: []
assignee: null
status: open
---

## Goal

Traces in production, so a live agent can be debugged — the thing
[047](047-nothing-correlates-a-log-line-to-its-run.md) is missing.

**Cheap, because `langsmith` 0.10.6 is already installed** (transitive via `langchain-core`).
Adoption is configuration — `LANGSMITH_TRACING`, an API key, a project name — not a
dependency.

Three constraints, all from the map's standing decisions:

- **Conditional on the free tier**, so tracing is an env flag the app runs **fine without**.
  Never a hard dependency, never an import that fails when the key is absent. The
  environment file is the author's to edit.
- **Disclosed in the UI.** Traces mean the reader's headlines leave our infrastructure, and
  [053](053-no-way-to-send-feedback-about-the-product.md) established that a reader's input
  can be unreleased marketing copy. One line, in the input area.
- **The disclosure is a deterrent, not a control.** *"Inputs are traced"* discourages casual
  probing — which is a real benefit and worth having — but it stops nobody determined. The
  controls remain [013](013-guardrails-mvp.md)'s screener and
  [045](045-paid-endpoints-have-no-auth-or-rate-limit.md)'s limits, and nothing here may be
  counted toward them.

Also worth resolving in the same pass: whether the trace carries a run identifier that ties
it to a log line, since that is 047's actual complaint and a trace with no correlation
handle only half-answers it.
