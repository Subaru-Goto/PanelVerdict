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

### Correction: "the pipeline is linear" is not the argument (2026-08-05)

An earlier draft rested on it, and it does not survive a look at the code. `pipeline.py:274-300`
is:

```
for chunk in chunks:                    # a cycle
    fan out 25 votes concurrently       # Send-shaped fan-out
    if OutOfCredit: break               # conditional exit
    tally + stopping_decision           # a barrier: needs the whole chunk
    if confirmed twice: stop            # second conditional exit
```

A cycle, a barrier, two conditional exits and a 25-way fan-out inside each iteration. That is a
**textbook LangGraph shape**, not a straight line — `Send`, an implicit join,
`add_conditional_edges`, an edge back to the vote node. Anyone arguing from topology will
conclude the opposite of what that draft claimed, so the argument has to be made on value.

### The actual argument: what would a graph buy that is not already bought?

- **Durable resume is already delivered, more cheaply, by the vote ledger.** `vote_fingerprint`
  plus `ON CONFLICT (request_fingerprint) DO NOTHING` means a re-run re-asks only what has no
  row. That is resume at the **domain** level: provider-independent, and it survives swapping
  persistence later. A graph checkpointer would duplicate it, leaving two resume mechanisms to
  keep honest. **This is the whole case.**
- **Sync versus async is real work.** 25 blocking SDK calls in threads against async-oriented
  nodes means touching all five `init_chat_model` sites in `llm.py` and everything binding them.
- **010e's byte-identical replay is a documented guarantee**, and it is what makes the $0 demo
  possible at all ([061](061-a-zero-cost-demo-page.md)). Rewriting the stopping loop risks it.
- **This is the project's most delicate logic** — adaptive stopping, the ledger, chunked
  concurrency. Most likely to break subtly, least likely to break loudly.

### The middle path worth costing before choosing either extreme

**Hand-author the graph around the vote loop, not through it.** Nodes for screen → select →
confirm → vote → assemble, where `confirm` holds the `interrupt()` and the **vote node calls
today's `collect_panel_votes` unchanged**, `ThreadPoolExecutor` and all.

That buys the things actually wanted — real nodes and edges in production code, a real
`interrupt()` for the spend gate, per-stage LangSmith spans — while the chunk loop, adaptive
stopping and the ledger stay untouched inside one node. It is a far smaller change than making
each vote a `Send`, and it does not put the replay guarantee at risk.

Cost this before concluding either "nowhere" or "rewrite the pipeline".
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
