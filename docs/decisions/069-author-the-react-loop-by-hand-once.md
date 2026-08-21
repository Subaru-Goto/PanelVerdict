---
title: "Author the ReAct loop by hand once, as an exercise, and keep the notes not the code"
labels: [wayfinder:research]
parent: 055-map-public-demo
blocked_by: []
assignee: subaru.dayo@gmail.com
status: closed
---

## Closed out of scope (2026-08-21)

Both legs this ticket stood on gave way the same day:

- **The learning mode is gone.** Author's direction: *"There is no learning mode, fully
  agentic coding"* — which retires the map's framework-learning goal this ticket existed
  to serve.
- **The gap it covered no longer exists.** Its whole justification was that *"nodes and
  edges are precisely what `create_agent` hides"* and no product ticket would ever
  exercise them. [067](067-where-is-a-hand-authored-graph-worth-it.md) resolved to the
  middle path, so [076](https://github.com/Subaru-Goto/PanelVerdict/issues/166) now builds
  `StateGraph`, `add_node`, `add_conditional_edges`, and `interrupt()` in **production
  code** — the exercise would duplicate, as a throwaway, what the map now ships.

## Question (as originally posed)

What does `create_agent` actually hide, learned by building it rather than by reading?

Exists because the map's framework-learning goal is **not** fully served by the product
tickets, and saying otherwise would be a comfortable fiction. Under
`create_agent` you genuinely touch most of LangGraph:

| technique | touched by the product tickets? |
|---|---|
| state — `state_schema`, `context_schema` | yes (012's closures become `context_schema`) |
| persistence — checkpointers, `thread_id` | yes ([046](https://github.com/Subaru-Goto/PanelVerdict/issues/144)) |
| middleware | yes ([052](https://github.com/Subaru-Goto/PanelVerdict/issues/149), [064](064-the-cost-ceilings.md)) |
| HITL — `interrupt_before` / `interrupt_after` | available as `create_agent` parameters |
| event streaming, per-node traces | yes (shipped; [065](https://github.com/Subaru-Goto/PanelVerdict/issues/159)) |
| **`StateGraph`, `add_node`, `add_edge`, `add_conditional_edges`, reducers** | **no** |

That last row is the whole gap: **nodes and edges are precisely what `create_agent` hides**,
and [067](067-where-is-a-hand-authored-graph-worth-it.md) may legitimately answer *"nowhere
yet"*, at which point nothing on this map would ever exercise them.

## Shape: a scratch file, and the code is thrown away

Re-author the analyst's loop as a `StateGraph` — model node, tool node, conditional edge,
`compile()` — run it against the existing `ScriptedChatModel`, and compare against what
`create_agent` builds.

**Nothing merges but the write-up.** The point is not a better analyst; it is knowing what
the abstraction contains. Keeping the code would put a working, tested component at risk for
no product gain, and `stream_analyst`'s fixed-sentence error discipline — pinned by
`test_error_events_never_carry_model_text` — would have to be re-established inside it.

`analyst_chat_model`, `build_tools` and `_SYSTEM_PROMPT` are reused **unchanged**. Its
docstring already names the boundary being crossed: *"Just construction: tool binding, the
loop, and error shaping all belong to the agent."*

## What the write-up has to answer

- **the reducer.** `MessagesState` annotates `messages` with `add_messages`, so
  `{"messages": [response]}` appends. Define state without that reducer and the identical
  line **overwrites the history** — the model loses context and returns a confidently wrong
  answer rather than an error. Establish this by making it happen once.
- **`bind_tools`.** An unbound model emits no tool calls, so the conditional edge always
  ends and the agent silently never uses a tool while appearing to work.
- **what `create_agent` adds beyond the four-line loop** — read
  `langchain/agents/factory.py` and list it, rather than assuming the prebuilt graph is only
  the ReAct cycle.
- **which of those the product would have to re-implement** if
  [067](067-where-is-a-hand-authored-graph-worth-it.md) ever answers yes.

## Why it comes before 067, not after

067 asks whether a hand-authored graph is worth building. Answering that from documentation
is guessing. This ticket makes the answer come from experience — so it is deliberately
**not** wired as a blocker, since 067 can be answered without it, but doing this first makes
that answer worth more.

Output: a markdown summary under `docs/research/`. Scratch code stays out of the repo.
