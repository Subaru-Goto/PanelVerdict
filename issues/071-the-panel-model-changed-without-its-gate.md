---
title: "The panel model changed without the manipulation check that was supposed to decide it"
labels: [wayfinder:task]
parent: 055-map-public-demo
blocked_by: []
assignee: null
status: open
---

## Goal

The panel moved from `openai/gpt-5-mini` to `openai/gpt-5.6-luna` on 2026-08-05, on price.
`docs/research/panel-model-selection.md` says that is not how this decision is allowed to be
made:

> *"**Final panel model** is confirmed-or-revised by the **manipulation check** (fidelity is a
> selection criterion, not just cost)."*
>
> *"**A cheap model that enacts badly is worth zero regardless of price.** Resolution (plan
> **B**): benchmark a flagship, deploy the cheapest model that matches its enactment … the
> **manipulation check decides**, not assumption."*

The cheapest variant was deployed first *deliberately* — plan B says deploy the cheapest that
matches, so testing the cheap one first is correct sequencing, and a pass ends the search. But
the check has not run, so nothing yet says Luna enacts Big Five traits at all.

**And this reversed the author's own instruction, recorded so it does not look like a drift.**
The ask was *"change the model from gpt-5-mini to openai/gpt-5.6-luna-pro"* (2026-08-05). Plain
`luna` was recommended instead and the author accepted — *"I take your recommendation."* The
reasons, so the reversal can be re-argued rather than re-discovered:

- `-pro` is the same model served with `reasoning.mode=pro`, so it emits **more** reasoning
  tokens at the same per-token price — and the panel is the only site where that multiplies by
  200 requests.
- the vote task is classification-shaped: read a persona, read two headlines, pick one, give a
  short reason.
- latency is bounded by a read timeout sourced from p95s measured on a *different* model, and
  `-pro` is slower.
- plan B's own logic: test the cheap variant first, because a pass ends the search while
  starting at `-pro` never reveals whether it was needed.

**The author's stated premise was also not quite right, and the correction favours the change.**
The ask described `-pro` as *"50% price of gpt-5-mini"*. It is cheaper than that: $0.10/$0.60
against $0.25/$2.00 per Mtok (OpenRouter model list, 2026-08-05), so **31%** on the same token
counts and a 3.3× cut on output alone. *"Same reasoning model"* is the part that remains
untested, and it is what this ticket exists to test.

## What is now unverified

- **014's manipulation check and 015's task-framing measured `gpt-5-mini`.** Both describe a
  model this repo no longer runs. Their numbers are not wrong; they are about something else.
  Until the check re-runs, the honest statement is that trait enactment is **unmeasured on the
  shipped model**, which is a stronger caveat than the README's current one.
- **The vote ledger is orphaned.** `configuration` is inside `vote_fingerprint`, so every
  cached vote is now a miss. `test_llm.py` names why that is dangerous rather than merely
  wasteful: *"the next run re-buys the panel and reports success, because a cache miss is
  indistinguishable from a first ask."* Nothing breaks; money is spent silently.
- **`USD_PER_VOTE = 0.0003` is an estimate**, signed off 2026-08-05 because test budget belongs
  to development. Derivation and its validation against the one measured figure are in
  `config.py`. **The first paid run on Luna should replace it with a measurement** — that is
  nearly free, since the check has to make paid calls anyway.

## Scope

- Re-run 014's manipulation check on `openai/gpt-5.6-luna` and compare trait effects against
  the recorded `gpt-5-mini` run.
- **Capture `USD_PER_VOTE` from that run** rather than leaving the estimate in place.
- If enactment is materially worse, escalate to `openai/gpt-5.6-luna-pro` — the same model
  served with `reasoning.mode=pro` — and re-run. Record the comparison either way, because
  *"pro was not needed"* is as useful a finding as *"pro was required."*
- Update the README's *Known limitations* to say enactment is unmeasured on the shipped model,
  and revert it once measured.

## What must not be quietly assumed

**`-pro` is not a neutral upgrade.** `panel-model-selection.md` rejected
`reasoning_effort=low` because *"effort changes what the panel is, and the measured
first-position rate and question-wording sensitivity were both taken at the default."* More
reasoning changes it in the same way less does. So escalating to `-pro` needs the check too; it
is not a safe fallback.

**And 015's negative control is the real bar.** It found the panel prefers a variant even on
same-meaning copy. A model change could plausibly make that better or worse, and that result —
not the trait effects alone — is what the product's published caveat rests on.

## Interaction with the demo

[061](061-a-zero-cost-demo-page.md) seeds stored reports from real `prod` runs. **Seed after
this ticket, not before**, or the fixtures are bought on a model that may be replaced — and
under [040](040-vote-cache-read-window.md)'s 24-hour read window the orphaned rows behind them
fall out of reach anyway.

## Done when

The manipulation check has run on the shipped model, `USD_PER_VOTE` holds a measured figure
rather than an estimate, and either Luna is confirmed or `-pro` is adopted with the comparison
recorded.
