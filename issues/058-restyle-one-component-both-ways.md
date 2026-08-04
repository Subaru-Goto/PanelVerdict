---
title: "Restyle one component both ways and react to it"
labels: [wayfinder:prototype]
parent: 055-map-public-demo
blocked_by: [057-does-shadcn-earn-its-place]
assignee: null
status: open
---

## Question

Which styled version do we actually want to look at?

*"The current design is horrible"* is a reaction, and the only reliable way to resolve it is
to produce something to react to. Pick **one** component — `evaluate-form.tsx` (152 lines) is
the right size and is the first thing a visitor sees — and build it twice:

- on the token layer from [056](056-geist-is-loaded-and-arial-renders.md), no new
  dependencies
- with shadcn primitives, per [057](057-does-shadcn-earn-its-place.md)'s findings

Then look at both and decide. Use `/prototype`.

**The comparison must be against a fair baseline**, which is why 056 comes first: judging
shadcn against an Arial-rendered scaffold would flatter it for reasons that have nothing to
do with shadcn.

Resolving this settles the styling approach for the whole map. Record *why*, not just which
— the next reader needs the reason more than the verdict.
