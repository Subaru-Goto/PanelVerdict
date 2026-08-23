---
title: "What does the EU AI Act actually require of PanelVerdict?"
labels: [wayfinder:research]
parent: 055-map-public-demo
blocked_by: []
assignee: Subaru-Goto
status: closed
---

## Question

The author proposed hand-authoring a LangGraph on the belief that the EU AI Act
*"requires us to show each step the LLM takes"* (2026-08-21). Before an architecture is
chosen on a legal premise, establish from primary sources: which obligations of
Regulation (EU) 2024/1689 apply to PanelVerdict at all, and does any of them require
per-step LLM traceability?

## Resolution (2026-08-21)

**No provision requires per-step LLM traceability for this product — the premise is
refuted.** Full findings with dated quotes:
[eu-ai-act-applicability.md](../research/eu-ai-act-applicability.md). The short form:

- **Minimal risk, confirmed.** Nothing in Annex III covers marketing-copy testing, and the
  Art. 5 prohibitions require techniques deployed on *natural* persons — the panel is
  synthetic; the only human is the marketer reading a report.
- **Art. 12 event logging applies to high-risk systems only**, and even there demands
  event-level records, never per-LLM-call traces. The Commission's Art. 50 guidelines
  (C(2026) 5054 final) put agent reasoning / chain-of-thought explicitly out of marking
  scope.
- **What does apply — and is in force since 2 Aug 2026:** the author is the **provider of
  the PanelVerdict AI system** the moment the demo is public under their name (the
  guidelines' own example is a public chatbot demo), so **Art. 50(1)** requires the analyst
  to disclose its artificial nature in-context — a T&C mention or an "assistant" label is
  insufficient per the guidelines. Penalties for Art. 50 breaches reach €15M/3%.
  → [The analyst never says it is an AI system](https://github.com/Subaru-Goto/PanelVerdict/issues/164)
- **Art. 50(4) content labelling does not apply** (the guidelines exclude text available
  only to the user who prompted it); **Art. 50(2) machine-readable marking plausibly does**,
  feasibility-bounded, with a voluntary Code of Practice (June 2026) as the vehicle — the
  one genuinely uncertain item.
  → [Generated text carries no machine-readable mark](https://github.com/Subaru-Goto/PanelVerdict/issues/165)
- The Digital Omnibus (Regulation (EU) 2026/1744) deferred **high-risk** obligations to
  Dec 2027 — **Art. 50 was not deferred.**

Sourcing caveat recorded in the doc: EUR-Lex was WAF-blocked throughout, so article text
came from the FLI AI Act Explorer mirror, cross-checked against the Commission's Art. 50
guidelines PDF (primary, quoted directly). Not legal advice.

**Consequence for the map:** the LangGraph decision returns to its honest grounds —
capability and author requirement, not compliance. Recorded in
[Where is a hand-authored graph worth it?](067-where-is-a-hand-authored-graph-worth-it.md).
