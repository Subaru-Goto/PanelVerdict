---
title: "Both endpoints that spend money are open to anyone who can reach them"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## The gap (sprint review feedback, 2026-08-03)

> *"`/evaluate` buys model calls and `/chat` streams analyst turns. Neither endpoint
> has authentication or rate limiting — any client that can reach the server can
> spend the operator's OpenRouter credit."*

Accurate. `main.py:168` and `main.py:228` both spend, and nothing between a caller
and the model asks who they are or how often they have asked before.

**Severity is bounded by one fact: nothing is deployed.** `docker-compose.yml`
carries only the `db` service, so this is a **blocker on the first deployment**
rather than a live incident. That is why it is a ticket and not a hotfix.

## What already exists, and why none of it covers this

Worth listing, because four things look like they might and each bounds a different
axis:

| control | bounds | does it stop this? |
|---|---|---|
| [013](013-guardrails-mvp.md) screening + nonce delimiters | what the text may *say* | no — volume, not content |
| [010f](010f-budget-guard.md) pre-flight credit check | **nothing** — `budget_notice` is *"warn-and-proceed, never refuse"* | no |
| `PROFILE` size caps | one run's size (25 / 100 / 200) | no — bounds a run, not the number of runs |
| the `$10` per-key cap | total loss | it is a **cap on loss, not a control** |

So the axis with nothing on it is **how many runs an unidentified caller may start.**

**And CORS is not access control.** `main.py:51` sets
`allow_origins=[settings.frontend_origin]`, which is a policy enforced by *browsers*
on behalf of other origins' scripts. `curl` ignores it completely. It is worth
naming because it is the control most likely to be mistaken for this one.

## The cost of the attack, from the measured numbers

At `prod` (200 votes) a run is **$0.145** (`USD_PER_VOTE`, first-full-scale-run.md).
The `$10` key cap is therefore **~70 runs**, and a shell loop reaches that in
minutes.

**The vote cache does not help.** It is keyed on a fingerprint over the headlines
and the persona prompt, so every request carrying new text is a full-price run. An
attacker sending random headlines gets a 0% hit rate by construction — the cache
protects the honest repeat, not the operator.

## The trap: a shared secret in a header does not work for this client

The reviewer's suggestion is a shared secret plus a per-key or per-IP limit, and the
second half is straightforwardly right. The first half **cannot be implemented as
stated**, and that is the design content of this ticket:

- The browser calls the API **directly** — `api.ts:142` and `chat.ts:32` fetch
  `${process.env.NEXT_PUBLIC_API_URL}/evaluate` and `/chat`.
- Anything `NEXT_PUBLIC_*` is compiled into the client bundle **by definition**. A
  secret shipped there is readable by every visitor, so it authenticates nobody.

Three ways out, and the choice belongs to whoever deploys:

| option | cost | what it buys |
|---|---|---|
| **Next.js route handlers proxy the API** | one route per endpoint, and the SSE stream has to be piped through | the secret stays server-side; the browser talks only to its own origin, so `frontend_origin` CORS becomes redundant rather than load-bearing |
| **real per-user auth** | a user model, sessions, and it changes [040](040-vote-cache-read-window.md)'s retention story from a window to per-user CRUD | the only option that makes rate limits meaningful per person |
| **network-level only** — no public exposure, plus a proxy limit | least code | fine for a demo, not for anything with users |

The middle option is where [040](040-vote-cache-read-window.md) already says this is
heading: *"once there is auth and a user base, an analysis becomes owned content."*
So auth is not only a guard — it is the prerequisite that ticket is waiting on.

## The `/chat` limit has to count something specific

`/evaluate` is one request, one bounded cost. `/chat` is a **stream**, so a limit
must decide what it counts:

- a request is not a unit of cost — one turn can call up to three tools before
  answering, bounded only by `recursion_limit = 2 * len(tools) + 2`
- a stream that has already started cannot be refused mid-flight (`stream_analyst`
  records that *"a stream cannot change its HTTP status after the first byte"*)

So the limit belongs **before** the first byte, and the honest unit is *turns per
thread per window*, not requests per second.

## Where it goes

**App middleware, not only a reverse proxy.** A proxy config lives outside the repo,
is not covered by the suite, and does not exist yet — nothing is deployed. FastAPI
middleware travels with the code and can be tested, which matters here because a
guard nobody can test is a guard nobody can trust. A proxy limit on top is fine as a
second layer.

**"App middleware" here means ASGI/FastAPI middleware, not LangChain's.** Considered
2026-08-03 and rejected for two structural reasons, recorded so nobody spends an
afternoon discovering them:

- **`/evaluate` has no agent to hook.** `create_agent` appears in `analyst.py` and
  nowhere else — `pipeline.py` has zero references. The vote path is
  `run_panel_test` → `collect_panel_votes` → a `ThreadPoolExecutor` of direct
  `llm.vote()` calls, so there is no agent loop and therefore no middleware surface.
  That is the endpoint this ticket exists for: **$0.145 and up to 200 model calls**,
  against a `/chat` turn bounded at 8 steps. Agent middleware would cover the cheap
  half and be structurally unable to reach the expensive one.
- **On `/chat` it runs too late to refuse.** Middleware hooks fire *inside* the agent
  (`before_model`, `wrap_model_call`, `after_model`), by which point FastAPI has
  accepted the request, `analysis_facts` has validated it, and the `StreamingResponse`
  has begun — and a stream cannot change its HTTP status after the first byte, as
  above. A rate limit must reject before any work starts, which is an HTTP-edge
  concern by construction.

Two nearby LangChain pieces are worth naming so they are not mistaken for this one:

| piece | what it actually bounds | relevant here? |
|---|---|---|
| `ModelCallLimitMiddleware` / `ToolCallLimitMiddleware` | calls **within one agent turn** | not to this ticket — but it does replace `analyst.py`'s hand-derived `recursion_limit`, which is its own ticket |
| `langchain_core.rate_limiters.InMemoryRateLimiter` | **our** request rate *to the provider*, so 429s at 25-way fan-out | no — it limits the caller, not the callers, so it protects the provider's quota rather than our credit |

## Done when

An unauthenticated caller cannot start a paid run, the limit is enforced before the
first byte of a stream, the secret is not readable in the client bundle, and a test
asserts a refused request costs nothing — the same property [013](013-guardrails-mvp.md)
established for refused *content*.
