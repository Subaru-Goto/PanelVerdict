---
title: "The analyst's step budget is derived arithmetic, and nothing bounds a whole conversation"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## What is there today

`analyst.py:407`:

```python
limit = 2 * len(tools) + 2
```

Passed as LangGraph's `recursion_limit`. The comment is honest about what it is:

> *"the limit must strictly exceed the steps executed, measured: a one-tool round errors
> at 3 and passes at 4 … It is a tripwire and nothing more: it used to be described as one
> half of a spend gate, back when a tool could buy a panel."*

It works. Three things about it are worth changing, and the third is not a refactor.

## 1. It is arithmetic standing in for a budget

`2 * len(tools) + 2` couples the spend budget to the **number of tools**, which is not what
bounds cost. Add a fourth tool for [018](018-audience-research-knowledge-base.md)'s corpus
and the budget silently grows by two supersteps — not because the analyst should be allowed
more, but because the expression says so. The quantity a reader wants to see is *how many
model calls one turn may make*, and that is currently something you compute rather than
something you read.

## 2. It raises rather than degrades

`recursion_limit` is enforced by LangGraph's counter, which **throws**
`GraphRecursionError`. `stream_analyst` catches broadly and emits a fixed-sentence `error`
event, so the reader gets a failure — correct, but blunt. A model that has gathered its
facts and is one step over budget produces nothing.

## 3. Nothing bounds a conversation — only a single turn

**This is the real gap.** `recursion_limit` is per-invocation. A reader can send fifty
turns on one `thread_id` and each gets a fresh budget, so there is no ceiling on what one
conversation costs. Nothing anywhere counts across turns.

## What `ModelCallLimitMiddleware` gives, read from the installed API

`langchain.agents.middleware`, in the pinned `langchain` 1.3.14:

```python
ModelCallLimitMiddleware(*, thread_limit: int | None = None,
                            run_limit: int | None = None,
                            exit_behavior: Literal['end', 'error'] = 'end')
```

Its docstring: *"Thread-level: the middleware tracks the number of model calls and persists
call count across multiple runs."*

| today | with middleware |
|---|---|
| `2 * len(tools) + 2`, derived | `run_limit=N`, declared |
| raises `GraphRecursionError` | `exit_behavior='end'` finishes the turn instead |
| per turn only | **`thread_limit` bounds the conversation** |

So this maps onto all three problems, and `thread_limit` is a capability that does not exist
in the codebase at all today.

## Where this meets 045, and why it is not a duplicate

[045](045-paid-endpoints-have-no-auth-or-rate-limit.md) says the honest unit for a `/chat`
limit is *"turns per thread per window"*, and it also records why LangChain middleware
cannot serve that ticket: it runs inside the agent, after the stream has begun, so it can
never return a 429.

Both are true, and they stack rather than compete:

- **045, at the HTTP edge:** may this caller start a turn at all?
- **this ticket, inside the agent:** given a turn has started, how much may it spend?

Neither substitutes for the other. An HTTP limit cannot see that one turn looped through
eight model calls; a middleware limit cannot refuse a request.

## The interaction that has to be got right

**`thread_limit` persistence rides on the checkpointer**, and
[046](046-analyst-threads-die-on-restart.md) records that the checkpointer is
`InMemorySaver`. So a thread-level count is process-local for the same reason the transcript
is: it resets on restart and is not shared across workers. Not a blocker — a thread budget
that resets on deploy is still better than none — but it should be stated, and it is another
reason 046 is worth doing.

**And the stream needs a sentence for the new outcome.** `exit_behavior='end'` means the
turn can finish *without* the model having written a final answer. Today's failure path is a
fixed-sentence `error` event; a budget-ended turn is not an error and should not read as
one. It needs its own wording, and `stream_analyst`'s existing discipline — fixed text, no
model output in the channel — is the pattern to follow.

## Scope

- Replace the `limit` arithmetic with `ModelCallLimitMiddleware`, passing
  `middleware=[...]` to `create_agent`.
- **`run_limit` needs a number, and this repo does not ship unsourced constants.** The
  current expression evaluates to **8** for three tools, and a one-tool round was measured
  at 4 — so 8 is defensible as *"what ships today"* rather than as a new guess. Keep it,
  and say that is why.
- **`thread_limit` needs a real decision**, not a derived one. It bounds a conversation, so
  it is a product choice about how long a reader may interrogate one report. It has no
  precedent to inherit and should be signed off explicitly, the way [040](040-vote-cache-read-window.md)'s
  24 hours was.
- A test that a turn exceeding the budget ends with the reader seeing a sentence rather than
  a stack trace, and one that the count survives across turns on a thread.
- Delete `recursion_limit` only if the middleware fully replaces it. If both stay, say which
  is the backstop and why — two limits with no stated relationship is how one of them
  becomes dead.

## Done when

The step budget is a declared number rather than an expression over the tool count, a turn
that exhausts it ends with an explanation instead of an exception, a conversation has a
ceiling that persists across its turns, and both numbers are signed off rather than derived
from how many tools happen to exist.
