---
title: "Vote-usage instrumentation: measure what a panel test actually costs"
labels: [wayfinder:task]
parent: 010-assemble-orchestrator-graph
blocked_by: []
assignee: null
status: closed
---

## Goal

Record `prompt_tokens`, `completion_tokens` and **`reasoning_tokens`** per vote, aggregate
them per run, then spend well under a cent measuring a real one — and write the resulting
per-test cost into [003](003-decide-panel-model-and-provider.md) and
[`panel-model-selection.md`](../research/panel-model-selection.md).

First of 010's children on purpose. It is the only one whose information **expires**: a run
that finishes without these fields is a run whose cost is gone, and three sibling tickets
are guessing until it lands.

## Why this is not optional

*(State when written. The measurement is at the end of this ticket — the per-test cost is
$0.107, and the numbers below are the estimates it replaced.)*

The project currently has **no** per-test cost estimate. The old `$0.055 / 200-persona test`
was retracted rather than corrected, because it assumed a prompt cache that
[cannot exist](../research/prompt-caching.md) *and* ~80 output tokens with no allowance
for reasoning. So:

- *"$10 cap ≈ ~180 full tests"* is not plannable, and the cap is a hard 402 with no overage.
- [010f](010f-budget-guard.md)'s pre-flight check has nothing to compare `limit_remaining`
  against.
- [010b](010b-partial-run-threshold.md) is reasoning about run economics without knowing them.

And there is nothing to mine: [014](014-targeting-manipulation-check.md) and
[015](015-task-framing-sensitivity.md) ran ~7,000 votes between them and logged none of it.

## The one real technical wrinkle

`ChatOpenAI.with_structured_output(PanelVoteOutput)` returns the **parsed pydantic object**,
which means the `AIMessage` — and with it `usage_metadata` — is discarded. So `usage` is not
merely unlogged today, it is unreachable through the current call.

Two ways out, and the choice is this ticket's:

- `with_structured_output(..., include_raw=True)`, which returns a dict of
  `{"raw", "parsed", "parsing_error"}` — usage lives on `raw.usage_metadata`. Internal to
  `OpenRouterPanelLLM.vote`; getting the number back out is not, and **does** change the
  `PanelLLM` protocol (see "This does change the `PanelLLM` protocol" below).
- A LangChain callback handler collecting usage out of band. Keeps the call shape but puts
  the numbers somewhere less obviously attached to the vote they belong to.

Prefer `include_raw=True`: the usage belongs to that vote.

### Checked against the installed source before building

langchain-openai 1.3.5, langchain-core 1.4.9. Five things the build would otherwise have had
to discover; the last two change what this ticket does.

**`include_raw=True` cannot change the request.** `ChatOpenAI.with_structured_output`
forwards to the base implementation (`base.py:3915`), which returns
`RunnableMap(raw=llm) | parser_with_fallback` (`base.py:2564-2572`). The bound model is
identical — only the output plumbing is rewired. So the switch cannot move a single prompt
token, and therefore cannot perturb what [014](014-targeting-manipulation-check.md) and
[015](015-task-framing-sensitivity.md) measured.

**`reasoning_tokens` does reach `usage_metadata`.** The mapping is unguarded
(`base.py:4159-4161`): `completion_tokens_details.reasoning_tokens` →
`output_token_details["reasoning"]` — though the key is built as
`f"{service_tier_prefix}reasoning"`, so a `priority` or `flex` service tier moves it to a
prefixed key (`base.py:4146`). Read it by the name the tier implies, not by a literal.

OpenRouter's usage-accounting docs state full usage details are always included, and that
`usage: {include: true}` is deprecated with no effect.
The feared finding — the dominant cost term invisible through this stack — does not
materialise.

Everything in this paragraph about OpenRouter, and every OpenRouter claim in the effort
section below, is read from their published docs and **cannot be confirmed from local
source**. Docs and providers disagree; the calibration run is what settles them.

**Absent is not zero.** `base.py:4180` filters `if v is not None`, so a provider that omits
`reasoning_tokens` produces an *absent key*, not a zero. Treating `None` as `0` would
understate the bill by its largest term, so the distinction has to survive into the type:
`int | None`. The same holds for `usage_metadata` itself, which is `None` when a response
carries no usage at all (`base.py:1845` guards on it).

**OpenRouter reports actual `cost`, and `usage_metadata` throws it away.** The provider
returns `cost` and `cost_details` alongside the token fields; `_create_usage_metadata` maps
only tokens, because `UsageMetadata` has no cost field. The raw dict survives intact:
`llm_output["token_usage"] = token_usage` (`base.py:1860`), merged into `response_metadata`
for single-generation results (`langchain_core/language_models/chat_models.py:2014-2018`),
and the openai SDK's models are `extra="allow"` (`_models.py:128-129`) so non-OpenAI fields
are not stripped in transit.

So `raw.response_metadata["token_usage"]["cost"]` should be **the bill**, where the
$0.25/$2 derivation below (sourced in
[`panel-model-selection.md`](../research/panel-model-selection.md)) is a *model* of it.
Note that this is a three-hop derivation from source — `base.py:1860` →
`chat_models.py:2014-2018` → `extra="allow"` — and **has not been observed on the wire**; the
first call either produces a `cost` key or turns this paragraph into a correction. Record
both figures. They should agree; if they do not, that discrepancy is the finding — and it is
what [010f](010f-budget-guard.md) needs, since
`limit_remaining` is denominated in the same credits. That dict is provider JSON, so narrow
the value to a number rather than casting it.

**One behavioural change to guard.** With `include_raw=True`, parse failures stop raising —
they arrive as `{"parsed": None, "parsing_error": <exc>}`. Today's `isinstance` check would
still raise, but with the whole dict in the message, including the raw model output; 008
already ruled that class of string log-only. Branch on `parsing_error` explicitly, and keep
a test on it.

## Reasoning effort: the only cost lever, and why it is two arms rather than a default

Reasoning tokens bill at the **output** rate — $2/M against $0.25/M input — and never appear
in the response. Prompt caching [cannot fire](../research/prompt-caching.md) at our
~300-370 token prompt, so effort is the only knob that reaches the dominant term. It is the
cost lever [008](008-build-panel-evaluation.md) concluded did not exist.

**The parameter shape — and this was got wrong first time round.** Both fields do go through
`_default_params` verbatim (`base.py:1352-1353`), which is what the original reasoning here
rested on. What it missed is `_use_responses_api` (`base.py:1751-1764`): **`self.reasoning is
not None` is one of the conditions that switches langchain to the Responses API.** So setting
the unified object does not merely rename a parameter, it moves the call to a different
endpoint — one whose response carries no `token_usage` and therefore **no `cost`**, and which
nothing in this project had ever been measured against. `reasoning_effort` is not in that
condition list, so it stays on Chat Completions.

Measured, not reasoned: the object form returned Responses-shaped metadata with the cost
missing on 10/10 votes, `reasoning_effort` returned the cost on 10/10, and forcing
`use_responses_api=False` alongside the object had the request rejected outright. So pass
**`reasoning_effort="low"`**. The provider's documented vocabulary — `max | xhigh | high |
medium | low | minimal | none` — is unchanged; only the field carrying it is.

**`exclude: true` is not a saving.** It hides the trace while still reasoning and still
billing. Only lowering the effort lowers the count, and only the count lowers the cost.

**Where the knob lives — not middleware.** `wrap_model_call` and `ModelRequest` ship in the
`langchain` umbrella package, which is not a dependency (`pyproject.toml:7-15` declares
`langchain-openai` alone) and which pulls in the LangGraph dependency
[010](010-assemble-orchestrator-graph.md) just removed from v1. Structurally it also has
nothing to wrap: middleware varies the model *between* an agent loop's calls, and a vote is
one structured call. Effort is panel configuration in exactly the sense `question` already is
(`llm.py:124-127`), so it belongs beside it as a constructor keyword, and an arm is an
instance — the dict `experiments/manipulation_check.py:328-336` already builds per framing.
Middleware's real home in this project is [012](012-build-analyst-chatbot-tools.md), which is
an agent loop.

**Measure both arms; decide neither here.** Two 10-vote arms, default and `low`, is still
well under a cent and turns "we could set effort low" into two numbers. Shipping `low` is a
separate decision, because 014's **0.66 first-position rate** (5,400 votes) and 015's framing
sensitivity were both measured at default effort — and less deliberation is precisely the
condition under which a positional shortcut gets *stronger*. Cheaper votes at a higher
first-position rate are not cheaper; they are a different panel with a rewritten
counterbalancing argument. That call needs 014's harness re-run, sized by the cost this
ticket is about to measure.

**Two traps in the low arm, both cheap to guard.**

- *A silently-ignored parameter is indistinguishable from a null result.* Wrong shape, or a
  provider that does not honour it, and the low arm looks identical to default — where "low
  does not help" reads exactly like "low never applied". So `reasoning_tokens` must visibly
  **drop** between arms. If it does not, suspect the parameter before believing the finding.
- *Cheaper reasoning can fail the schema.* We send `response_format: json_schema`
  (`with_structured_output`'s default), so degraded compliance converts a cost saving into a
  **failed vote** — strictly worse at $0 saved. Check `parsing_error` stays `None` across the
  arm, which the explicit branch above makes observable rather than a mystery raise.

**Checked and dropped: `effort: 'none'` does not get `temperature` back.** langchain does
strip a non-default temperature for gpt-5 unless effort is `'none'`, but the guard is
`model_lower.startswith("gpt-5")` (`base.py:1171-1176`) and `config.py:20` sets
`openai/gpt-5-mini` — the branch never fires for our model id. So it says nothing about
[003](003-decide-panel-model-and-provider.md)'s 400, which came from the provider *because*
langchain passed the temperature through, and [010e](010e-per-vote-cache.md)'s framing does
not rest on langchain behaviour at all. Recorded so the next reader does not re-derive it.

## Where the numbers go

Aggregate **per run**, not per vote — a 200-vote run wants one line, not two hundred. The
per-vote figures are only interesting as a distribution (see below), so keep them in memory
and emit totals.

`collect_panel_votes` returns `PanelVotes`; usage is a natural third field beside `records`
and `failures`. It is the same shape argument the failures made: a caller that cannot see
what a run cost cannot report it.

Store the per-vote list and **derive** the totals rather than storing both — a stored total
can drift from the list it summarises, and 010f wants a p99 that only the list can give.

The honest question the totals function has to answer: what is the reasoning total when only
*some* votes reported the field? Summing the known ones understates it silently, so report the
total alongside how many votes contributed to it.

### This does change the `PanelLLM` protocol, and the churn is the cost

The bullet above is right that `include_raw` is internal to `OpenRouterPanelLLM.vote` — but
getting the number *out* is not. `vote` returns `PanelVoteOutput`, so the protocol has to
return the usage beside it for `_cast_vote` to hand it to the collector.

Prefer that over the callback handler, and prefer it over an accumulator owned by the LLM:
`_cast_vote` already returns a value from a worker thread, so aggregating in the collector's
own loop needs no lock, and the usage stays attached to the vote it belongs to. An accumulator
on the LLM needs no lock either (`list.append` is atomic under the GIL) and touches nothing —
but it is **unbounded mutable state with no run boundary**, so reusing one LLM for two panels
silently merges two bills with nothing in the type system marking it. `PanelVotes` exists so a
run's facts travel with the run.

The cost, so it is chosen rather than discovered: **eight fakes** implement `vote`
(`tests/conftest.py:18`, `tests/test_main.py:59`, three in `tests/test_manipulation_check.py`,
three in `tests/test_vote.py`) plus `experiments/manipulation_check.py`, which is committed
014/015 code. All mechanical. Make the usage field optional so a fake is not forced to invent
token counts.

Then test the alignment the way 008 tested presentation order: assert **mis-pairing** is
caught. Usage zipped onto the wrong record is a defect where every value is real and nothing
downstream could detect it.

## The calibration run

A **10-persona** panel against the real model, which costs a fraction of a cent and settles
the order of magnitude. Do not wait for [010c](010c-panel-test-pipeline.md) — `FIXED_PANEL`
plus `collect_panel_votes` is enough to run this today.

Drive it through `collect_panel_votes` rather than a private thread pool, or the run measures
a harness instead of the thing that ships. `backend/experiments/` is the precedent — a CLI
module writing jsonl, with `analysis.py` reading it back.

Record, in `panel-model-selection.md`:

- mean and spread of `prompt_tokens` (the ~300–370 estimate, confirmed or corrected against
  a real request with the schema included),
- mean and spread of `completion_tokens` and `reasoning_tokens`,
- **`cost` as OpenRouter reports it**, and the derived cost of a 200-vote run at the sourced
  $0.25/$2 per M, so the model of the bill can be checked against the bill,
- both effort arms, side by side,
- **the observed per-vote latency distribution**, which is what
  [010f](010f-budget-guard.md) needs to set a read timeout instead of leaving the SDK's 600s.

**Latency has to be timed per vote, not off the wall clock.** Concurrency is 25, so ten votes
fire at once and the run's elapsed time is roughly *one* vote's latency, not ten.
The only latency figure this project has is **4.65s per vote**, and it survives as a *comment*
(`experiments/manipulation_check.py:57-58`): none of the five files in `experiments/out/`
carries a clock, so it cannot be re-derived from the 7,630 votes already paid for. Treat it as
a soft prior, and note that this is the sharpest argument for the ticket — 014 measured
latency and lost it.

**Free while we are here:** `prompt_tokens_details.cached_tokens` should be `0`, which turns
`prompt-caching.md`'s central conclusion from a derivation off published thresholds into an
observation. The measured `prompt_tokens` either confirms or corrects that doc's ~300–370
assumption at the same time.

Ten votes is not a distribution. State it as an order-of-magnitude reading, and note that
the 200-vote run in 010c supersedes it — the point is to stop planning against a retracted
number, not to publish a benchmark.

## Out of scope

Cost *display* in the UI, and any budget enforcement. This ticket measures; 010f decides
what to do about it.

**Choosing a reasoning effort to ship.** This ticket measures both arms and writes the
numbers down. Adopting `low` retires 014's and 015's measurements until their harness is
re-run, which is its own decision and its own spend — and one this ticket's numbers are what
make decidable.

## Closed 2026-07-28

**$0.107 per 200-vote test at default effort, ~93 tests inside the $10 cap.** Full readings in
[`panel-model-selection.md`](../research/panel-model-selection.md) and the decision-facing
summary in [003](003-decide-panel-model-and-provider.md). The raw rows land in
`backend/experiments/out/cost.jsonl`, which is **gitignored** like every other experiment
artifact here — so the two documents are the durable record, and `--report` re-reads a local
run without paying for it again.

What the numbers said, beyond the headline:

- **The retracted ~$0.055 was low by ~2×, and output was the reason** — ~234 tokens per vote
  against the assumed ~80, **68% of it reasoning**. Input was over-estimated at the same time
  (270 tokens, not 300–370) but is only a sixth of the bill.
- **The provider's `cost` equals the list-price derivation exactly**, bit-for-bit on 20/20
  votes. So [010f](010f-budget-guard.md)'s pre-flight check can use either, in the same units
  as `limit_remaining`.
- **Caching confirmed dead by observation** — `cached_tokens` 0 on every vote, prompt 270
  tokens against a 1,024 minimum. Wider margin than
  [`prompt-caching.md`](../research/prompt-caching.md) derived.
- **`low` halves the bill** ($0.057) and cuts latency 44%, with 0 parse failures across 10
  votes. Not adopted — that needs 014's and 015's harness re-run first, and the effort arms
  exist so that decision has numbers rather than an argument.
- **A read timeout still cannot be set.** 10 votes per arm gives a p95 over ten points and no
  p99, which is the figure 010f wants. [010c](010c-panel-test-pipeline.md)'s first full run
  supplies it. Recorded so nobody reads the p95 above as the answer.

Two deviations from the ticket as written:

1. **The parameter is `reasoning_effort=`, not `reasoning={"effort": ...}`** — see the
   correction in the effort section. The object form silently changes endpoint and loses the
   cost figure, which cost one confounded arm to discover.
2. **A parse failure now carries only its exception type.** The ticket assumed the failure's
   message was safe to log; langchain formats it as `f"Invalid json output: {text}"`, so it
   carried the model's whole reply into the log. The type is what a caller acts on.

Not done here, and deliberately: 010c's 200-vote run supersedes these figures, and the
reasoning-effort decision is its own ticket when someone wants it.
