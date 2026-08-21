---
title: "The evaluate form bounds its vocabulary — open text invites targets the pool cannot serve"
labels: [wayfinder:task]
parent: 078-map-next-chapter
blocked_by: []
assignee: null
status: open
---

## Goal

A visitor knows what the pool can serve **before** typing, and the highest-risk
dimension stops being typed at all. Author's direction (2026-08-21): *"open Text is
ambiguous for agents to select the filter … we only have US, DE and JP, and no solution
for hobby."*

## Scope

- **Country becomes an explicit control** — a US / DE / JP multi-select, default all.
  It has exactly three legal values, and it is where free text has hurt most ("Ohio"
  silently became the whole US, [007](007-build-targeting-query-translation.md)). The
  control's value wins; the translator is told geography is out of its scope, so it can
  no longer misread it.
- **The text box discloses its vocabulary**: a caption or chips naming the servable
  dimensions (age, gender, education, income band, Big Five temperament) plus one or two
  example targets — and an honest line that interests/hobbies are not yet supported
  (the grounding gap is recorded at [006i](006i-leisure-profiles.md)/map 000; v2 work,
  not a silent failure).
- Free text **stays** for everything non-geographic — query translation is the product's
  differentiator and half its RAG story; the fix is honesty about the vocabulary, not a
  form replacing it.
- The disclosure ladder (unmappable words → notices) is unchanged and still lands in
  [077](077-panel-preview-accept-or-redraw.md)'s preview, where it can still change the
  decision.

## Done when

"Sporty French gamers" is impossible to submit in good faith: France was never typeable,
and the visitor was told hobbies are unsupported before typing — with whatever they did
type still resolving through the same translated, disclosed, preview-confirmed path.
