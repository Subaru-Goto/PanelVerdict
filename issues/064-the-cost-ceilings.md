---
title: "The cost ceilings: a per-account quota and the global daily cap that actually protects us"
labels: [wayfinder:grilling]
parent: 055-map-public-demo
blocked_by: []
assignee: null
status: open
---

## Question

What are the numbers, and which layer is load-bearing?

**Nothing caps spend today.** No daily limit, no per-caller limit, no refusal of any kind —
`budget_notice` warns and proceeds, and `get_remaining_credit` reads the balance without ever
declining. At `prod` scale a run is **$0.145**; `dev` is **$0.018** (README's profile table).
So a stranger with a loop is currently bounded only by the key's balance.

The layering, with roles named so neither looks redundant:

| layer | stops | bounded by |
|---|---|---|
| per-account quota | casual abuse | not exposure — accounts are free to create |
| **global daily cap** | **everything, including new-account farming** | **a number we choose** |
| per-IP limit | one script bursting | trivially bypassed; stops only the dumb case |

**Only the global cap bounds exposure.** The per-account quota makes abuse tedious; it does
not make it impossible, because signing up again costs nothing. Whatever ships must say this,
or the cap will read as duplicated effort and get dropped.

**Which is why this ticket is unblocked, and the global cap ships first.** An earlier draft
made it depend on [063](063-google-login-verified-at-the-edge.md), which had the load-bearing
control arriving *after* auth and after vendor research — while *nothing caps spend today*.
The global cap needs no identity at all: it is a counter and a ceiling. Only the per-account
quota needs 063, so **split the work rather than the ticket** — ship the cap, then the quota.

What has to be decided:

- **the daily ceiling, in dollars** — signed off explicitly, not derived. This repo does not
  ship unsourced constants, and there is no measurement that yields this number: it is a
  decision about what a bad day may cost.
- **runs per account, and per what window.** The proposal is 2 per day; *ever* locks out a
  returning visitor permanently and the global cap already protects us.
- **what the app does at the ceiling.** Refusing with an error is the lazy answer; falling
  back to the demo report ([061](061-a-zero-cost-demo-page.md)) means the app still works
  when the budget is gone.
- **`dev` or `prod` profile for public runs**, and how that is disclosed given the resolution
  differs (±24 against ±13.9 points).
- **the analyst's own limit.** It spends too. 045 argues the honest unit is *turns per thread
  per window* at the edge; [052](052-the-step-budget-is-derived-arithmetic-not-a-declared-limit.md)
  bounds model calls *within* a turn via middleware. Both, and say which is which.

**And it contradicts a documented stance.** `budget_notice` says *"warn-and-proceed, never
refuse"*, reasoned on the grounds that votes already cast land in the ledger and a re-run
resumes free. That is right about **our own** thin credit and silent about **a stranger's
loop** — the same shape of argument [054](054-nothing-confirms-the-panel-before-the-money-is-spent.md)
had to make. Write the distinction down rather than quietly overriding it.
