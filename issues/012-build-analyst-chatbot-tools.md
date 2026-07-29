---
title: "Build the 'Ask the analyst' chatbot + tools (chatbot requirement)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [010-assemble-orchestrator-graph, 011-build-report-ui]
assignee: null
status: open
---

## Goal

The chatbot + tool-calling requirement, embedded in the report and **scoped to the current test**:

- ≥3 tools (LLM decides *when*, deterministic code does *how*): `run_panel_test`, `search_personas`, `analyze_results` (+ optional `estimate_cost` / `get_test_history`),
- **suggested-question chips** rather than free composition (each chip maps to a requirement and demos reliably).

The exact chip set is fog until this ticket is worked (see map Notes).

## Decided 2026-07-29 — analyst model and slicing (user)

- **Analyst model: `openai/gpt-5-mini` for v1** — the same model as every other
  role. 003 deferred the reasoning-model pick here; the user chose consistency
  and cost over a flagship, at chat volume the difference is pennies either
  way, and it stays config (`settings.analyst_model`) so revisiting is a
  one-line change if answer quality disappoints.
- **Chat surface: the floating launcher (prototype variant C), decided by the
  user 2026-07-29.** Three variants ran on the live page against fixture data
  (A: persistent side column, B: inline Q&A appendix, C: floating launcher
  opening an overlay dock); the user picked C — the report stays a document,
  the analyst is a helper you summon. Chips live inside the dock, shown while
  the thread is empty. Candidate chip set from the prototype (final copy is
  012c's): "Why did the test stop after 50 of 200 votes?", "How sure are we
  that <headline A> wins?", "Who was on this panel?", "What would 200 more
  votes change?". Known trade recorded at the decision: the chips demo the
  tool-calling requirement and C hides them behind a click — 012c should make
  the launcher unmissable (and may consider opening the dock once, on first
  render of a fresh report).
- **The reply streams (user, 2026-07-29).** Real token streaming, not a typing
  animation over a completed reply — the first words show while the model is
  still writing. Tool rounds have no streamable text, so the stream carries a
  status signal while a tool runs and token deltas for the closing answer.
  Lands in **012b** (the transport is the endpoint's contract, and it must be
  settled before 012c consumes it): `/chat` becomes a streaming response,
  frontend reads it via fetch + ReadableStream (EventSource cannot POST).
  012a's loop stays the engine — only the transport changes.
- **Stream wire: `stream_events(version="v3")`, accepted as experimental
  (user, 2026-07-29).** The v3 protocol emits `LangChainBetaWarning` and
  LangChain may still reshape it, but it is the only mode that surfaces
  `tool-started` — the front edge the dock needs while `run_panel_test` runs
  for minutes. Known trade: the event anatomy (envelope dicts, two message
  dialects) was established by probing, not docs, so a langchain/langgraph
  upgrade can break the parsing loop in `stream_analyst`; the streaming test
  suite is the tripwire, and the fallback is `stream_mode="messages"` at the
  cost of the tool front edge.
- **`search_personas` is panel-only (user, 2026-07-29).** The tool searches
  the voters of the current test (`WHERE id = ANY(<panel ids from
  result.votes>)`), not the whole pool — the chat lives on one report and the
  chips are report questions, so the analyst talks about the people on screen.
  Pool-wide search is deferred until a real "would a different audience
  differ?" conversation needs it, which pairs with `run_panel_test` anyway.
  Two review notes (2026-07-29): the scope is honest-client scoping, not a
  security control — `panel_ids` come from client-supplied `result.votes`,
  and the pool is one shared synthetic dataset with no tenancy boundary, so
  nothing confidential is reachable either way. And HNSW being approximate,
  a selective `id = ANY(panel)` filter can post-filter candidates below
  `limit` at pool scale; at v1 size the planner seq-scans and results are
  exact.
- **Tool dependencies travel by closure (user, 2026-07-29).** `build_tools`
  grows `conn=` / `embedder=` keyword args and the tool bodies close over
  them — the pattern `analyze_results` already set. LangChain's
  `context_schema`/`ToolRuntime` earns its machinery when tools are defined
  far from where deps are known (shared tool libraries, agent-internal
  state); these tools are per-request by design, so the closure costs
  nothing. This closes the ticket's open "closures vs context_schema"
  question.
- **`search_personas` returns top-5 (user sign-off, 2026-07-29).** Convention,
  not measurement: ~40 tokens per persona summary keeps a search around 200
  tokens while giving the model enough names to answer concretely. Revisit if
  answers feel starved or bloated once real chats run.
- **Agent middleware: not adopted in 012a.** The hand-rolled loop is ~30 lines
  and needed neither effort escalation nor per-turn model swaps; the question
  stays open per the 010 amendment and gets its final answer when this ticket
  closes, informed by whether 012b's multi-tool loop ever wants either.
- **Three PRs**: 012a — `/chat` endpoint + hand-rolled LangChain tool loop +
  `analyze_results` (pure function over the tally, no new paid calls);
  012b — `search_personas` (pgvector index + query) and `run_panel_test` as
  tools; 012c — chat panel in the report + suggested-question chips, then the
  user's end-to-end UI test. A chat turn that triggers `run_panel_test` spends
  real money, so the UI must make that a deliberate act (012c's problem).

## Amended 2026-07-29 — the loop is `create_agent`; the v1/v2 line is redrawn (user)

The user clarified what 010's deferral was actually protecting v1 from: **authoring
graphs** — nodes, edges, human-in-the-loop — not the langgraph *runtime* as a
transitive dependency. `create_agent` is LangChain 1.x's front door and the API a
working engineer meets everywhere, so v1 uses it; the hand-rolled loop below is
**superseded** after one afternoon of life. Its evidence is on the record: the loop
cost ~30 lines and was not painful — the framework is adopted for idiom and
learning value, not necessity. What `create_agent` absorbs: ToolMessage plumbing,
the unknown-tool reply, the round cap (its recursion limit), and the middleware
question (middleware is its native mechanism). What stays ours: the tools, the
recompute-don't-trust facts, and the zero-interpolation system prompt.
**Conversation memory is a server-side checkpointer** (user, same day,
reversing the first draft's client-replay design): `InMemorySaver` keyed by a
client-minted `thread_id`. The deciding argument is cost, not convenience — a
text-only replay drops ToolMessages, so every follow-up re-buys the tool
calls; a checkpointed thread remembers them. Accepted with eyes open: a
restart forgets threads and a second worker would not share them — fine at
demo scale; the Postgres checkpointer is the scale-up path, not a redesign.

## Superseded 2026-07-29 — amended 2026-07-27 (010): the tool loop was LangChain-by-hand in v1

[010](010-assemble-orchestrator-graph.md) dropped LangGraph from v1, so this ticket does
not get to reach for it either: v1 builds the tool loop on LangChain's tool calling with the
message list held by the request.

This is also the ticket where the decision gets revisited. A multi-turn chat with a tool
loop, message history across turns, and possibly confirmation interrupts is the *idiomatic*
LangGraph case — unlike the linear panel pipeline, where it was not. So if v2 adopts it,
adopt it here, and let this ticket's own experience of hand-rolling the loop be the
evidence for whether it is worth the dependency. Note what the graded requirement actually
names: **tool calling**, which is this ticket's content and is framework-independent.

**Agent middleware belongs to this ticket if it belongs anywhere.** It ships in the same
`langchain` umbrella package as the graph, so it sits on the same side of the v1/v2 line.
[010a](010a-vote-usage-instrumentation.md) considered it for the reasoning-effort knob and
records why it was rejected there; the residue for this ticket is that a tool loop is the case
middleware was built for — escalating effort after a failed step, swapping model per turn — so
the question is live here and nowhere else in v1.

## Notes

- **Vector index (deferred here from 006f).** `search_personas` needs the pgvector similarity index (HNSW/IVFFlat) on ~~`interests.embedding`~~ **`personas.summary_embedding`** — 006f persists vectors but builds no index. **Amended 2026-07-26 ([006j](006j-persona-summary-embedding.md)):** the index target moves to one vector per persona, and the open question of "per-persona mean-pooled embedding vs. querying per-interest rows" is moot — the `interests` table is dropped, so there is exactly one vector to search.

  **This note assumed Alembic, which does not exist.** 006f never introduced migrations, and 006j D6 decided against them on purpose: the sampled columns are a pure function of `master_seed`, so the pool is a cache and drop-and-reseed replaces a migration. So the index is a plain `CREATE INDEX` in `schema.sql`, run by `apply_schema` like the rest.

  The concurrency advice survives the change and still has to be honored *if* migrations ever arrive — which is the moment the pool stops being reproducible, i.e. when votes and test results are persisted alongside it. It said: build with `CREATE INDEX CONCURRENTLY` (avoids locking the table), which **cannot run inside Alembic's default transaction**, so wrap it in `op.get_context().autocommit_block()`. Note `CONCURRENTLY` is pointless on a freshly seeded pool with no readers, so this only matters for an index added to a live pool.
- **pgvector adapter on pooled connections.** If the search runtime uses a `psycopg_pool.ConnectionPool`, register the vector adapter per connection via the pool's `configure=` callback — use **`register_vector`** alone, NOT 006f's `prepare_connection` (which also runs `apply_schema` DDL and must not fire on every checkout).
