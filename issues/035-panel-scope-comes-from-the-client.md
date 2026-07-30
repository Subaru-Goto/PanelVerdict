---
title: "The analyst's panel scope is supplied by the caller, so `search_personas` can reach any persona in the pool"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Problem (found by security review, 2026-07-30)

`search_personas` is scoped to the current test's voters:

```python
panel_ids=[vote.persona_id for vote in result.votes]
```

`result` is `ChatRequest.result` — the whole `EvaluateResponse`, posted by the
client. So the ids that bound the search are the ids the caller chose to send. A
client that puts arbitrary `persona_id`s in `votes[]` can point the analyst's
search at any persona in the pool, not just the panel that voted.

**Not exploitable today, and that is the whole reason to write it down now.** The
pool is synthetic, shared, and belongs to nobody: the personas a caller could
reach this way are the same ones any test could have drawn. Nothing leaks
because there is nothing private in there yet.

## Why it matters anyway

`docs/least-privilege.md` holds this exact code up as the model for how data
access should be defended:

> **Data access is defended by scoping, never by a classifier** — a classifier
> is a model guessing whether text looks like an attack, and its blind spots are
> ours, while a `WHERE` clause has none.

The `WHERE` clause is real. What the document does not say, and should, is that
**the values bound into it come from the request**. The SQL cannot be widened by
anything the model emits — that part holds, and it is the part that stops
prompt injection. But it can be widened by the caller, which is a different
threat and one the document currently reads as covered.

So the honest statement is: scoping defends against the *model*, not against the
*client*. Today those are the same party. The moment they are not, this is the
first thing that breaks, and it will break quietly because the code looks
correct.

## Fix, when there is anything to protect

The server must derive the panel from something it trusts rather than from the
payload — load the run under the session's tenant and ignore what the body
claims. That is the same change `docs/least-privilege.md` already names as the
structural blocker for multi-tenancy:

> **`ChatRequest` carries the entire `EvaluateResponse` from the client.** That
> is safe only while a caller can send nothing but their own data.

Which makes this ticket a concrete instance of that one, not a separate problem.
Doing it means persisting a run and giving `/chat` a run id — a real change, and
one with no benefit until there are accounts, which is why it is filed rather
than built.

## Not doing now

- **Validating that `persona_id`s belong to a real panel.** It would narrow
  nothing: a caller can name ids that *are* a real panel. Checking membership
  without an owner to check it against is the shape of a control rather than a
  control.
- **Removing `search_personas`.** It answers a question readers actually ask,
  and the exposure is a synthetic pool.

## Related

- [013](013-guardrails-mvp.md) — the guardrails work whose review found this,
  and whose `docs/least-privilege.md` is the document to amend when it is fixed.
- [012](012-build-analyst-chatbot-tools.md) — where the panel-only scoping was
  decided, for the report's sake rather than for isolation.
