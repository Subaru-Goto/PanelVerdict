---
title: "Where is a hand-authored graph worth it, if anywhere?"
labels: [wayfinder:grilling]
parent: 055-map-public-demo
blocked_by: []
assignee: null
status: open
---

## Question

**Default decided: keep `create_agent` wherever it fits** (2026-08-04). So this ticket is
narrow — is there *one* place a hand-authored `StateGraph` earns the rewrite?

The starting facts, verified rather than assumed:

- `langgraph` 1.2.10 is **already installed** (transitive via `langchain`), and
  `create_agent` **already compiles a `StateGraph`** (`langchain/agents/factory.py`). The
  analyst therefore already runs on a graph.
- `create_agent` gives the prebuilt ReAct shape: `START → model → (tools → model)* → END`.
- Hand-authoring buys three things that shape cannot express: **`interrupt()`** — pause,
  persist, resume from a *later HTTP request* — **durable resume** at node granularity, and
  **per-node traces** instead of one span.

**The only candidate worth arguing:** `/evaluate`'s spend gate.
[054](054-nothing-confirms-the-panel-before-the-money-is-spent.md) recommends two HTTP
endpoints, and it reached that partly on a claim this map has since found false — see
[068](068-amend-054-langgraph-is-installed.md). With `interrupt()` genuinely available, the
alternative is one graph that pauses and resumes.

What the answer has to weigh:

- **`/evaluate` is linear**, which is exactly why [000-map](000-map.md) deferred LangGraph. A
  linear graph is a more elaborate way to write a function that already works.
- **`collect_panel_votes` uses a `ThreadPoolExecutor` with 25 workers.** LangGraph nodes are
  async-oriented, so a vote node means deciding how 25 threads live inside it, or
  restructuring to a `Send` fan-out. Real work against tested code that carries adaptive
  stopping and a vote ledger.
- **`interrupt()` needs a checkpointer that survives a restart**, so it depends on
  [046](046-analyst-threads-die-on-restart.md)'s `PostgresSaver` — otherwise a paused run
  dies on deploy.
- **The analyst is not a candidate** unless [018](018-audience-research-knowledge-base.md)
  needs a mandatory retrieval node the ReAct loop cannot express. Check that before ruling it
  out for good.

**And `create_agent` already exposes more than this ticket first assumed.** Its parameters
include `state_schema`, `context_schema`, `checkpointer`, `middleware`, `store`, `cache`, and
crucially **`interrupt_before` / `interrupt_after`** — so a pause point does not strictly
require hand-authoring. Weigh the static interrupt against dynamic `interrupt()` inside a node
before treating HITL as the reason to build a graph.

**Answer this after [Author the ReAct loop by hand once](069-author-the-react-loop-by-hand-once.md)
if possible.** Not wired as a blocker, because this is answerable from documentation — but
answering it from documentation is guessing, and 069 turns it into a judgement from experience.

A legitimate outcome is **"nowhere yet"**, with the reason recorded so the question is not
reopened from enthusiasm.
