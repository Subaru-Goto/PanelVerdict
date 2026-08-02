---
title: "VOTE_CONCURRENCY started as a latency knob and quietly became a price"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## The finding (2026-08-02, asked simply "please explain this number")

`VOTE_CONCURRENCY = 25` (`app/vote.py:16`) is a bare module literal. It was chosen when it
governed **only latency**, which is free. [010d](010d-adaptive-stopping.md) then reused it as
the adaptive-stopping chunk size, which made it govern **what a decisive test costs** — and
nothing moved to reflect that. The number is fine; where it lives and what pins it are not.

Two separable defects, below. **Neither is "the value 25 is wrong"** — no run has ever been
throttled by it, and this ticket proposes no change to the number.

## Provenance: it is a planning-time round number, and it predates everything

Traced through git rather than recalled:

| date | event | commit |
|---|---|---|
| **2026-07-16** | `~25` written into the 008 stub — with the tilde | `0d7edad`, the original Wayfinder map: 13 ticket stubs, **no panel code existed** |
| 2026-07-27 | `VOTE_CONCURRENCY = 25` ships | `ca09372` (008) |
| 2026-07-28 | `dev: PanelProfile(size=25)` created | `232ecf3` |
| 2026-07-28 | chunking reuses the constant | `f584550` (010d) |

`issues/008-build-panel-evaluation.md:18` says *"run in batches (~25)"* and never derives it.
There is **no rate limit recorded anywhere in the repo** — `docs/research/panel-model-selection.md`
documents the `$10` credit cap and the 402/429 distinction, but no RPM or TPM figure. So the
cap cannot currently be raised or lowered on evidence; it would take a measurement nobody has
taken.

To its credit the code already admits this — *"25 is a chosen cap rather than a measured one
— no run has yet been throttled by it"* — which is the acceptable form for an unsourced
number under this repo's rule: disclosed, not dressed up.

### The `dev = 25` coincidence is a coincidence

Worth settling, because it is the natural guess and it is wrong in both directions. The cap
predates the profile by twelve days, and `232ecf3` justifies the size on **resolution** —
*"±26 points at 25, ±17 at 100, ±14 at 200"* — never on matching the fan-out. Two numbers,
two independent derivations, same value. 010d then found the equality sitting there and
pocketed it (*"the dev profile degenerates to a single fan-out"*).

Recorded so nobody "fixes" one to match the other, or assumes changing one is safe because
they were chosen together. They were not.

## Defect 1 — the constant's job changed; its home did not

[`config.py:16`](../backend/app/config.py) states the principle this violates, in the
docstring of the dataclass built for exactly this problem:

> *"A panel size is not a tuning knob, it is a purchase: 200 votes cost 200 model calls …
> so the choice is made once per environment rather than per call site."*

That promotion happened to `size` and `model`. It did not happen to `VOTE_CONCURRENCY`,
correctly at the time — on 2026-07-27 the number bought latency only. But since 010d,
`_STOP_CONFIRMATIONS = 2` chunks of 25 means **the earliest a decisive run can stop is 50
votes**, and that is not arithmetic on paper: `docs/research/first-full-scale-run.md` records
the `stopped` run ending at exactly 50 votes for **$0.0363**, *"`decisive` at the 2-chunk
floor."* It hit the floor, not a judgement.

So the floor is a fraction of the panel that varies by profile, and no profile says so:

| profile | size | chunks | earliest stop | as a share of the panel |
|---|---|---|---|---|
| dev | 25 | 1 | **never** | streak caps at 1, `>= 2` is unreachable |
| demo | 100 | 4 | 50 votes | **50%** |
| prod | 200 | 8 | 50 votes | 25% |

Two consequences, both derived from the code above rather than measured:

- **Adaptive stopping cannot fire in `dev` at all.** 010d:105 and `pipeline.py:264` both note
  the single fan-out; neither says the stop is therefore unexercised there. Harmless for
  spend ($0.018 either way) but a real trap when debugging *"why did it run to the cap"*.
- **`demo` can save at most half**, where `prod` saves up to 75%. The savings 010d advertises
  were measured at `prod` size, and the profile a demo actually runs on gets a weaker version
  of them.

**The seam is also missing where it would be needed.** `collect_panel_votes` takes
`concurrency` as a parameter, but only tests pass it (`test_vote.py:223`, `:251`, `:315`);
`pipeline.py:274` reads the module constant directly, with no override. So the fan-out width
is injectable at a boundary nothing in production crosses, and the chunk size is not
injectable at all.

## Defect 2 — the comment's central claim is true locally and false in the shipped path

`vote.py:12` exists to prevent one misreading, and it is emphatic:

> *"A cap on requests in flight, **not a barrier between groups of 25**: a group that waits
> for its slowest member leaves the other workers idle, and a reasoning model's latency
> varies enough for that to cost real time."*

True of `collect_panel_votes` in isolation. **But `collect_panel_votes` is called once per
chunk** — `_chunk_votes` → `collect_panel_votes` → `with ThreadPoolExecutor(...)`, and the
`with` block joins every future on exit. A fully paid prod run therefore performs **eight
barriers, each waiting for its slowest member** — precisely the structure the comment says
was avoided, reintroduced one layer up by a later ticket that never revisited the wording.
(The fan-out is over the chunk's cache *misses*, so a partly cached chunk is narrower than
the cap and a fully cached one waits on nobody.)

**This is not a regression, and the ticket should not read as one.** A stopping rule needs a
boundary to evaluate at; the barrier *is* the price of the stop, and the stop buys up to 75%
of the votes back, which dwarfs the latency it costs. The defect is the **claim**, not the
behaviour: a reader of `vote.py:12` concludes the run never waits on a slowest member, and
the shipped path does it eight times.

Same class as the failures [039](039-culture-tag-cannot-say-neither.md) counted three of —
documentation asserting a property the shipped composition does not have. Cheap to fix:
the sentence needs to say the cap is per chunk and the chunk boundary is 010d's.

For scale, and explicitly labelled as **arithmetic on the measured distribution, not a
measured wall time** (only *"the paid run's minutes"* is on record): with p50 6.5s and
slowest-of-25 landing near the ~96th percentile (~11–12s at the recorded p95 of 11.1s), eight
sequential barriers are ~90s against ~52s for an ideal uninterrupted 25-in-flight stream.
A real figure is now obtainable — [033](033-a-run-records-its-own-time.md) logs wall time
beside `seconds_total`, and their ratio is the effective concurrency.

## What this ticket is *not* asking for

- **Not a new value.** Raising the cap needs a rate limit nobody has measured; lowering it
  trades latency for a cheaper stop floor. Both are decisions with a missing input.
- **Not decoupling chunk size from concurrency by picking two numbers.** With the current
  barrier-per-chunk loop those are the same knob: a chunk smaller than the cap idles workers,
  a chunk larger queues them, so `chunk == concurrency` is the only value that does neither.
  Genuinely decoupling them means evaluating the stop **as votes complete** rather than at a
  barrier — a different loop, and a much larger change than this ticket. Worth its own ticket
  if the 50-vote floor ever costs real money.

## Done when

`VOTE_CONCURRENCY`'s comment says what the number now buys — a latency cap *and*, via 010d,
the stopping granularity that sets a decisive run's floor price — and no longer claims the
run never waits on a slowest member. Whether it stays a module literal or joins
`PanelProfile` is the open call this ticket exists to put in front of someone; if it stays,
the reason it stays is written down. A test names the dev-profile consequence, so
"the stop cannot fire at size 25" is a pinned property rather than a thing rediscovered by
someone debugging a run that went to the cap.
