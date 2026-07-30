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
