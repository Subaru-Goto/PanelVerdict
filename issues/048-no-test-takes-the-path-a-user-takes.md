---
title: "No test takes the path a user takes, and the contract has three hand-written definitions"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## The gap (sprint review feedback, 2026-08-03)

> *"`test_main.py` tests `/evaluate` and `/chat` in isolation via dependency overrides.
> No test exercises the flow a real user takes: evaluate, then chat about the result.
> The contract between the two endpoints … is only verified by type agreement, not by
> an end-to-end assertion."*

Correct, and the concrete form is worth naming: every `/chat` test posts
**`_CHAT_RESULT`** (`test_main.py:268`) — a hand-written dict literal. No test has ever
fed `/chat` a body that `/evaluate` actually produced.

## The contract is defined three times, by hand

That is the real finding. One shape, three independent transcriptions, and nothing
asserts they agree:

| # | where | what it is |
|---|---|---|
| 1 | `schemas.py:482` `EvaluateResponse` | the source of truth |
| 2 | `test_main.py:268` `_CHAT_RESULT` | a dict literal maintained by hand |
| 3 | `api.ts:120` `export type EvaluateResponse` | a TypeScript type, hand-written, no codegen |

**And the frontend does not validate — it asserts.** `api.ts:162` is
`return (await res.json()) as EvaluateResponse`, an unchecked cast. So a payload that
does not match is not caught at the fetch; it survives into render and fails there.
That is precisely the crash [049](049-a-render-error-loses-the-paid-report.md) exists
to contain, and it is why these two tickets are related rather than merely adjacent.

## What drift actually escapes today

Worth being precise, because *some* drift is already caught and a ticket claiming
otherwise would overstate:

- **Caught:** a required field added to `EvaluateResponse` with no default — `/chat`
  validates `request.result` as the model, so `_CHAT_RESULT` fails validation and the
  test goes red. Cross-field drift is caught too: `analysis_facts` rejects a tally
  naming variants the votes do not, pinned by
  `test_chat_refuses_a_tally_naming_other_variants`.
- **Escapes:** a field added **with a default**. `_CHAT_RESULT` still validates, the
  suite stays green, and every test now runs against a payload no real run emits —
  while the frontend's hand-written type and the real body diverge silently.
- **Escapes:** anything about *values* rather than shape. `_CHAT_RESULT` is frozen at
  36/14 of 50; if `/evaluate` changed what it puts in `counts` or `notices`, no `/chat`
  test would notice.

## Why this is cheap

The `client` fixture (`test_main.py:57`) already overrides **every** paid dependency —
stub translator, stub panel LLM, `ScriptedChatModel`, `FixedEmbedder`, no screener,
`get_remaining_credit` returning `None`. So the test needs no new scaffolding, calls
no paid model, and costs nothing:

```python
def test_a_report_can_be_discussed(client, conn) -> None:
    report = client.post("/evaluate", json={...}).json()
    response = client.post(
        "/chat",
        json={"thread_id": "t-e2e", "message": "Why did it lean that way?",
              "result": report},
    )
    assert response.status_code == 200
    assert any(e["type"] == "token" for e in ndjson_events(response.text.splitlines()))
```

One test, one assertion that matters: **the body `/evaluate` emits is a body `/chat`
accepts.** Asserting on the analyst's words would be asserting on
`ScriptedChatModel`'s script, which proves nothing.

## What it does not cover, stated so nobody assumes it does

- Not the frontend's copy of the contract. Definition 3 stays hand-written and
  unchecked by this test.
- Not the real models — every one is a double, as the README promises for the whole
  suite.
- Not the browser path. `useAnalyst` mints the `thread_id` and sends `OPENING_REQUEST`
  on mount; this test stands in for that with a literal id and message.

## The larger fix, deferred deliberately

**Generate definition 3 from definition 1.** FastAPI already publishes an OpenAPI
schema, so the TypeScript type could be generated rather than transcribed, which
would delete a whole class of drift instead of testing for it.

Not folded in here because it adds a codegen step and a build-time dependency to the
frontend, and this ticket's value is that it costs one test function. Worth its own
ticket if the hand-written type ever drifts in practice — and [049](049-a-render-error-loses-the-paid-report.md)
is the containment for it in the meantime.

## Done when

One test posts `/evaluate`'s real response body to `/chat` and asserts the stream
produces at least one token event, so a shape change to `EvaluateResponse` breaks a
test rather than a browser.
