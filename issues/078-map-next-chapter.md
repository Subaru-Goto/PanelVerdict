---
title: "Map: PanelVerdict next chapter — production-deployed, requirements-complete"
labels: [wayfinder:map]
status: open
---

## Destination

**PanelVerdict deployed to production on a public URL, demonstrably satisfying the full
requirement set — an agent, LangGraph, RAG, human-in-the-loop, and production-ready
operation.** Author's direction (2026-08-21): *"now we have no must requirements, other
than use RAG, human in the loop, langGraph, agent, deployed and production ready … so we
should revise everything what we have done so far to be ready for the next chapter of this
product."*

This **redraws** [055-map-public-demo](055-map-public-demo.md)'s destination and closes
that map. 055's ceiling was *"a demo anyone can safely use — not real production"*, with
production recorded as a later fresh effort. This is that fresh effort, arriving earlier
than 055 predicted, by author direction rather than by traction.

### What "production ready" means here, so the title does not overclaim

Solo developer, demo-scale traffic. Production-ready means **operable, safe, and honest**:
deployed with CI, authenticated and rate-limited, cost-ceilinged, observable (traces +
correlated logs), durable (runs and threads survive restarts), legally compliant
(Art. 50), and tested end to end. It does **not** mean web-scale: 055's licensed
simplifications (free tiers, vendor lock-in on subject ids, the simple `tests` table
shape, no multi-tenancy) **carry forward** unless a ticket shows one of them now breaks
an actual requirement. A ticket arguing for heavier design "because production" must name
the requirement it serves.

## How each requirement is satisfied — the spine of this map

| requirement | satisfied by | state |
|---|---|---|
| **Agent** | the analyst: `create_agent` + three read-only tools, NDJSON streaming | live; improving via [026](026-analyst-speaks-machinery.md), [029](029-serve-vote-reasons-to-the-analyst.md), [041](041-which-traits-moved-the-vote.md), [046](046-analyst-threads-die-on-restart.md) |
| **LangGraph** | hand-authored evaluate graph ([076](076-author-the-evaluate-graph-around-the-vote-loop.md)); the analyst already compiles a `StateGraph` | decided in [067](067-where-is-a-hand-authored-graph-worth-it.md); build pending |
| **RAG** | **two retrieval surfaces**, author's framing 2026-08-21: (1) *structured/vector* — the panel draw and `search_personas` retrieve from the persona pool, "long-term memory"; (2) *unstructured* — the analyst explains terms, statistics, and how the verdict was calculated, grounded in the methodology docs ([079](079-the-analyst-explains-the-statistics-grounded-in-the-docs.md), **new**) | (1) live; (2) to build |
| **Human in the loop** | the panel confirmation gate: composition preview, then **accept / adjust the filter / redraw** ([076](076-author-the-evaluate-graph-around-the-vote-loop.md), [077](077-panel-preview-accept-or-redraw.md)) | decided; build pending |
| **Deployed** | [059](059-where-can-this-deploy.md) answers *where*; standing it up (Docker, CI, secrets) is fog until it does | research open |
| **Production-ready** | auth [062](062-is-clerk-the-right-auth-vendor.md)/[063](063-google-login-verified-at-the-edge.md), limits [045](045-paid-endpoints-have-no-auth-or-rate-limit.md)/[066](066-amend-045-shared-secret-contradicts-public-access.md), ceilings [064](064-the-cost-ceilings.md) (decided, unimplemented), persistence [060](060-nothing-persists-a-finished-test.md)/[046](046-analyst-threads-die-on-restart.md), observability [065](065-langsmith-behind-a-flag.md)/[047](047-nothing-correlates-a-log-line-to-its-run.md), e2e [048](048-no-test-takes-the-path-a-user-takes.md), Art. 50 [074](074-the-analyst-never-says-it-is-an-ai-system.md)/[075](075-generated-text-carries-no-machine-readable-mark.md), gates [070](070-what-does-a-run-actually-cost.md)/[071](071-the-panel-model-changed-without-its-gate.md)/[072](072-a-switched-off-screener-is-only-a-log-line.md) | open, inherited |

Beyond the table, the requirement set is deliberately loose — *"nothing specific"* — so
**no ticket should gold-plate a requirement already demonstrably met.** The analyst is an
agent; it does not also need to become a multi-agent system for the requirement's sake.

## Notes

- **Domain:** synthetic-panel A/B testing for content/marketing creative. Vision in
  `docs/project-idea.md`; findings in `docs/lessons-so-far.md`.
- **EXECUTION-CARRYING, not plan-only** (Wayfinder default overridden, as on both prior
  maps). Build tickets use `## Goal`; decision tickets use `## Question`.
- **Fully agentic, no learning mode** (author, 2026-08-21) — tickets serve the product,
  never a tutorial.
- **Skills to consult:** `/langgraph-fundamentals`, `/langgraph-persistence`,
  `/langgraph-human-in-the-loop`, `/langchain-rag` (for 079), `/tdd` for logic slices,
  `/code-review` before every PR.
- **Inherited, not owned:** all open tickets of [000-map](000-map.md) and
  [055-map-public-demo](055-map-public-demo.md) remain children of their original maps
  and are **live under this map by reference** — the requirement table and ordering
  below are the index. New tickets are created here where this destination *changes*
  something.
- **Decision history lives in the closed maps.** 000's *Decisions so far* holds the v1
  route; 055's holds the demo-hardening decisions including the graph resolution. This
  map does not restate them.
- **Standing decisions carried forward unchanged:** one FastAPI service (no LangGraph
  Server/`useStream`); the edge refuses, middleware bounds; store the subject id, never
  the email; the global daily cap is the real backstop; LangSmith conditional on its free
  tier; restyle, don't redesign the report's iterated copy.

## Suggested order (judgment, not law)

1. **Gates:** [071](071-the-panel-model-changed-without-its-gate.md) (does Luna enact
   traits at all — everything rests on this), [070](070-what-does-a-run-actually-cost.md),
   [072](072-a-switched-off-screener-is-only-a-log-line.md).
2. **Spine:** [059](059-where-can-this-deploy.md) → deploy + CI (fog graduates) →
   [062](062-is-clerk-the-right-auth-vendor.md)/[063](063-google-login-verified-at-the-edge.md) →
   [045](045-paid-endpoints-have-no-auth-or-rate-limit.md) + [064](064-the-cost-ceilings.md)
   implementation → [046](046-analyst-threads-die-on-restart.md) →
   [074](074-the-analyst-never-says-it-is-an-ai-system.md).
3. **Requirements builds:** [076](076-author-the-evaluate-graph-around-the-vote-loop.md) →
   [077](077-panel-preview-accept-or-redraw.md) + [080](080-the-evaluate-form-bounds-its-vocabulary.md);
   [079](079-the-analyst-explains-the-statistics-grounded-in-the-docs.md) in parallel.
4. **Polish:** UI ([056](056-geist-is-loaded-and-arial-renders.md)/[057](057-does-shadcn-earn-its-place.md)/[058](058-restyle-one-component-both-ways.md),
   [021](021-progress-ux.md)/[032](032-slow-run-is-visible.md),
   [049](049-a-render-error-loses-the-paid-report.md)), analyst quality
   ([026](026-analyst-speaks-machinery.md)/[029](029-serve-vote-reasons-to-the-analyst.md)/[041](041-which-traits-moved-the-vote.md)/[043](043-persona-search-embeds-the-wrong-shape.md)),
   the long tail of open v1 tickets as they earn their place.

## Decisions so far

<!-- one line per closed ticket -->

## Not yet specified

- **The deploy itself, CI shape, and secrets handling** — graduates when
  [059](059-where-can-this-deploy.md) resolves. Still the fog patch that must clear
  before this map can close.
- **The rest of "security"** beyond auth and limits: CORS, security headers, dependency
  audit — inherited from 055, still not sharp.
- **An accessibility baseline** — unspecifiable until
  [058](058-restyle-one-component-both-ways.md) chooses the styling approach.
- **Retention once accounts exist** — [040](040-vote-cache-read-window.md)'s window and
  thread expiry, re-opened by content becoming owned.
- **Whether Luna enacts Big Five traits** — [071](071-the-panel-model-changed-without-its-gate.md)
  is the gate; what to do if enactment degrades stays unsharp.
- **Art. 50(2)'s concrete baseline** — [075](075-generated-text-carries-no-machine-readable-mark.md)
  watches the Code of Practice.

## Out of scope

- **Images / VLM evaluation** — still B-era: no clean public dataset to validate against,
  and no requirement names it. Returns only with a redrawn destination.
- **The audience-research RAG corpus** ([018](018-audience-research-knowledge-base.md)) —
  stays gated on the Upworthy validation study. The RAG requirement is met twice without
  it (see the table); this corpus is a value-add for a *validated* engine.
- **The validation study itself, and fixing the same-meaning validity gap** — its own
  later map; the product ships with the measured caveat, as v1 decided.
- **Payments, multi-tenant accounts, per-user report libraries** — traction-gated, as on
  055.
- **LangGraph Server / `useStream`** — ruled out with [067](067-where-is-a-hand-authored-graph-worth-it.md);
  one FastAPI service stands.
