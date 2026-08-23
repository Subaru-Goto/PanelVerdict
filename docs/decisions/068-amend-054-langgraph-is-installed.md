---
title: "Amend 054 — langgraph is installed and interrupt is available"
labels: [wayfinder:task]
parent: 055-map-public-demo
blocked_by: []
assignee: Subaru-Goto
status: closed
---

## Closed absorbed (2026-08-21)

Everything this ticket asked for happened inside the resolutions of its two subjects:
[054](054-nothing-confirms-the-panel-before-the-money-is-spent.md)'s closing note records
the false claim and its correction, and [067](067-where-is-a-hand-authored-graph-worth-it.md)
answered the question 054's recommendation was waiting on — including the
checkpointer-survives-restart dependency this ticket flagged, now a `blocked_by` edge on
[076](https://github.com/Subaru-Goto/PanelVerdict/issues/166).

## Goal (as originally posed)

[054](054-nothing-confirms-the-panel-before-the-money-is-spent.md) claims:

> *"`langgraph` is not importable in this environment and is not a declared dependency."*

**The first half is false.** It was checked with the system `python3` rather than the
project's venv. Verified inside `backend/.venv`:

```
langgraph            1.2.10
langgraph-checkpoint 4.1.1
langgraph-prebuilt   1.1.0
langgraph-sdk        0.4.2
```

`langgraph.types.interrupt` imports fine, and `create_agent` is built on `StateGraph`
(`langchain/agents/factory.py`). The second half stands: it is transitive via `langchain`,
not declared in `pyproject.toml`.

Correct the ticket, and correct **what it changes about the conclusion**:

- 054 argued the spend gate must be HTTP-shaped partly because the framework primitive was
  unavailable. **The real reason is different and still holds:** `/evaluate` has no graph, so
  there is nothing to interrupt — `create_agent` appears only in `analyst.py`. The obstacle is
  the *absence of a graph*, not the absence of the library.
- That turns the question into a genuine choice rather than a constraint, and it belongs to
  [067](067-where-is-a-hand-authored-graph-worth-it.md): build the graph and use
  `interrupt()`, or keep two endpoints. 054's recommendation stands **until 067 answers**, and
  should say so.
- Note also that `interrupt()` would need a checkpointer surviving restart, so it depends on
  [046](https://github.com/Subaru-Goto/PanelVerdict/issues/144) — a paused run on `InMemorySaver` dies on
  deploy.

**Ownership, since the frontmatter and body could look contradictory:** this ticket belongs to
[the public-demo map](055-map-public-demo.md) — writing the correction is this map's work —
while [054](054-nothing-confirms-the-panel-before-the-money-is-spent.md) itself stays a child
of [000-map](000-map.md) and is not re-parented.

PR #115's description carries the same wrong claim. It is merged and immutable, so the
correction lives in the ticket rather than in the history.
