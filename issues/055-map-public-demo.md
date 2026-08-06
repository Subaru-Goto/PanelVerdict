---
title: "Map: PanelVerdict public demo — a stranger can use it safely"
labels: [wayfinder:map]
status: open
---

## Destination

**PanelVerdict live on a public URL that a stranger can use safely and cheaply.** An ungated
$0 demo anyone can click, Google login to spend anything, hard cost ceilings above that,
the analyst gated and rate-limited, traced in LangSmith, running as **one FastAPI service**,
and looking deliberately designed rather than unstyled.

A **fresh effort**, not a resumption of [000-map](000-map.md). That map's destination was a
demo-able v1 and it ruled LangGraph, auth and deployment out of scope. Redrawing the
destination is what brings them back — per Wayfinder, out-of-scope work returns only as a
new effort.

### The ceiling, stated so the title does not overclaim

**This is a demo anyone can safely use — not real production.** Author's direction
(2026-08-04): *"if it gets popular, we will rework for the real production."* So a
production rework is a **later fresh effort**, and this map is judged against demo scale.

That licenses choices which would be wrong at real scale, and they are choices rather than
oversights:

- **vendor lock-in is acceptable** — subject ids are provider-specific, so a later auth move
  re-identifies every user. Harmless against per-day quotas.
- **free tiers are acceptable**, including the possibility of outgrowing them.
- **the simple shape wins** where a normalised or scalable one would cost more now — the
  `tests` table ([060](060-nothing-persists-a-finished-test.md)) is the live example.
- **no multi-tenancy, no teams, no owned history.** Login bounds spend; it is not an account
  system.

A ticket arguing for a heavier design *because it will be needed at scale* is arguing past
this ceiling, and should be answered with this line rather than with the design.

## Notes

- **Domain:** synthetic-panel A/B testing for content/marketing creative. Product vision in
  `docs/project-idea.md`; cumulative findings in `docs/lessons-so-far.md`.
- **EXECUTION-CARRYING, not plan-only** (Wayfinder default overridden, as on 000-map).
  `wayfinder:task` tickets carry the build and use a `## Goal` body; decision tickets use
  `## Question`.
- **Skills to consult:** `/langgraph-fundamentals`, `/langgraph-persistence`,
  `/langgraph-human-in-the-loop`, `/langchain-middleware`, `/langchain-rag` for the
  framework work; `/research` and `/prototype` for their ticket types; `/grill-me` +
  domain modelling for decision tickets; `/tdd` for logic slices; `/code-review` before
  every PR.
- **Inherited, not owned:** tickets 045–054 stay children of 000-map. This map references
  them and adds tickets only where this destination *changes* them.

### Standing decisions (settled while naming the destination, 2026-08-04)

- **One FastAPI service.** LangGraph Platform/Server is out of scope: two backends double
  what must be deployed, secured and rate-limited, and a visitor cannot see your topology.
- **LangGraph is already here.** `langgraph` 1.2.10, `langgraph-checkpoint` 4.1.1,
  `langgraph-sdk` and `langsmith` 0.10.6 are all installed transitively via `langchain`, and
  `create_agent` already compiles a `StateGraph` (`langchain/agents/factory.py`). So the
  analyst *already runs on a graph* — the open question is where a **hand-authored** graph
  earns its place, never whether to adopt one.
- **`create_agent` is the default; hand-author only where something specific demands it.**
  **Not because the pipeline is simple** — corrected 2026-08-05, since `pipeline.py:274-300` is
  a cycle with a barrier, two conditional exits and a 25-way fan-out, which is a textbook graph
  shape and would argue the *opposite*. The reason is that **the value a graph would add here is
  already bought:** durable resume comes from the vote ledger, where `vote_fingerprint` plus
  `ON CONFLICT DO NOTHING` re-asks only what has no row — provider-independent, and it survives
  swapping persistence. A graph checkpointer would duplicate it. Add the sync-versus-async cost
  across `llm.py`'s five call sites and the risk to 010e's byte-identical replay, and the
  balance is clear. [067](067-where-is-a-hand-authored-graph-worth-it.md) holds the full
  argument and the middle path — a graph *around* the vote loop rather than through it.
- **The edge refuses, the middleware bounds.** Auth and turns-per-window are FastAPI
  dependencies returning 401/429; per-turn model-call budgets are middleware. Middleware
  runs *inside* the agent after streaming has begun, so it can never refuse a request —
  the same structural finding [045](045-paid-endpoints-have-no-auth-or-rate-limit.md)
  already recorded for rate limiting.
  **This reverses a stated direction, recorded so it does not look like an oversight.** The
  author proposed gating the analyst *with* middleware — *"for the analytic chatbot, we can
  say this is for loged in function, we can use langChain middleware to do it"* (2026-08-04).
  It cannot work: by the time middleware executes, FastAPI has accepted the request and the
  stream has begun, so no 401 is reachable. The intent — *the analyst is a logged-in
  feature* — is honoured in full by [063](063-google-login-verified-at-the-edge.md); only
  the mechanism moved.
- **Store the Clerk subject id, never the email, never a token.** The app only asks *"same
  person? how many runs used?"* — a subject id answers both, so the database holds no PII.
  OAuth tokens are the genuinely dangerous class and Clerk keeps them. Note this delegates
  rather than removes the obligation: Clerk is processor, we remain controller.
- **The global daily cap is the real backstop.** Per-account quotas only make abuse
  tedious, because Google accounts are free to create. Only a global ceiling bounds
  exposure to a number we chose.
- **LangSmith is conditional on its free tier**, so tracing must be an env flag the app runs
  fine without — never a hard dependency. Disclosed in the UI, where the disclosure also
  deters casual probing. **It is not a control:** the controls stay
  [013](013-guardrails-mvp.md)'s screener and 045's limits.
- **Restyle, do not redesign.** [000-map](000-map.md) records **twelve** rounds of
  cold-reader iteration on the report — *"six rounds of cold-reader iteration with the user"*
  on the copy ([011](011-build-report-ui.md)) and *"six more cold-reader rounds on the
  posterior chart"* ([023](023-vote-feed-voter-details.md)). The visual layer is fair game;
  the information architecture and wording are not.
- **The framework learning goal is part of the destination, not a side effect.** Author's
  direction: *"I would like to really understand langChain and langGraph … gain the skill of
  work standard."* So a ticket that reaches the product outcome while teaching nothing has
  only half-succeeded. Note this is **not** in tension with `create_agent` as the default:
  the transferable surfaces are `PostgresSaver` ([046](046-analyst-threads-die-on-restart.md)),
  middleware ([052](052-the-step-budget-is-derived-arithmetic-not-a-declared-limit.md),
  [064](064-the-cost-ceilings.md)) and LangSmith ([065](065-langsmith-behind-a-flag.md)) — none
  of which needs a hand-authored graph. If
  [067](067-where-is-a-hand-authored-graph-worth-it.md) answers *"nowhere yet"*, the learning
  goal is still met by those three, and that should be said rather than assumed.
  **The one exception is nodes and edges themselves** — `StateGraph`, `add_node`, `add_edge`,
  reducers — which `create_agent` hides completely and which no product ticket here would ever
  reach. [Author the ReAct loop by hand once](069-author-the-react-loop-by-hand-once.md) covers
  that deliberately, as a throwaway exercise rather than a refactor, so working code is never
  the price of learning.

## Decisions so far

<!-- one line per closed ticket -->

- [The cost ceilings](064-the-cost-ceilings.md) — **signed off 2026-08-04.** A **$1.00/day**
  global cap in USD and **2 runs per account per day**, public paid runs on `prod`, and an
  apology rather than an error at the ceiling. **Buys 3 accounts a day**, which is thin and is
  the first number to revisit if the demo gets traffic. Two things the ticket holds that the
  gist cannot: why this finds the *edge* of `budget_notice`'s documented "never refuse" rather
  than overruling it, and why only the global cap bounds exposure. Panel model **stays**;
  analyst spend is unmeasured, so [070](070-what-does-a-run-actually-cost.md) has it.

## Not yet specified

- **Whether Luna enacts Big Five traits.** The panel moved to `openai/gpt-5.6-luna` on
  2026-08-05 on price, and `panel-model-selection.md`'s rule is that *"the manipulation check
  decides, not assumption."* [071](071-the-panel-model-changed-without-its-gate.md) is the
  gate; what is *not* yet sharp is what to do if enactment degrades in a way that changes
  015's negative control rather than the trait effects.

- **The deploy itself, and secrets handling.** [Where can this deploy?](059-where-can-this-deploy.md)
  asks *where*; actually standing it up graduates from that answer, and **nothing in the
  current ticket set delivers the public URL the destination names** — deliberately, since
  the steps depend on the platform. This is the fog patch that must graduate before the map
  can close.
- **Does `/evaluate` become a graph?** Depends on
  [067](067-where-is-a-hand-authored-graph-worth-it.md). If it does,
  [054](054-nothing-confirms-the-panel-before-the-money-is-spent.md)'s two-endpoint
  recommendation is replaced by one `interrupt()`, and the `ThreadPoolExecutor` in
  `collect_panel_votes` has to find a home inside a node.
- **Node versus Edge runtime on the frontend.** Route handlers and middleware can run on
  either, and the choice interacts with the auth provider's middleware and with anything
  needing Node APIs. Use each where it fits (author's direction, 2026-08-04) — but *which*
  is which is not yet decided, and it is entangled with
  [059](059-where-can-this-deploy.md)'s platform answer.
- **CI/CD.** Nothing runs the suites on push today. Shape depends on the deploy target.
- **An accessibility baseline.** Contrast, focus states, keyboard reach on the dock.
  Unspecifiable until the styling approach is chosen by
  [Restyle one component both ways](058-restyle-one-component-both-ways.md), because whether
  Radix supplies keyboard behaviour or it is hand-rolled changes what the baseline even
  contains.
- **The rest of "security" beyond auth and limits.** CORS, security headers, dependency
  audit, and input validation past [013](013-guardrails-mvp.md)'s screener. Named because
  the author's brief said *"security, ratelimit so on"* and this map currently answers only
  auth and spend — this is the *"so on"*, and it is not yet sharp.
- **Retention once accounts exist.** [040](040-vote-cache-read-window.md) gave votes a
  24-hour window and 046 left thread expiry open; both said the answer changes when content
  becomes *owned*. This destination makes it owned.
- **Progress UX** ([021](021-progress-ux.md), deferred at v1) re-scoped for a public
  demo — a 200-vote run currently gives a visitor no feedback at all.
<!-- Removed: "what the demo says about itself" — the dev-vs-prod disclosure copy is owned by
     [A $0 demo page](061-a-zero-cost-demo-page.md), which already requires it decided. Fog
     excludes what is already a live ticket. -->

## Out of scope

- **Payments.** Not needed for a demo product; Stripe is the path *if* this gets traction,
  as a fresh effort rather than a deferral. Recorded so the reasoning is not re-derived.
- **Multi-tenant accounts as a product** — owned history, teams, per-user report libraries.
  Login here exists to bound spend, not to become an account system.
- **LangGraph Platform / Server, and `useStream`.** Ruled out above; the cost is two
  backends and a wire contract we no longer own. 000-map's *Not yet specified* holds the
  fuller analysis.
- **Redesigning the report's information architecture or copy** — see *Restyle, do not
  redesign*.
