---
title: "Targeting drops fuzzy age words: 'young Japanese people' seated a 91-year-old"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Problem (found in real use, 2026-07-30)

Target description "Young Japanese people" produced a panel whose voters ran
from 23 to 91 years old. The translator has no rule for unquantified age
words: the system prompt (`llm.py` `_TARGET_SYSTEM_PROMPT`) lists `age` as an
attribute but rule 5 — "leave a field empty rather than guessing" — pushes
the model away from mapping "young" to numbers, and an empty span resolves to
the pool default (18–100). Nothing on the report says the word was dropped,
so the report *looks* like it honored a target it quietly ignored.

Open observation from the incident: it is not yet confirmed whether the
translator left the span empty (default 18–100, voters happening to run
23–91) or hallucinated a span. First step of this ticket: reproduce inside
pytest with the fake translator path bypassed — i.e., pin what the real
prompt does — before choosing where the fix lands. No paid calls outside
pytest.

## Reproduced live 2026-07-31 — and the open observation above is now answered

Target "young japanese" returned:

> The pool holds no data on young — the panel is not matched on that.

So the translator **left the span empty and put the word in `unmapped`**, rather
than hallucinating a span. That settles the question this ticket said to answer
first, and it does it without a paid pytest reproduction, because the notice only
fires on a non-empty `request.unmapped` (`targeting.py:231-237`).

Three things follow, and they change the shape of the decision below rather than
just confirming the bug.

**The title's "silent" is no longer accurate, but the panel is still wrong.** The
word *is* reported. What is not honored is the ask: `unmapped` produces a notice
and nothing else, so no age filter is ever applied and the 91-year-old remains
admissible on a "young" target. Reported-and-unfiltered, not silent-and-unfiltered.

**A distinct defect, cheap to fix, worth separating from the fix options below:
the notice blames the wrong thing.** "The pool holds no data on young" is false —
the pool holds ages on every persona, bounded by `MIN_PERSONA_AGE`/`MAX_PERSONA_AGE`,
and `min_age`/`max_age` exist on both `TargetRequest` and `TargetQuery`. The gap is
that nothing maps the *word* to a span. The message attributes a translator
limitation to a data limitation, which means the product hands the reader a wrong
explanation of its own behaviour — worse than handing them none, because it sends
the next person looking in the pool. The wording is shared by every `unmapped`
attribute, so the fix is one sentence and is not specific to age.

**Option 1 is already the de facto behaviour — but by the model's judgement, not by
rule.** No prompt rule sends fuzzy age words to `unmapped`; the model decided that
on its own, so nothing pins it and any prompt or model change can silently move it.
That sharpens the choice: option 1 is not "add a behaviour", it is "pin the
behaviour we already have", and on its own it leaves the panel exactly as
unfiltered as today — honest about the ask it ignored, still useless for it.
Whether that is acceptable is the actual decision.

**One design fact confirmed in passing, relevant well beyond this ticket:**
`unmapped` never enters `TargetQuery`, and `retrieve_panel` reads only the query.
So an unmappable attribute changes the notices and *not* the panel drawn — which
also means it cannot change a vote's cache key. Adding or removing "young" from a
target re-uses the same paid votes.

## Fix options (user decision pending — do not pick silently)

1. **Notice-only:** prompt rule that unquantifiable age words go into
   `unmapped`, so the report shows "this part of your target couldn't be
   honored". No invented numbers; the panel stays broad but honest.
2. **Mapped spans:** prompt rule giving explicit numeric spans for the common
   fuzzy age words ("young", "middle-aged", "elderly"). Every span is a
   constant that needs a citable source (e.g. conventional market-research
   brackets) or explicit user sign-off — house rule, no unsourced numbers.
3. **Both:** map the common words, `unmapped` for anything else.

## Pin whichever fix wins with a test

"Young Japanese people" must yield either a bounded age span or a visible
notice — never a silent full-range panel.

## Related

- The analyst could have surfaced this bug in-chat if it could see panel
  ages — that capability gap is [025-analyst-panel-composition-facts](025-analyst-panel-composition-facts.md).
