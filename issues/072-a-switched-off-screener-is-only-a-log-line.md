---
title: "A switched-off screener is only a log line, and no test can catch it"
labels: [wayfinder:task]
parent: 055-map-public-demo
blocked_by: []
assignee: null
status: open
---

## Goal

Make an unreachable screening model **loud**. Today it is an `ERROR` log line, which requires
somebody to be reading logs.

## What already exists, so this is not rediscovery

`screening.py` has thought about this carefully and the ticket only asks for the last step:

- **Configuration errors are already distinguished from outages.**
  `_CONFIGURATION_STATUSES = frozenset({401, 403, 404})` (`:73`), and the handler logs at
  `ERROR` rather than `WARNING` when the status is one of those — because *"a 404 or a 401 is a
  **configuration** error … so the control is not degraded, it is off."*
- **`self_model_name` exists for exactly this** (`:76`): *"the screener's model if it will say,
  for a log line that has to name what is switched off."*
- **The failure mode is documented from experience**, not theory: *"That was found by running it
  — both purpose-built safety models 404 on this account, every call raised, and the suite
  stayed green because every test doubles the screener."*
- **The fail-open direction is deliberate and correct**: *"Availability and detection fail in
  opposite directions … an unreachable screener returns quietly, a detection raises."*

So the design is right. The gap is that its only signal is a log line nobody is obliged to read,
and **no test can go red** — `get_screener` is overridden in every test that touches the app.

## Why it matters more now than when it was written

[013](013-guardrails-mvp.md)'s screener is the only control on the sole untrusted-input path,
and [055](055-map-public-demo.md)'s destination puts that path **on a public URL**. A guardrail
that is quietly off on a laptop is a nuisance; quietly off on an open endpoint is the thing
[045](045-paid-endpoints-have-no-auth-or-rate-limit.md) exists to worry about.

Worth stating plainly: **this is not a vulnerability today.** A security pass over the model
switch checked it and found the current slugs valid and the direction of the change
neutral-to-safer. It is a defence-in-depth gap, and the reason to fix it is that the next model
change is the one that silently switches the control off.

## The decision this ticket has to make

**Does an unreachable screener stop the app, or only announce itself?** The answer is probably
not the same everywhere, and that is the interesting part:

- **Locally**, fail-open is right and already reasoned: `get_screener` returns `None` with no key
  because *"a missing key already means 'advisory checks do not run' rather than 'the product is
  down'."* Breaking `uv run` for a missing screener would be hostile.
- **On the public deployment**, an open endpoint with the injection guardrail silently off is a
  worse outcome than a failed boot. Refusing to start is defensible there.

So this likely lands as *"announce everywhere, refuse to start when configured to."* Whatever
ships, the environment split should be **explicit**, not an accident of which code path runs.

## How to probe, and the cost nobody has priced

A screening call is a **paid model call**, so a naive startup probe spends money on every boot —
and on a scale-to-zero platform, on every cold start. [064](064-the-cost-ceilings.md)'s ceiling
is $1.00/day, so this is small but not nothing, and it is unbounded in *count* rather than in
size.

| probe | catches | misses | cost |
|---|---|---|---|
| a real screening call on a fixed benign string | 401, 403, 404 **and** a model that answers unusably | nothing | one paid call per boot |
| slug present in OpenRouter's public model list | 404 (bad or retired slug) | **401/403 — the key lacking access** | free, unauthenticated |
| probe once, cache the verdict | as above, amortised | a mid-life revocation | one call per process |

The middle row is tempting because it is free, and it is the weaker check: 404 is the *typo*
case, while 401/403 is the *this account cannot use it* case — which is precisely what happened
when the purpose-built safety models were tried. **A free check that misses the failure that
actually occurred is not the one to pick.**

## It needs the app's first startup lifecycle

`main.py` has **no `lifespan`, no `on_event`, no startup hook of any kind.** So this introduces
one — and [046](046-analyst-threads-die-on-restart.md) needs the same thing for a
process-lifetime checkpointer connection, having recorded that it *"cannot borrow `get_conn`"*
and is *"a new lifecycle in an app that currently has none."*

**Two tickets, one lifecycle.** Whoever gets there first should build it so the other can use it,
rather than two startup mechanisms appearing independently.

## The test has to escape the doubles

`get_screener` is overridden in every app test, which is why the suite stayed green through a
real outage. So the test for this **must not use that fixture**: construct the real screener
against a transport that raises `APIStatusError(404)` and assert the app announces or refuses,
per the decision above. Anything that goes through the existing `client` fixture is asserting
against a double and proves nothing — the same trap
[025](025-analyst-panel-composition-facts.md) recorded for tool routing.

## Done when

A screening model this account cannot reach is visible **without reading logs** — announced at
startup everywhere, and a hard failure where configuration says it should be — pinned by a test
that does not route through the screener double.
