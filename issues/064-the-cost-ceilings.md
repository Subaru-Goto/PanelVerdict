---
title: "The cost ceilings: a per-account quota and the global daily cap that actually protects us"
labels: [wayfinder:grilling]
parent: 055-map-public-demo
blocked_by: []
assignee: Subaru-Goto
status: closed
---

## Resolution — signed off 2026-08-04

Every number below is **signed off by the author**, not derived. There is no measurement that
yields a risk appetite.

### The ceilings

| what | value | why this and not something else |
|---|---|---|
| **global daily cap** | **$1.00/day** | author's limit was *"no more than 1 euro a day"*. Expressed in **USD** because `USD_PER_VOTE`, the profile table and `remaining_credit` are all USD — a euro cap would need an FX rate, and any rate hardcoded today is a stale unsourced constant tomorrow. **A fixed dollar figure, deliberately not converted:** at any EUR/USD above 1.00 it sits under €1, and if the rate ever fell below parity the cap would drift slightly *over* the author's intent. Accepted, because re-checking a rate is worse than a cent of drift. |
| **per account** | **2 runs per day** | *per day*, not *ever* — *ever* permanently locks out someone returning next week, and the global cap is what actually protects us. |
| **public paid runs** | **`prod` (200 votes)** | the author wants 200 shown, and picking `prod` also **dissolves the disclosure question** this ticket asked: there is no smaller panel to disclose, because a public run is the same 200 votes as the demo report. |
| **analyst, at the edge** | **20 turns per thread per day** | signed off, not derived. A chat turn is a fraction of a vote, so this is generous and cheap. 045 owns the mechanism. |
| **analyst, inside** | `ModelCallLimitMiddleware(thread_limit=40, run_limit=8, exit_behavior='end')` | `run_limit=8` is what `2 * len(tools) + 2` evaluates to **today** (3 tools), so it is *what already ships* rather than a new guess — 052's argument. **`thread_limit=40` is signed off, not derived** — it is 2× the edge's turn budget, a deliberate slack so the inner limit is a backstop rather than a second gate. `exit_behavior='end'` means an exhausted turn finishes with a sentence, not a stack trace. |

### Amendment 2026-08-05: the model changed, and the ceiling now buys ~2.4× more

The panel moved to `openai/gpt-5.6-luna` and `USD_PER_VOTE` fell from a measured **0.000726**
to an estimated **0.0003** (derivation in `config.py`; gate in
[071](071-the-panel-model-changed-without-its-gate.md)). **The ceiling is unchanged at
$1.00/day** — the author's risk appetite did not move — but what it buys did:

| | at $0.000726 | at $0.0003 |
|---|---|---|
| a full `prod` run | $0.145 | **$0.060** |
| full runs per day | 6 | **16** |
| accounts per day, at 2 runs each | **3** | **8** |

**This materially answers the concern below.** The section states 3 accounts/day is *"thin for
a destination that says a stranger can use it safely"* and names it the first number to revisit.
It got revisited by a model change rather than by raising the cap, which is the better outcome:
the same exposure now serves nearly three times the visitors.

**The ratio is 2.4×, not 2.7×.** `0.000726 / 0.0003 = 2.42`; the run and account counts show
2.67× only because flooring rounds 6.9 down to 6 while 16.7 goes to 16. Quoting the counts
flatters the change, so the constants are the honest figure.

**Two caveats.** The new figure is an **estimate**, so these counts are provisional until 071
measures a paid run — and per-account quotas become *less* decorative at 8 accounts than at 3,
since the global cap no longer binds quite so immediately.

### What $1.00 actually buys, which is the number to argue with

Stated plainly because the ticket's own framing hid it behind *runs*:

- a full `prod` run is **$0.145**, so the cap is **6 full runs**
- at 2 runs per account, an account can consume **$0.29**, so the cap serves **3 accounts a
  day** before the fourth visitor is refused
- adaptive stopping raises that: the `stopped` run in `first-full-scale-run.md` finished at
  **50/200 votes for $0.0363**. That is one quarter *by construction* — 50 of 200 votes at the
  same per-vote rate — not an independent measurement, so it bounds rather than predicts. If
  **every** run stopped at 50 votes the cap would buy 27; if none did, 6. **Where real traffic
  falls between 6 and 27 is unmeasured**, and no figure is asserted here.

**This makes the per-account quota nearly decorative at this ceiling**, which is worth admitting:
the global cap almost always binds first. The quota's remaining job is narrow — stopping one
person consuming the whole day in two minutes before anyone else arrives.

**And 3 accounts a day is thin for a destination that says *"a stranger can use it safely."***
It is the author's stated risk appetite and stands, but it is the number to revisit first if the
demo ever gets traffic — either by raising the cap or by running public tests on the `demo`
profile (100 votes, $0.073), which would double the reach at ±16.7 rather than ±13.9.

### At the ceiling: an apology, not an error

The app says plainly that the day's budget has been reached. **No error page, no stack trace,
no silent failure.** And the demo report stays reachable, so a visitor arriving at a bad
moment still sees a real 200-vote verdict rather than a dead end — they never spent anything,
so they should not be punished for the timing.

### Why this does not simply overrule `budget_notice`

`budget_notice` documents *"warn-and-proceed, never refuse"*, and its reasoning is sound:
*"every vote it casts lands in the ledger and a re-run after top-up resumes free."*

**That consolation does not apply to a stranger's run.** The votes land in the ledger, but
they are keyed to *that stranger's headlines* — which nobody will ever re-run, so the spend
buys nothing we keep. Our own thin credit is recoverable; a stranger's loop is not. The stance
holds where it was reasoned and is silent here.

### Two cost questions this surfaced and did not answer

- **The model is not the lever, and the panel model stays.**
  `panel-model-selection.md` already searched for cheap — *"GPT-5 Mini is cheaper than Haiku
  on every axis … the clear value pick"* — and warns *"a cheap model that enacts badly is
  worth zero regardless of price."* Switching also **re-keys every vote fingerprint**
  (`configuration` is inside it) and invalidates what 014 and 015 measured.
- **The analyst runs the cheapest model available** — `openai/gpt-5.6-luna` since 2026-08-05,
  previously `gpt-5-mini` — its cost is **unmeasured**, and
  `003:38` deferred *"a reasoning model"* pick to 012 with no record it was ever made. So
  there is nothing to economise until it is measured →
  [070](070-what-does-a-run-actually-cost.md).

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
