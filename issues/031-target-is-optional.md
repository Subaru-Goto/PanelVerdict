---
title: "A test cannot be run without a target: the audience field is effectively required"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Problem (found in real use, 2026-07-30)

"Evaluate" stays disabled until an audience is described
(`evaluate-form.tsx`: `disabled = !targetDescription.trim() || …`), so the
untargeted test — two headlines against a cross-section of the whole pool —
cannot be run at all. It is the simplest thing the product does and the one
thing the form forbids.

The gate is client-side only. `EvaluateRequest.target_description` is a bare
`str` with no `min_length`, so the API would accept `""` today.

## Second half, invisible from the UI

Sending `""` would not be free. `select_panel` calls
`translator.translate(description=description)` unconditionally — a paid model
call — and would spend it translating an empty string, leaving what comes back
to the model's discretion.

Nothing needs translating. `resolve_target(TargetRequest())` already resolves
to the whole pool by the documented path: `_resolve_regions([])` returns every
`Locale` at rung `requested`, ages fall back to the pool's own span, and no
other filter is set. The empty request is already the "everybody" request.

## Fix

- **Frontend:** drop the target from the submit gate; headlines stay required.
  Label it optional, so a blank field reads as a choice rather than an
  oversight.
- **Backend:** in `select_panel`, skip the translator entirely when the
  description is blank and resolve `TargetRequest()` directly. Free,
  deterministic, and it removes a paid call whose result was never in doubt.
- **Notice:** say what happened. A blank target currently resolves with only
  "Matched against panelists in …", which reads the same as a target that
  asked for everywhere. An untargeted run should say so, since the report's
  whole job is distinguishing what was asked for from what was served.

## Pin with tests

- Blank description → no translator call at all (the double records calls), and
  a whole-pool query.
- Blank description → the untargeted notice; a described target → not.
- The form submits with headlines only.

## Related

- [011](011-build-report-ui.md) — the report's rule that every gap between what
  was asked and what was served becomes a notice.
