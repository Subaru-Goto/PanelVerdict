---
title: "Rename probability_worth_acting_on — the wire should speak the report's language"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [011-build-report-ui]
assignee: Subaru-Goto
status: closed
---

**Delivered 2026-07-29** in PR #65. The field is `probability_meaningfully_preferred`
with keys `a`/`b` as proposed; the report.tsx crossover and its guard comment are
gone, the pairing test pins the straight read, and `expected_preference_shortfall`
kept its shipping keys. `docs/reading-the-posterior.md` never named the field, so
no doc edit was needed; `vote.py` untouched, fingerprints unaffected. Both suites
green at merge (backend 447, frontend 25).

## Goal

Rename `PanelVerdict.probability_worth_acting_on` (keys `shipping_a` /
`shipping_b`) to a field whose name and keys match what the report actually
says, so the frontend stops mapping `shipping_b` onto a tile labelled "A".

Proposed: `probability_meaningfully_preferred` with keys `a` / `b`, where
`a` = today's `shipping_b` and `b` = today's `shipping_a`. Exact name open
to bikeshedding at implementation; the two requirements are that it names
the *preference* rather than the shipping decision, and that key `a` is
about variant A.

## Why

011b's tile copy went through three passes with the user — "Shipping A is
the mistake" → "Risk of shipping A" → **"Chance A is preferred / by a gap
big enough to matter"** — and the final frame is preference-shaped, not
decision-shaped. The wire field is decision-shaped and points the other
way: the chance shipping B is *wrong* is the chance A is *meaningfully
preferred*. So the report now crosses the fields over —
`probability_worth_acting_on.shipping_b` feeds the tile labelled
"Chance A is preferred" — held in place by a comment in `report.tsx` and a
value-to-label pairing test. That containment works, but every future
reader of the grid re-derives the crossover, and an accidental swap is
exactly the bug the copy invites.

`verdict.py`'s docstring records the original naming rationale: "Named for
what a reader does with it, not for the geometry." The 011b copy iteration
overturned that premise — the user rejected the decision framing for the
reader-facing surface, which is the same argument against it on the wire.
The math is untouched either way: `a`-preferred = `1 − cdf(rope_high)`
crossed to `cdf(rope_low)` — only the labels move, to the one place that
can fix the mismatch for every consumer at once.

## Scope

A clean rename, not an additive/deprecated pair — the frontend is the only
consumer and nothing external holds the schema yet. Touches:

- `backend/app/schemas.py` — `PanelVerdict` field + `PreferenceProbability`
  key names and docstrings.
- `backend/app/verdict.py` — `probability_worth_acting_on()` +
  `ActionableProbability`, and the construction site; update the "named for
  what a reader does with it" docstring to record the reversal.
- `backend/tests/test_verdict.py`, `backend/tests/test_main.py`.
- `backend/experiments/panel_run.py` (prints the field).
- `frontend/app/lib/api.ts` — type follows the wire; `report.tsx` — delete
  the crossover and its comment; the pairing test in
  `frontend/__tests__/report.test.tsx` flips from "pins the crossover" to
  "pins the straight mapping" and must stay.
- Check `docs/reading-the-posterior.md` for prose naming the field.

Note `expected_preference_shortfall` keeps its `shipping_a`/`shipping_b`
keys: it genuinely is about the shipping decision (what picking that side
costs), so the decision framing is correct there. The rename is only for
the probability whose reader-facing sentence is about preference.

## Done when

- No `probability_worth_acting_on` / crossed mapping anywhere; the 98%
  tile test passes with a straight `a`-to-A read.
- Backend and frontend suites green; cache fingerprints unaffected (the
  vote fingerprint hashes prompts and options, not verdict fields — assert
  nothing in `vote.py` changes).
