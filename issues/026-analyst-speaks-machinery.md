---
title: "Analyst quotes field names at the reader: 'stop_reason = null and coverage = requested'"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Problem (found in real use, 2026-07-30)

Asked "Why did the test stop early?", the analyst replied:

> I checked the test results with the analyzer tool. The output shows
> stop_reason = null and coverage = "requested" — 25 panelists were requested,
> 25 matched, and 25 voted — so the test did not stop early [...] Would you
> like me to show the vote counts and the stopping fields from the report?

**The finding was correct.** `stop_reason` is set only when the chunk loop
breaks early (`pipeline.py`), so `None` does mean the run polled to the end;
25/25/25 reads `PanelCounts` right. Nothing was hallucinated. What broke is
[025](025-analyst-panel-composition-facts.md)'s rule — *"never name a tool, a
function, a field or a step you took"* — in four places: "the analyzer tool",
"stop_reason = null", `coverage = "requested"`, "the stopping fields".

## Two causes, and only one of them is the model's fault

**1. Narrating the act.** "I checked the test results with the analyzer tool"
has no cause in the payload — the model even invented a name (`analyze_results`
is not "the analyzer tool"). This is plain prompt disobedience.

**2. Leaking fields, which we caused.** `analyze_results` returns
`model_dump_json()`, so our field names *are* the model's whole vocabulary for
this test. Note **which** fields leaked: `stop_reason` and `coverage`, not
`counts`. That is not random. `counts` has plain-English values — "25
requested, 25 matched" — so the model could say it. `null` and `"requested"`
have no sayable form, and nothing in the payload says what they mean:
`_stopped_early_notice` returns `()` when the reason is `None`, so a run that
*didn't* stop early carries no English about it anywhere. The model quoted the
field because quoting was the only faithful move left to it.

That is exactly the mistake 025 diagnosed and then avoided: forbidding by
instruction what the tool hands over raw. Ids stopped appearing because we
stopped passing them — *"a model cannot quote a handle it was never given"* —
and the same move is available here.

### A correctness bug rides along with the leak

`coverage` is about **places only**: `requested` means every named region was
served as named, and says nothing about age, gender, income or traits. The
enum name invites exactly the over-read the reply made — presenting
`"requested"` as evidence the panel matched the ask. Under
[024](024-fuzzy-age-words-in-targeting.md) a "young Japanese people" target
that silently drops "young" still reports `coverage: "requested"`. Any
reader-facing wording must say *places*, the way the report already does
("A stand-in region was used", "The region you named could not be matched").

## Fix

**Payload half — replace, do not augment.** Drop `stop_reason` and `coverage`
from `AnalysisFacts` in favour of fields whose *values* are English sentences.
Augmenting would leave the raw enum in the payload, which is the leak. Wording
follows the report's and `_stopped_early_notice`'s existing vocabulary rather
than inventing a third dialect; the early-stop sentence must not claim
panelists went unpolled, since `EvaluateResponse` does not carry `asked`.
Both construction sites move — `analysis_facts` and `run_panel_test` build
`AnalysisFacts` separately, and fixing one path only would leave a re-test
answering in machinery.

**Prompt half.** Move the no-machinery rule up next to the tool rule that
creates the temptation, and give it the positive form (lead with the finding)
rather than a bare prohibition.

## Honest limit, inherited from 025

The prompt half's *effect* cannot be asserted — asserting the constant contains
a sentence is tautological, and whether the model obeys is
quality-with-degrees, i.e. judge territory. What ships tested is the payload
half: the machinery token is absent from the tool result, and the sayable
sentence is present. This is now the second ticket in a row whose real fix
lived in prose no test can check; see the map's DeepEval note.

## Deliberately NOT changing

- **`PanelVerdict.rope`** rides into the payload under a field name the prompt
  has a dedicated rule about ("prefer 'tie zone' over ROPE") — the same
  instruct-don't-withhold pattern, and a leak waiting to happen. Left alone
  because it has not been observed leaking, and because `PanelVerdict` is the
  wire contract the report reads: renaming it is [022](022-rename-worth-acting-on-field.md)-shaped
  work, not a line in this ticket. Recorded so the next sighting is evidence,
  not a surprise.
- **The report's `coverage: {rung}` chip** shows the same raw enum to the user.
  Out of scope here (frontend copy), noted for whoever next does a cold read.

## Related

- [025](025-analyst-panel-composition-facts.md) — same surface, and the source
  of both the rule that was broken and the withholding pattern that fixes it.
- [024](024-fuzzy-age-words-in-targeting.md) — the coverage over-read above is
  the analyst-side face of that bug.
