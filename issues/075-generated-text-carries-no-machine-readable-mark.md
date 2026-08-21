---
title: "Generated text carries no machine-readable mark — Art. 50(2), the uncertain one"
labels: [wayfinder:task]
parent: 055-map-public-demo
blocked_by: []
assignee: null
status: open
---

## Goal

Whatever PanelVerdict lets a user take away (a report, analyst answers) carries a
machine-readable indication that it is AI-generated — to the extent Art. 50(2) actually
demands and current practice can deliver.

## The state of the question

[073](073-what-the-eu-ai-act-actually-requires.md) flags this as the one genuinely
uncertain-in-practice obligation: as provider of a generative AI system the author is
plausibly in scope of Art. 50(2) (machine-readable marking of generated text), but the
duty is feasibility-bounded, excludes short outputs and chain-of-thought, and its
compliance vehicle is a **voluntary Code of Practice (final 10 June 2026)** whose text-
marking baseline is still settling. A reported transitional window for pre-existing
systems could only be sourced secondarily — recorded as uncertain in
[eu-ai-act-applicability.md](../docs/research/eu-ai-act-applicability.md).

## Scope — watch and tag, not architecture

- Metadata-tag anything exportable: if/when the report becomes a saveable artifact
  ([060](060-nothing-persists-a-finished-test.md) persistence, any future export), embed
  an AI-generated provenance marker (format per the Code of Practice's baseline).
- Track the Code of Practice; when its text-marking baseline is concrete, size the real
  work and amend this ticket rather than guessing now — the repo's no-unsourced-constants
  rule applies to legal baselines too.
- In-app text shown only to the prompting user is the case the Art. 50(4) guidelines
  explicitly exclude; do not build marking for it on precaution.

## Done when

Exported/persisted artifacts carry a provenance mark, the Code of Practice position is
recorded with a date, and the decision of what NOT to mark is written down with its
source.
