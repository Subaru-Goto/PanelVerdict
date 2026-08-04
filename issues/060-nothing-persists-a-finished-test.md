---
title: "Nothing persists a finished test — decide the tests table"
labels: [wayfinder:grilling]
parent: 055-map-public-demo
blocked_by: []
assignee: null
status: open
---

## Question

Should a finished test be stored, and in what shape?

`ChatRequest` states the current position outright: *"nothing persists a finished test today
— the votes ledger stores votes, not verdicts."* `schema.sql` has `personas` and `votes` and
nothing else.

**Four separate tickets independently want the same table**, which is the strongest signal on
this map about what to build first:

| ticket | what it needs a stored report for |
|---|---|
| [061](061-a-zero-cost-demo-page.md) | a demo that is $0 **forever**, not for 24 hours |
| [049](049-a-render-error-loses-the-paid-report.md) | recovering a report a render error destroyed |
| [053](053-no-way-to-send-feedback-about-the-product.md) | referencing the report feedback is about |
| [054](054-nothing-confirms-the-panel-before-the-money-is-spent.md) | holding a pending selection between the two phases |

**The demo is what makes it urgent.** [040](040-vote-cache-read-window.md) specifies a
**24-hour read window** on the vote cache — so a demo that replays cached votes silently
starts paying 24 hours after it is seeded. A stored *report* needs no model call at all,
ever.

What this ticket has to settle:

- what a row holds — the whole `EvaluateResponse` as JSONB, or a normalised shape
- what identifies it, given `pipeline.py:258` records that **a cached vote keeps the
  `test_id` of the run that paid for it**, so `votes[0].test_id` does not identify a report
- whether writing it goes on the paid path, and what happens if that write fails after the
  votes are bought
- retention, which 040 answered for votes and 046 left open for threads — and which this
  destination changes, because a logged-in user's report is *owned* content
- whether the demo's row is the same kind of row as a user's, or a separate seeded fixture
