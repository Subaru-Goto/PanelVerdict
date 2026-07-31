---
title: "Replace `ChatOpenAI` with `init_chat_model` — the provider-agnostic constructor"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: Subaru-Goto
status: closed
---

## Closed 2026-07-31 — delivered in PR #86, and four of five risks cost nothing to check

The swap is **behaviour-preserving by construction**, which is what made this
cheap: built with the same arguments, `init_chat_model` returns a `ChatOpenAI`
whose `model_dump()` is byte-identical to the old direct call's, and
`init_embeddings` does the same for `OpenAIEmbeddings`. Same class, same config,
therefore the same endpoint, the same `cost` field, the same wire bytes, the same
embedding space. Risks 1, 2, 4 and 5 all reduce to that one observation, so the
paid live run the Done-when scheduled became a confirmation rather than the
evidence. Risk 1 turned out to be *safe by design* rather than merely handled:
omitting the provider raises `ValueError` listing the providers it knows, so an
OpenRouter `vendor/model` id can never be silently resolved against the wrong
client.

**Risk 3 was settled for free and then pinned, because the dangerous change is
the tidy-looking one.** `configuration` — the vote cache's hash input — carries
`{model, effort, ask}` and deliberately not how the request is *carried*, so
`provider` never entered it and no paid vote was orphaned. But `provider` *is* a
constructor argument the adapter binds, and the existing test was named
`test_configuration_declares_everything_the_adapter_binds`, so a later reader
folding it in for consistency is the obvious move — and it silently re-keys the
whole `votes` ledger, because a cache miss is indistinguishable from a first ask:
the next run re-buys the panel and reports success.
`test_how_a_vote_is_carried_is_not_part_of_its_identity` now pins the key set.

**The user amended the ticket mid-flight — the provider lives in `Settings`, not
a module constant — and that amendment had a consequence the ticket hadn't
priced.** `llm.py` takes config by injection precisely so it stays import-safe
(`config.py` instantiates `settings` at module scope), so a config-owned provider
*cannot* be read where it is used: it has to be threaded. Fourteen mechanical
insertions across eight files followed, which is the measurement rather than the
complaint — `(api_key, base_url, provider, model)` is a Data Clump, and it went
to [tech-debt](tech-debt.md) rather than into this PR, whose whole defence was a
diff small enough to read against a bit-identical client.

**One claim was made, committed, and retracted.** A comment justified naming the
field `langchain_provider` on the grounds that pydantic reserves the `model_`
prefix. It does not — it guards `model_` names that shadow one of its own
attributes, and `model_provider` shadows nothing (checked under
`-W error::UserWarning`: accepted silently, no `protected_namespaces` needed). The
field is `model_provider`, which also vacates the `LANGCHAIN_*` env prefix the
framework reads its own configuration from.

**A dependency became invisible.** `langchain-openai` is now required at runtime
while no app module imports it — the initialisers resolve the provider through
LangChain's fixed `_BUILTIN_PROVIDERS` registry and import it themselves. Left
unremarked, "nothing imports this" is a plausible reason to drop it, and the app
would stay importable while every model call broke. Noted in `pyproject.toml`.

Review found no security issues and no hard standards violations; the security
pass added one fact worth keeping — `base_url` survives the registry unchanged,
so the OpenRouter key is never sent to `api.openai.com`.

The live verification also re-found [024](024-fuzzy-age-words-in-targeting.md)
and answered its open question as a side effect — written up in PR #87, not here.

## Goal

Every chat model in the backend is constructed with `ChatOpenAI` from
`langchain_openai`. Replace those with LangChain's provider-agnostic
`init_chat_model`, **holding behaviour constant** — same endpoint, same request
bytes, same cost reporting, same cached votes.

Requested 2026-07-31, ahead of the sprint review. It is a *legibility* change,
not a capability one: `init_chat_model` is the idiomatic LangChain entry point
and makes "LangChain for model/provider abstraction"
(`docs/project-idea.md:177`) true at the constructor rather than only in the
prose. Config already treats the model as data
(`config.py` — the [003](003-decide-panel-model-and-provider.md) rule that a
model id is never hardcoded); this makes the *provider* data too.

## The five construction sites

| site | what it builds | complication |
|------|----------------|--------------|
| `llm.py:311` | `PanelLLM` vote model | `reasoning_effort=`, `with_structured_output(..., include_raw=True)`, `timeout`, `max_retries` |
| `llm.py:354` | `analyst_chat_model` | **returns `ChatOpenAI` as its annotated type** |
| `llm.py:396` | `OpenRouterTargetTranslator` | `with_structured_output(TargetRequest)` |
| `llm.py:~430` | plausibility scorer | `with_structured_output(PlausibilityScore)` |
| `screening.py:112` | the screener | `with_structured_output(ScreeningVerdict)` |

`OpenAIEmbeddings` at `llm.py:413` comes too, via the parallel constructor
`init_embeddings` from `langchain.embeddings` — `init_chat_model` covers chat
models only, so the embedder needs its own swap or the module ends up
half-idiomatic. Same slash problem as the chat models:
`settings.embedding_model` is `"openai/text-embedding-3-small"`
(`config.py:75`), so the provider is passed, not inferred.

## Five things that can go wrong, in the order they bite

1. **The model id has a slash.** `settings.panel_model` is
   `"openai/gpt-5-mini"` — an *OpenRouter* id. `init_chat_model` parses
   `"provider:model"`, so the provider must be passed explicitly
   (`model_provider=`) rather than inferred from a string that contains a
   different separator. Getting this wrong is not a crash; it is a wrong model.

2. **The Responses API trap.** `llm.py:301-308` records it in full: setting
   `reasoning={"effort": ...}` silently switches LangChain to the Responses
   API, whose response carries no `token_usage` and therefore no `cost` — and
   every cost figure this project has published was measured on Chat
   Completions ([010a](010a-vote-usage-instrumentation.md)). `reasoning_effort=`
   is the form that stays put. Confirm on the wire that it still does through
   `init_chat_model`'s kwarg forwarding: the check is that a vote's metadata
   still reports `cost`, not that the call succeeds.

3. **The vote fingerprint.** `llm.py:280` builds `self.configuration` from the
   model id, the effort and the rendered scaffold — **none of it read off the
   `ChatOpenAI` object**, which should insulate the sha256 cache key from this
   swap. *Verify* that rather than assume it: a changed fingerprint orphans
   every already-paid vote in the `votes` ledger
   ([010e](010e-per-vote-cache.md)) and the next demo run pays again.

4. **The return type.** `analyst_chat_model` is annotated `-> ChatOpenAI`.
   `init_chat_model` returns `BaseChatModel`, which is what
   `analyst.py`/`main.py` already accept — so the annotation narrows for no
   reason and should widen. Check nothing downstream touches a
   `ChatOpenAI`-only attribute, tests included.

5. **The pool's embeddings are on disk, and query vectors are not.**
   `nearest_panelists` (`persistence.py:263`) compares a freshly-embedded query
   against `summary_embedding` columns written at seed time. Those two vectors
   have to come from the same model in the same space, or cosine distance
   returns confident nonsense rather than an error. Same model id via
   `init_embeddings` should mean identical vectors — confirm it, because the
   repair is a paid reseed, and the failure is silent: `search_personas` would
   keep answering, just with the wrong five people.

## Done when

`uv run pytest`, `ruff check`, `ruff format --check` all green; **one real vote**
taken outside the suite confirming `cost` is still reported and the fingerprint
still hits the cache (a cached re-run costs $0.00 — that *is* the assertion);
one `search_personas` call returning people who plausibly match the query, since
that is the only observable that catches risk 5; and `docs/project-idea.md:177`
reads true.
