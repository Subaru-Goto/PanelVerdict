---
title: "Build the guardrails MVP (security requirement)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [008-build-panel-evaluation]
assignee: null
status: closed
---

## Goal

The minimum defensible slice for the security requirement:

- random-nonce delimiters around **all interpolated content** (per the 006e grill: a static XML tag is forgeable, a per-request nonce can't be escaped/closed; delimiting is designed once here, not piecemeal in 006e which ships only the denylist),
- strict {A, B, neither} enum output (injection can't break the pipeline's shape),
- position randomization (from 008) as an architectural defense,
- plain-text output rendering,
- size/format limits,
- ONE screening layer (OpenRouter Guardrails in *flag* mode, or Mistral Moderation).
- ~~**shared with ticket 006:** LLM-written persona content (interests + prose) is run through this same screening **before persisting** to the pool.~~ **Amended 2026-07-26 ([006j](006j-persona-summary-embedding.md)):** no LLM-written persona content survives — every persona field is sampled or templated, so there is nothing to screen before persisting and the pool-poisoning path closes by construction. **The interpolated content that remains untrusted is the user's: headline variants and the natural-language target description.** 006e's local denylist has no caller left after 006j slice 3 and should be absorbed here, where the untrusted input actually enters, rather than kept alive in the pool build.

Document the "least privilege by design" argument: panel agents have no tools, no memory, no shared state → worst-case successful injection = one biased vote, absorbed by position randomization + anomaly detection.


## Closed 2026-07-30 — and half of it was already true

Item by item, against what the code actually did rather than what the ticket
assumed:

| asked for | outcome |
|---|---|
| random-nonce delimiters around *all* interpolated content | **built where a stranger's text enters**, which is the vote prompt: options were spliced straight into the task text. Not everywhere the word "all" reaches — `read_reasons` hands the analyst panel-model prose as a bare JSON tool result, undelimited. That entry point postdates this ticket ([029](029-serve-vote-reasons-to-the-analyst.md)); it is named in `docs/least-privilege.md` rather than left implied. |
| strict {A, B, neither} enum output | **superseded, not met.** The shape is strict — `with_structured_output(PanelVoteOutput)`, and a parse failure raises rather than being filed as a vote — but there is no `neither`: [002](002-decide-vote-schema.md) settled on a forced binary for v1 and the map defers `neither` to B-era. Recorded as superseded rather than done, because a reader of the table should not conclude the third option exists. |
| position randomisation | **already true.** |
| plain-text rendering | **already true**, with a test that fails if model output ever reaches a markup sink. |
| size/format limits | **half built.** Sizes capped on all three untrusted fields plus the analyst's composer. **No format constraint**, deliberately: a headline is free text in any language, so any allowlist narrow enough to be useful would refuse real copy. The ask is not fully met and the reason is recorded rather than the gap being papered over. |
| ONE screening layer | **built**, blocking on detection. |
| absorb 006e's denylist | **moot** — grep finds no denylist anywhere. It was removed already. |
| document least privilege | **built:** `docs/least-privilege.md`. |

## The trap in the nonce, which nearly cost the vote cache

`configuration` is half the vote cache key, and it is built by rendering the
prompt scaffold with blank inputs — so an edit to the template invalidates
cached votes automatically, with nobody having to mirror the prompt by hand.
That is a good design, and the nonce walks straight into it.

`get_panel_llm` is a FastAPI dependency, so a **fresh adapter is built per
request**. A random nonce inside the scaffold would therefore give every request
its own `configuration`, its own fingerprint for every vote, and a cache that
**never hits again** — silently, at full price, with nothing failing.

The suite could not have caught it. `test_configuration_declares_everything_the_adapter_binds`
asserts that *different* knobs give *different* keys; **nothing asserted that
identical knobs give the same key.** That test now exists, and was verified by
leaking the wire nonce into the key and watching it fail.

The fix is a fixed sentinel (`CACHE_KEY_NONCE`) for the key and randomness only
on the wire: the key records *"asked inside a sealed envelope"*, not *"asked
inside envelope #76e8ebe9"*.

**One-time cost, on the record:** the prompt template genuinely changed, so
`configuration` changed, so every vote in the ledger is now stale. The next run
of any previously-run test pays again. That is the cache working as designed —
the ask changed — but it is real money, once.

## Screening: what was chosen and what was rejected

**OpenRouter Guardrails was ruled out** — not on merit. It is configured at
Workspaces → Guardrails or via the Management API, and the account holder here
is not an admin. Recorded because it would otherwise look like the obvious
choice to the next reader: it needs no code at all, and its budget enforcement
returns **402**, the exact status this codebase already handles end to end.

Had it been available, two of its modes would still have been forbidden:

- **Redact would corrupt tests.** It replaces matched content with
  `[PROMPT_INJECTION]`, so the panel would vote on text the customer never
  wrote — and `vote_fingerprint` hashes the *original* option strings, so the
  redacted vote would be cached under the unredacted key and replayed forever.
- **DLP must stay off.** Its NLP types redact person names and addresses, and
  this product's legitimate inputs are made of exactly those.

**Mistral Moderation was considered** and dropped once OpenRouter turned out to
serve safety classifiers directly: `openai/gpt-oss-safeguard-20b` and
`meta-llama/llama-guard-4-12b` are both reachable with the key the product
already has, so no second provider and no second key.

**`gpt-oss-safeguard-20b` was chosen over Llama Guard** because it is
policy-conditioned rather than carrying a fixed harm taxonomy. The risk here is
not a category of harm — a headline saying "ignore previous instructions" is not
*harmful*, it is merely **addressed to the wrong reader** — and no published
taxonomy names that. It is also cheaper: ~$0.00004 per test, about 0.2% of a
dev run.

The consequence is that **the policy is the detector and the model is only the
engine**, so its quality is ours. The false positive that would have made it
useless is specific to this product: **marketing copy is made of imperatives**,
and a generic injection detector flags "Buy now" and "Don't miss out" — the
exact register of the thing under test. The policy spends a paragraph saying so.

## Screening blocks — and the first draft of this ticket was wrong about that

This ticket originally shipped screening in **flag mode**: log a detection, run
anyway. The argument was that a successful injection is worth only one biased
vote, so refusing a paid run costs more than the attack. The user rejected the
reasoning, and was right to. It failed twice:

- **It reasoned about impact under today's architecture.** "Low impact" is a
  claim about a snapshot. A control justified by a small blast radius disappears
  the moment the radius grows, and nothing fails to mark the change.
- **It was wrong on its own terms.** The ceiling broke under the first probe —
  a crafted headline becomes a vote reason, `read_reasons` hands reasons to the
  analyst, and the analyst held a tool that spends money.

It also used one layer as an excuse not to build another, which is the fallacy
defence in depth exists to prevent.

**What ships instead.** A detection raises `UnsafeInput` and the endpoint
answers **400** with a sentence naming the remedy; the screener's own words
never travel, since a refusal quoting them would be a channel into the response
body. Refusing is cheap because screening runs before the panel, so a blocked
run buys no votes.

**The two failure modes are kept apart**, which was the specific mistake worth
naming: an *unreachable* screener still lets the run through, because
availability is our problem and a screening outage must not become a product
outage. Collapsing detection and availability gives a layer that is neither safe
when it works nor available when it does not.

## The spend path was deleted, not gated

`run_panel_test` bought a whole new panel. Its only guard was a sentence in its
own description asking the model not to call it unprompted — a prompt rule, in a
codebase that elsewhere calls prompt rules unassertable — while the route to it
was real: headline → vote reason → `read_reasons` → analyst → tool.

The first fix bound the tool only when a request field said so. It worked, and
it was still the weaker answer: a flag is a thing a later change can get wrong.
**The tool is now gone.** Every tool the analyst holds reads; none spends, none
writes. `/chat` no longer constructs a panel model at all, so the absence shows
in the endpoint's signature rather than living in a boolean.

Three things fell out of it, each worth more than the feature:

- `ToolDeps` lost its translator, panel model and panel size. What a reader
  needs is a connection and an embedder.
- `stream_analyst`'s `except OutOfCredit` handler became **unreachable** and was
  removed. `OutOfCredit` is raised only by the vote path and the pipeline,
  neither of which the analyst can now touch; a 402 from the embedder still
  lands on the `APIStatusError` arm.
- The step budget went 10 → 8 with the tool surface, the derived formula
  working rather than a number being tuned.

Nothing was lost: [030](030-report-reading-order.md) already gave the report a
**Test again** control, which goes through `/evaluate` where the screening, the
caps and the delimiting live.

**Found by using it.** The first fix left the analyst unable to re-run and the
client unable to grant permission, so the capability was simply dead — and worse,
the analyst confabulated around the gap, offering to collect a panel size and
country quotas for a run it could not make, using parameters the tool never had.
A prompt rule now states what it can and cannot do, so it names Test again
instead of inventing the shape of a thing it cannot do.

## The boundary that moved after this ticket was written

[029](029-serve-vote-reasons-to-the-analyst.md) put another model's free text
into the analyst's context. Input screening structurally cannot cover it — that
text is generated *after* the request leaves us. The nonce delimiting and the
recomputed-figures rule are what stand there instead; the exposure is prose
only. Recorded in `docs/least-privilege.md` rather than solved here.

## What review caught afterwards

Worth listing, because most of it was documents claiming more than the code did:

- `docs/least-privilege.md` still ended with "**No blocking.** revisit when flag
  mode has produced evidence" — the opposite of what shipped, in the same file
  that argues for blocking. A reader would have taken the stale half as current.
- "Every verdict figure is recomputed" overstated `analysis_facts`: exactly one
  is. `tally`, `counts`, `polling`, `region_match` and `panel` are read off the
  client's request, which is safe only under the same assumption as everything
  else in §1 and fails at the same moment.
- Three comments still described the spend path this branch deleted, including
  the step budget's "tripwire, not the spend gate".
- `screen_inputs` returned rather than continued on a transient failure, so one
  error while screening the target silently skipped both headlines — a wider
  hole than the fail-open it was meant to be.
- `assert isinstance` in the screener would vanish under `python -O`, leaving a
  control that fails open; the vote path already narrows with a raise.
- Four constants shipped with rationale but no source, in a repo whose README
  requires derivation, citation or explicit sign-off — and which already has the
  `PENDING USER SIGN-OFF` marker two files away.
- `ChatRequest.message` had no ceiling while the evaluate fields did.

## The screener was inert, and only a live run could have shown it

The suite was green and the control did nothing. Every test doubles the
screener — deliberately, because it is a paid model — so nothing in CI could
observe that **both** purpose-built classifiers OpenRouter serves answer:

```
404 - No endpoints available matching your guardrail restrictions and data policy
```

`gpt-oss-safeguard-20b` and `llama-guard-4-12b` are both unreachable on this
account, so every screening call raised, the fail-open path swallowed it, and a
blatant injection ran a full paid panel. Confirmed by posting one to a running
server and watching it return 200.

Two things came out of that.

**The model changed to `openai/gpt-5-mini`** — what every other role uses, and
therefore known reachable. It flags the injection and passes "Members save half
price this week", which is the pair that matters. Nothing much is lost, because
the policy was always the detector and the model only the engine; a safety model
would be cheaper and faster, not better. First thing to revisit if the account's
data policy ever changes.

**A configuration error is no longer logged like an outage.** A timeout is a bad
day and fail-open is right; a 404 or a 401 means the model is not available to
this account and never will be until a person changes something — the control is
not degraded, it is *off*. Those now log at ERROR, naming the model, so the next
reader sees a switch in the off position rather than a blip.

Verified end to end afterwards: the injection is refused with 400 in ~9s and
buys no votes, and ordinary marketing copy still runs. The general lesson is the
one the ticket already half-knew — **a control whose every test doubles it has
not been tested** — and the cost of learning it was one unscreened paid run.

## Honest limit

The identity rule — added because the analyst answered "I am ChatGPT" when asked
its name — is the one fix here with no structural version. Ids could be withheld
and enums could be withheld; a model's knowledge of itself is in its weights, so
a prompt rule is the only lever and its effect is unassertable. Judge territory,
like [025](025-analyst-panel-composition-facts.md)'s and
[026](026-analyst-speaks-machinery.md)'s prompt halves.
