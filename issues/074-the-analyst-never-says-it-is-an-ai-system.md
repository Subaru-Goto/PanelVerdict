---
title: "The analyst never says it is an AI system — Art. 50(1) is in force and unmet"
labels: [wayfinder:task]
parent: 055-map-public-demo
blocked_by: []
assignee: null
status: open
---

## Goal

A visitor who opens the analyst dock is told, in context and before or at the first
exchange, that they are talking to an AI system — and the analyst says so itself if asked.

## Why this is a live legal duty, not polish

[073](073-what-the-eu-ai-act-actually-requires.md): once the demo is public under the
author's name, the author is the **provider of an AI system**, and **Art. 50(1)**
(in force since 2 Aug 2026, not deferred by the Omnibus) requires that people interacting
with it are informed of its artificial nature. The Commission's guidelines
(C(2026) 5054 final) are specific about what fails: a terms-of-conditions mention, an
"assistant" label, or a generic "this product uses LLMs" statement are **insufficient**;
the "obvious to a reasonable person" exemption is read restrictively for public-facing
systems. Penalties for Art. 50 breaches reach €15M/3% (SME caps lower).

Today the dock has nothing. The report's synthetic-panelist caption
([023](023-vote-feed-voter-details.md)) helps but discloses the *panel*, not the
*conversation partner* — it cannot carry this duty alone.

## Scope

- Disclosure copy at the dock: visible at the chat input and/or in the first turn —
  in-context, per the guidelines, not buried in a footer. Wording goes through the same
  cold-reader discipline as all report copy; "restyle, don't redesign" does not apply here
  because this is *new* copy, not a rewrite of iterated copy.
- Self-disclosure: asked "are you human?", the analyst answers that it is an AI system.
  The system prompt has no interpolation by design (`least-privilege.md`) — a static
  instruction line preserves that.
- One decision to record while here: does the **submission → report flow** also count as
  "interacting with an AI system" under Art. 50(1)? [073](073-what-the-eu-ai-act-actually-requires.md)'s
  research says a one-shot prompt/reply likely counts. If yes, the evaluate form needs one
  disclosure line too — cheap, so decide it here rather than spawning a ticket.

## Out of scope

- Art. 50(2) machine-readable marking —
  [075](075-generated-text-carries-no-machine-readable-mark.md).

## Done when

A stranger reaching the dock cannot miss that the analyst is an AI system, the analyst
says so when asked, the evaluate-flow question has a written answer, and the disclosure
survives a cold read (someone who does not know the Act understands what they are told).
