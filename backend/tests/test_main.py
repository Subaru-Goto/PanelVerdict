from concurrent.futures import ThreadPoolExecutor

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from openai import APIStatusError
from pgvector.psycopg import register_vector
from pydantic import SecretStr

from app.config import Settings, settings
from app.main import (
    app,
    budget_notice,
    get_analyst,
    get_checkpointer,
    get_conn,
    get_embedder,
    get_panel_llm,
    get_remaining_credit,
    get_screener,
    get_translator,
)
from app.persistence import nearest_panelists, persist_pool
from app.schemas import EvaluateRequest
from app.screening import ScreeningVerdict
from app.vote import OutOfCredit
from tests.factories import (
    FixedEmbedder,
    ScriptedChatModel,
    StubTranslator,
    make_assembled,
    make_panel_vote,
    make_persona,
    ndjson_events,
    pointing,
    seed_japanese,
    tool_call_message,
    voted,
)

# What the endpoint should pass through as `requested`. Read from settings rather
# than written as a number, because the test environment pins the profile — the
# assertion is that the endpoint forwards the configured size, not what the size is.
_SIZE = settings.panel.size

_REQUEST_BODY = {
    "target_description": "Japanese homeowners",
    "headline_a": "Save 50% today",
    "headline_b": "Limited time: half price",
}


@pytest.fixture
def client(conn, stub_llm, monkeypatch):
    """The app with every paid or external dependency replaced: the testcontainer
    connection, a canned translator, and a stub panel model.

    The edge guard's settings are pinned to their declared defaults, not left
    to the ambient environment: `Settings` reads the repo-root `.env`, so a
    developer who has `API_SHARED_SECRET` set for their own deploy would
    otherwise watch every unauthenticated test turn 401 while CI stayed green.
    Read from the model's own defaults so the pin cannot drift from them.
    """
    for field in (
        "api_shared_secret",
        "evaluate_runs_per_day",
        "chat_turns_per_thread_per_day",
        "chat_turns_per_caller_per_day",
    ):
        monkeypatch.setattr(settings, field, Settings.model_fields[field].default)
    # Every override is a zero-argument callable, never the class itself: FastAPI
    # reads an override's signature as a dependency, so `StubTranslator` bare would
    # turn its `request: TargetRequest` parameter into the endpoint's body model.
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_translator] = lambda: StubTranslator()
    app.dependency_overrides[get_panel_llm] = lambda: stub_llm(
        chosen="option_1", reason="clear discount framing"
    )
    # No network in tests: the credit check is a live GET when not overridden.
    app.dependency_overrides[get_remaining_credit] = lambda: None
    # Answers without tools — the agent's tool mechanics are test_analyst's.
    app.dependency_overrides[get_analyst] = lambda: ScriptedChatModel(
        responses=[AIMessage(content="The interval cleared the band.")]
    )
    # A real embedding is a paid call; the canned vector keeps /chat free.
    app.dependency_overrides[get_embedder] = lambda: FixedEmbedder(pointing(0))
    # The screener is a model too. None means 'advisory checks do not run'.
    app.dependency_overrides[get_screener] = lambda: None
    # The real saver is Postgres, created by the lifespan — which TestClient
    # only runs as a context manager, and these tests don't. One in-memory
    # saver per fixture: thread durability is test_analyst's subject.
    saver = InMemorySaver()
    app.dependency_overrides[get_checkpointer] = lambda: saver
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_a_caller_without_the_shared_secret_cannot_start_a_paid_run(
    client, conn, monkeypatch
) -> None:
    """045/#143: the browser's proxy holds the secret; a caller without it gets
    401 and — the property that matters — costs nothing: neither the translator
    nor the panel model is ever invoked. CORS is a browser courtesy, so this
    refusal is the only thing standing between curl and $0.145 a run."""
    monkeypatch.setattr(settings, "api_shared_secret", SecretStr("edge-secret"))
    calls = {"translate": 0, "vote": 0}

    class CountingTranslator:
        def translate(self, request):
            calls["translate"] += 1
            return StubTranslator().translate(request)

    class CountingLLM:
        configuration = "stub"

        def vote(self, **kwargs):
            calls["vote"] += 1
            return voted()

    app.dependency_overrides[get_translator] = lambda: CountingTranslator()
    app.dependency_overrides[get_panel_llm] = lambda: CountingLLM()
    seed_japanese(conn, 5)

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 401
    assert calls == {"translate": 0, "vote": 0}


def test_the_proxy_with_the_right_secret_passes_the_gate(
    client, conn, monkeypatch
) -> None:
    """The guard is a gate, not a wall: the Next proxy's header opens it."""
    monkeypatch.setattr(settings, "api_shared_secret", SecretStr("edge-secret"))
    seed_japanese(conn, 5)

    response = client.post(
        "/evaluate", json=_REQUEST_BODY, headers={"X-API-Key": "edge-secret"}
    )

    assert response.status_code == 200


def test_chat_without_the_secret_is_refused_before_the_stream_opens(
    client, monkeypatch
) -> None:
    """A stream cannot change its status after the first byte, so the refusal
    has to come before there is a stream at all — 401, not an error event."""
    monkeypatch.setattr(settings, "api_shared_secret", SecretStr("edge-secret"))

    response = client.post(
        "/chat",
        json={
            "result": _CHAT_RESULT,
            "thread_id": "t-gate",
            "message": "why?",
        },
    )

    assert response.status_code == 401


def test_a_caller_over_the_run_limit_is_refused_before_any_model_call(
    client, conn, monkeypatch
) -> None:
    """045/#143's other half: the secret says a request came through our proxy,
    the ledger says how often this caller has asked. Runs past the window's
    limit get 429 and buy nothing — the counter lives in Postgres, so neither
    a redeploy nor a second worker forgets it."""
    monkeypatch.setattr(settings, "api_shared_secret", SecretStr("edge-secret"))
    monkeypatch.setattr(settings, "evaluate_runs_per_day", 2)
    calls = {"vote": 0}

    class CountingLLM:
        configuration = "stub"

        def vote(self, **kwargs):
            calls["vote"] += 1
            return voted()

    app.dependency_overrides[get_panel_llm] = lambda: CountingLLM()
    seed_japanese(conn, 5)
    headers = {"X-API-Key": "edge-secret", "X-Client-Id": "203.0.113.9"}

    first = client.post("/evaluate", json=_REQUEST_BODY, headers=headers)
    second = client.post("/evaluate", json=_REQUEST_BODY, headers=headers)
    votes_bought_by_honest_runs = calls["vote"]
    third = client.post("/evaluate", json=_REQUEST_BODY, headers=headers)

    assert (first.status_code, second.status_code) == (200, 200)
    assert third.status_code == 429
    assert calls["vote"] == votes_bought_by_honest_runs


def test_a_thread_over_its_turn_limit_is_refused_before_the_stream(
    client, conn, monkeypatch
) -> None:
    """The stream cannot change its status after the first byte, so the limit
    speaks in HTTP: 429, no stream, no model call. Per thread, not per caller —
    a request is not the unit of /chat's cost, a thread's turns are — and a
    fresh thread is untouched by a sibling's exhaustion."""
    monkeypatch.setattr(settings, "api_shared_secret", SecretStr("edge-secret"))
    monkeypatch.setattr(settings, "chat_turns_per_thread_per_day", 2)
    invocations = {"model": 0}

    class CountingModel(ScriptedChatModel):
        def _generate(self, messages, **kwargs):
            invocations["model"] += 1
            return super()._generate(messages, **kwargs)

    app.dependency_overrides[get_analyst] = lambda: CountingModel(
        responses=[AIMessage(content="ok")]
    )
    headers = {"X-API-Key": "edge-secret", "X-Forwarded-For": "203.0.113.9"}

    def turn(thread_id: str):
        return client.post(
            "/chat",
            json={"result": _CHAT_RESULT, "thread_id": thread_id, "message": "why?"},
            headers=headers,
        )

    first, second = turn("t-limit"), turn("t-limit")
    spent_by_honest_turns = invocations["model"]
    third = turn("t-limit")
    spent_after_refusal = invocations["model"]
    fresh_thread = turn("t-other")

    assert (first.status_code, second.status_code) == (200, 200)
    assert third.status_code == 429
    assert spent_after_refusal == spent_by_honest_turns
    assert fresh_thread.status_code == 200


def test_a_forged_forwarding_header_does_not_buy_a_fresh_budget(
    client, conn, monkeypatch
) -> None:
    """The rate-limit key must not be something the caller can choose.
    X-Forwarded-For is caller-settable — platforms append rather than replace,
    so its leftmost entry is attacker text — and keying on it let anyone mint
    unlimited budgets by varying one header. Only X-Client-Id counts, which the
    proxy overwrites from a platform value the visitor cannot set; the secret
    is what makes that header trustworthy."""
    monkeypatch.setattr(settings, "api_shared_secret", SecretStr("edge-secret"))
    monkeypatch.setattr(settings, "evaluate_runs_per_day", 1)
    seed_japanese(conn, 5)

    def run(forged: str):
        return client.post(
            "/evaluate",
            json=_REQUEST_BODY,
            headers={
                "X-API-Key": "edge-secret",
                "X-Client-Id": "198.51.100.7",
                "X-Forwarded-For": forged,
            },
        )

    first = run("203.0.113.1")
    second = run("203.0.113.2")

    assert first.status_code == 200
    assert second.status_code == 429


def test_rotating_thread_ids_does_not_escape_the_chat_limit(
    client, conn, monkeypatch
) -> None:
    """The client mints thread ids, so a per-thread count alone is a limit the
    caller can reset at will. The thread cap still bounds one runaway
    conversation; this pins the caller cap that bounds the abuser."""
    monkeypatch.setattr(settings, "api_shared_secret", SecretStr("edge-secret"))
    monkeypatch.setattr(settings, "chat_turns_per_thread_per_day", 99)
    monkeypatch.setattr(settings, "chat_turns_per_caller_per_day", 2)

    def turn(thread_id: str):
        return client.post(
            "/chat",
            json={"result": _CHAT_RESULT, "thread_id": thread_id, "message": "hi"},
            headers={"X-API-Key": "edge-secret", "X-Client-Id": "198.51.100.7"},
        )

    first, second = turn("t-a"), turn("t-b")
    third = turn("t-c")

    assert (first.status_code, second.status_code) == (200, 200)
    assert third.status_code == 429


def test_a_non_ascii_secret_header_is_a_refusal_not_a_crash(
    client, monkeypatch
) -> None:
    """Headers arrive latin-1-decoded, and `hmac.compare_digest` refuses to
    compare strings holding non-ASCII codepoints — so a byte like 0xe9 turned
    the 401 into a 500 with a traceback. Compared as bytes, a wrong key is
    just a wrong key, whatever its bytes."""
    monkeypatch.setattr(settings, "api_shared_secret", SecretStr("edge-secret"))

    # Sent as raw bytes: this byte cannot survive an ASCII encode, which is
    # exactly the shape a hostile client puts on the wire.
    response = client.post(
        "/evaluate", json=_REQUEST_BODY, headers={b"X-API-Key": b"caf\xe9"}
    )

    assert response.status_code == 401


def test_concurrent_runs_cannot_outrun_the_ledger(
    client, conn, pg_url, monkeypatch
) -> None:
    """Count-then-insert is not a limit under load: READ COMMITTED hides other
    transactions' uncommitted rows and sync handlers run in a thread pool, so
    simultaneous requests all read the same 'used' and all pass. The database
    has to arbitrate, not the application.

    Each request opens its own connection here, as in production — sharing the
    fixture's single connection would serialize the very contention under test.
    """
    monkeypatch.setattr(settings, "api_shared_secret", SecretStr("edge-secret"))
    monkeypatch.setattr(settings, "evaluate_runs_per_day", 3)
    seed_japanese(conn, 2)

    def own_connection():
        with psycopg.connect(pg_url) as connection:
            register_vector(connection)
            yield connection

    app.dependency_overrides[get_conn] = own_connection
    headers = {"X-API-Key": "edge-secret", "X-Client-Id": "198.51.100.7"}

    def run() -> int:
        return client.post("/evaluate", json=_REQUEST_BODY, headers=headers).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = [f.result() for f in [pool.submit(run) for _ in range(10)]]

    assert codes.count(200) == 3
    assert codes.count(429) == 7


def test_a_caller_cap_refusal_does_not_spend_the_threads_budget(
    client, conn, monkeypatch
) -> None:
    """Two caps, one recording step: a request the caller cap refuses must not
    have consumed a turn from the thread it named, or tripping the caller cap
    would quietly cap conversations for reasons unrelated to them."""
    monkeypatch.setattr(settings, "api_shared_secret", SecretStr("edge-secret"))
    monkeypatch.setattr(settings, "chat_turns_per_thread_per_day", 5)
    monkeypatch.setattr(settings, "chat_turns_per_caller_per_day", 1)
    headers = {"X-API-Key": "edge-secret", "X-Client-Id": "198.51.100.7"}

    def turn(thread_id: str):
        return client.post(
            "/chat",
            json={"result": _CHAT_RESULT, "thread_id": thread_id, "message": "hi"},
            headers=headers,
        )

    turn("t-first")  # spends the caller's only turn
    refused = turn("t-second")

    assert refused.status_code == 429
    # The refused thread kept all five of its turns: nothing was recorded.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM request_ledger WHERE endpoint = '/chat'"
            " AND caller = 't-second'"
        )
        row = cur.fetchone()
    assert row is not None and row[0] == 0


def test_a_cap_of_zero_is_the_local_escape_hatch(client, conn, monkeypatch) -> None:
    """Unlike the secret, the caps had no off value, so a developer iterating
    on the cheap dev profile was locked out after 25 runs with no remedy but
    hand-written SQL. Zero means unlimited."""
    monkeypatch.setattr(settings, "evaluate_runs_per_day", 0)
    seed_japanese(conn, 2)

    codes = [client.post("/evaluate", json=_REQUEST_BODY).status_code for _ in range(3)]

    assert codes == [200, 200, 200]
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM request_ledger")
        row = cur.fetchone()
    assert row is not None and row[0] == 0


def test_a_malformed_payload_does_not_spend_a_run(client, conn, monkeypatch) -> None:
    """013's rule is that a refused request costs nothing, and a payload the
    schema rejects buys no model call — so it must not spend budget either.
    Dependencies resolve before the endpoint's own body is validated, so the
    limiter has to see the parsed body itself to get this order right."""
    monkeypatch.setattr(settings, "evaluate_runs_per_day", 5)

    response = client.post("/evaluate", json={"headline_a": "only one field"})

    assert response.status_code == 422
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM request_ledger")
        row = cur.fetchone()
    assert row is not None and row[0] == 0


def test_evaluate_returns_the_full_panel_test_payload(client, conn) -> None:
    seed_japanese(conn, 5)

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 200
    body = response.json()

    # the two headlines are echoed back as identified variants
    assert body["variants"] == {
        "a": "Save 50% today",
        "b": "Limited time: half price",
    }

    # one vote per matched persona, reasons carried through for later quality review
    assert len(body["votes"]) == 5
    assert all(vote["reason"] == "clear discount framing" for vote in body["votes"])

    # each vote carries its voter as a person — demographics plus the five trait
    # levels — while the ledger's provenance (test_id, presentation_order) stays
    # off the wire
    vote = body["votes"][0]
    assert set(vote) == {"persona_id", "chosen_variant_id", "reason", "voter"}
    assert vote["voter"]["country"] == "JP"
    assert set(vote["voter"]) == {
        "country",
        "age",
        "gender",
        "education",
        "income_band",
        "traits",
    }
    assert set(vote["voter"]["traits"]) == {
        "openness",
        "conscientiousness",
        "extraversion",
        "agreeableness",
        "neuroticism",
    }

    # what the verdict is a verdict *on*: the three counts, the query the panel was
    # drawn under (coverage as data, not just the country list), and the notices
    assert body["counts"] == {"requested": _SIZE, "matched": 5, "voted": 5}
    assert body["query"]["countries"] == ["JP"]
    assert body["query"]["coverage"] == "requested"
    assert isinstance(body["notices"], list)

    # a single-chunk run at the dev size ends by exhaustion, not by decision
    assert body["stop_reason"] is None

    # the tally is descriptive; both variants are always reported
    assert body["tally"]["total"] == 5
    assert set(body["tally"]["counts"]) == {"a", "b"}
    assert "winner" not in body["tally"]

    # the verdict is the posterior plus the band's probabilities, and it carries its
    # own band — nothing in the payload names a winner.
    verdict = body["verdict"]
    assert verdict["rope"] == [0.43, 0.57]
    assert 0.0 <= verdict["share_preferring_b"] <= 1.0
    assert 0.0 <= verdict["probability_majority_prefers_b"] <= 1.0
    assert set(verdict["probability_meaningfully_preferred"]) == {"a", "b"}
    assert 0.0 <= verdict["probability_practical_tie"] <= 1.0
    assert set(verdict["expected_preference_shortfall"]) == {"shipping_a", "shipping_b"}
    assert "winner" not in verdict


def test_a_shortfall_notice_reaches_the_response(client, conn) -> None:
    seed_japanese(conn, 2)

    body = client.post("/evaluate", json=_REQUEST_BODY).json()

    assert body["counts"] == {"requested": _SIZE, "matched": 2, "voted": 2}
    assert any(
        f"Only 2 of the {_SIZE}" in notice["message"] for notice in body["notices"]
    )


def test_a_target_nobody_matches_is_the_requests_fault(client, conn) -> None:
    """422, not 502: the pool is fine and the provider was never called — the target
    named an audience this pool cannot serve."""
    persist_pool(conn, [make_assembled(make_persona(id_="US-00000", country="US"))])

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 422
    assert "no persona matches" in response.json()["detail"]


def test_a_panel_with_no_votes_is_a_bad_gateway_naming_types_only(client, conn) -> None:
    seed_japanese(conn, 3)

    class Failing:
        configuration = "stub"

        def vote(self, *, system_prompt: str, option_1: str, option_2: str):
            raise RuntimeError("api key sk-secret rejected")

    app.dependency_overrides[get_panel_llm] = Failing

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail == "0 of 3 panelists voted (RuntimeError)"
    assert "sk-secret" not in detail


def test_a_partial_run_returns_a_verdict_with_the_shortfall_in_the_counts(
    client, conn
) -> None:
    """The 5-persona all-or-nothing refusal is retired, and no
    threshold replaces it: every run with at least one vote gets a verdict, and the
    customer is informed through the counts and a notice rather than refused."""
    seed_japanese(conn, 3)

    class RefusingOne:
        configuration = "stub"

        def vote(self, *, system_prompt: str, option_1: str, option_2: str):
            if "31-year-old" in system_prompt:
                raise RuntimeError("transient")
            return voted()

    app.dependency_overrides[get_panel_llm] = RefusingOne

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["counts"] == {"requested": _SIZE, "matched": 3, "voted": 2}
    assert body["tally"]["total"] == 2
    assert any(
        "1 of the 3" in notice["message"] and "did not vote" in notice["message"]
        for notice in body["notices"]
    )


def test_exhausted_credit_is_a_402_naming_the_remedy(client, conn) -> None:
    """Not a 502: the server did nothing wrong, and 'bad gateway' sends a human to
    the wrong place. The 402 carries what to do — and no provider text."""
    seed_japanese(conn, 3)

    class Broke:
        configuration = "stub"

        def vote(self, *, system_prompt: str, option_1: str, option_2: str):
            raise OutOfCredit("OpenRouter credit exhausted (402)")

    app.dependency_overrides[get_panel_llm] = lambda: Broke()

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 402
    detail = response.json()["detail"]
    assert "Top up and re-run" in detail
    assert "not charged" in detail


class TestBudgetNotice:
    """The credit pre-flight, decided as warn-and-proceed: a run the credit cannot
    finish is still worth starting, because every vote it casts is saved and a
    re-run after top-up resumes free. So the check informs; it never refuses."""

    def test_thin_credit_warns_with_both_figures(self, monkeypatch) -> None:
        """Both the balance and the estimate travel, so a reader can see the shortfall.

        The rate is pinned to a known value rather than read from config, for two
        reasons. Writing the product in (`"$0.15"`) broke on a model change — a config
        value failing a message test. Deriving it from `USD_PER_VOTE` fixed that but
        restated the formula under test, so it could not fail if both sides were wrong
        together. A fixed rate asserts the arithmetic *and* survives a re-pricing.
        """
        monkeypatch.setattr("app.main.USD_PER_VOTE", 0.001)
        (notice,) = budget_notice(0.05, size=200)

        assert notice.severity == "warning"
        assert "$0.05" in notice.message
        assert "$0.20" in notice.message
        assert "top" in notice.message and "re-run" in notice.message

    def test_sufficient_credit_says_nothing(self) -> None:
        assert budget_notice(5.00, size=200) == ()

    def test_an_unknown_balance_never_warns(self) -> None:
        """None is an unlimited key or a failed check — a broken meter must not
        cry wolf over a run it cannot price."""
        assert budget_notice(None, size=200) == ()


def test_the_preflight_warning_reaches_the_response(client, conn, monkeypatch) -> None:
    # The rate is pinned for the same reason as the arithmetic test above: this
    # test wants "a warning reaches the wire", not a bet on config. Unpinned, it
    # silently inverted when the per-vote estimate dropped below the $0.01 stub
    # (first at the 2026-08-05 re-estimate, again at the 2026-08-23 measurement).
    monkeypatch.setattr("app.main.USD_PER_VOTE", 0.001)
    seed_japanese(conn, 3)
    app.dependency_overrides[get_remaining_credit] = lambda: 0.01

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 200
    messages = [n["message"] for n in response.json()["notices"]]
    assert any("credit" in m and "re-run" in m for m in messages)


_CHAT_RESULT = {
    "verdict": {
        "share_preferring_b": 0.288,
        "probability_majority_prefers_b": 0.001,
        "credible_interval": [0.173, 0.418],
        "credible_mass": 0.95,
        "rope": [0.43, 0.57],
        "probability_meaningfully_preferred": {"a": 0.984, "b": 0.0},
        "probability_practical_tie": 0.016,
        "detectable_gap": 0.167,
        "expected_preference_shortfall": {"shipping_a": 0.004, "shipping_b": 0.212},
    },
    "tally": {"counts": {"a": 36, "b": 14}, "total": 50},
    "counts": {"requested": 200, "matched": 200, "voted": 50},
    "query": {
        "countries": ["US"],
        "coverage": "requested",
        "min_age": 18,
        "max_age": 100,
        "gender": None,
        "income_quintiles": [],
        "education": [],
        "traits": [],
        "notices": [],
    },
    "notices": [],
    "stop_reason": "decisive",
    "variants": {"a": "Save 50% today", "b": "Members save half"},
    "votes": [],
}


def test_chat_streams_the_analysts_reply_as_ndjson(client) -> None:
    response = client.post(
        "/chat",
        json={
            "thread_id": "t-main-1",
            "message": "Why did it stop early?",
            "result": _CHAT_RESULT,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = ndjson_events(response.text.splitlines())
    tokens = [e["text"] for e in events if e["type"] == "token"]
    assert "".join(tokens) == "The interval cleared the band."
    assert events[-1] == {"type": "done"}


def test_the_chat_connection_can_bind_a_query_vector(conn, pg_url, monkeypatch) -> None:
    """Every other test replaces get_conn with the fixture connection, which
    registers the pgvector adapter — only this test exercises the real
    dependency. search_personas binds a numpy vector; a connection without the
    adapter cannot even send that query. (`conn` is here as a precondition:
    it guarantees the container already has the extension and schema.)"""
    # database_url is a derived property, so the patch lands on the class.
    monkeypatch.setattr(type(settings), "database_url", pg_url)
    dependency = get_conn()
    try:
        live = next(dependency)
        found = nearest_panelists(live, embedding=pointing(0), panel_ids=[], limit=1)
        assert found == []
    finally:
        dependency.close()


def test_the_lifespan_builds_the_postgres_checkpointer(pg_url, monkeypatch) -> None:
    """Every other test overrides get_checkpointer — only this one runs the
    real lifespan (TestClient does that as a context manager). It pins the
    wiring the deploy relies on: startup opens the pool, `setup()` migrates
    the library's checkpoint tables without error, and the saver the /chat
    dependency will hand out is the Postgres one."""
    # database_url is a derived property, so the patch lands on the class.
    monkeypatch.setattr(type(settings), "database_url", pg_url)
    with TestClient(app):
        assert isinstance(app.state.checkpointer, PostgresSaver)


def test_chat_search_tool_runs_on_the_streams_own_schedule(client, conn) -> None:
    """The stream body executes after the handler returns; this pins that the
    yield-dependency connection is still open when the tool finally runs, and
    that the whole wiring — request votes → panel scope, embedder → query
    vector — holds over HTTP, not just in-process."""
    persist_pool(
        conn,
        [
            make_assembled(make_persona(id_="US-00000"), embedding=pointing(0)),
            make_assembled(make_persona(id_="US-00001"), embedding=pointing(1)),
        ],
    )
    app.dependency_overrides[get_analyst] = lambda: ScriptedChatModel(
        responses=[
            tool_call_message(name="search_personas", args={"query": "thrifty"}),
            AIMessage(content="One panelist stands out."),
        ]
    )
    votes = [
        make_panel_vote("US-00000").model_dump(mode="json"),
        make_panel_vote("US-00001").model_dump(mode="json"),
    ]

    response = client.post(
        "/chat",
        json={
            "thread_id": "t-main-5",
            "message": "Who here is thrifty?",
            "result": {**_CHAT_RESULT, "votes": votes},
        },
    )

    assert response.status_code == 200
    events = ndjson_events(response.text.splitlines())
    assert {"type": "tool", "name": "search_personas"} in events
    tokens = [e["text"] for e in events if e["type"] == "token"]
    assert "".join(tokens) == "One panelist stands out."
    assert events[-1] == {"type": "done"}


def test_chat_refuses_a_tally_naming_other_variants(client) -> None:
    """422 before any model call: the guard runs ahead of the paid agent."""
    broken = {**_CHAT_RESULT, "tally": {"counts": {"x": 50}, "total": 50}}

    response = client.post(
        "/chat",
        json={"thread_id": "t-main-2", "message": "hi", "result": broken},
    )

    assert response.status_code == 422


def test_chat_requires_a_message_and_a_thread(client) -> None:
    empty_message = client.post(
        "/chat",
        json={"thread_id": "t-main-3", "message": "", "result": _CHAT_RESULT},
    )
    empty_thread = client.post(
        "/chat",
        json={"thread_id": "", "message": "hi", "result": _CHAT_RESULT},
    )

    assert empty_message.status_code == 422
    assert empty_thread.status_code == 422


def test_chat_exhausted_credit_is_an_in_band_error_event(client) -> None:
    """Once the stream starts the 200 is committed, so the 402's meaning
    arrives as an `error` event carrying the same fixed sentence — and none
    of the provider's own words."""

    class Broke(ScriptedChatModel):
        def _generate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: object = None,
            **kwargs: object,
        ) -> ChatResult:
            request = httpx.Request("POST", "http://openrouter.invalid")
            raise APIStatusError(
                "provider text that must not travel",
                response=httpx.Response(402, request=request),
                body=None,
            )

    app.dependency_overrides[get_analyst] = lambda: Broke(responses=[])

    response = client.post(
        "/chat",
        json={"thread_id": "t-main-4", "message": "hi", "result": _CHAT_RESULT},
    )

    assert response.status_code == 200
    events = ndjson_events(response.text.splitlines())
    assert events[-1] == {
        "type": "error",
        "message": "OpenRouter credit exhausted (402)",
    }
    assert "provider text" not in response.text


class TestInputLimits:
    """Untrusted text is bounded before it is copied 25 times.

    A headline is rendered into every panelist's prompt, so an unbounded field
    is not one oversized request but a whole run of them — and the same text
    reaches the report, the analyst's context and the vote cache key. The cap
    is what lets every later guardrail reason about a bounded input.
    """

    def _payload(self, **over: str) -> dict[str, str]:
        return {
            "target_description": "US adults",
            "headline_a": "Save 50%",
            "headline_b": "Half price",
        } | over

    def test_an_oversized_headline_is_refused(self, client) -> None:
        assert (
            client.post("/evaluate", json=self._payload(headline_a="x" * 5000))
        ).status_code == 422

    def test_an_oversized_target_is_refused(self, client) -> None:
        assert (
            client.post("/evaluate", json=self._payload(target_description="x" * 5000))
        ).status_code == 422

    def test_an_empty_headline_is_refused(self, client) -> None:
        """Blank is meaningful for the target and meaningless for a headline:
        there is nothing for a panel to prefer."""
        assert (
            client.post("/evaluate", json=self._payload(headline_a=""))
        ).status_code == 422

    def test_the_caps_are_not_tighter_than_the_product(self) -> None:
        """Asserted on the schema rather than the endpoint, because this is
        about the cap being generous enough for real copy — not about anything
        the endpoint then does with it."""
        EvaluateRequest(
            target_description="Japanese homeowners in their 40s who research "
            "carefully before buying anything expensive. " * 3,
            headline_a="Members save half price this week — ends Sunday",
            headline_b="Save 50% today",
        )


def test_every_untrusted_field_reaches_the_screener_before_the_panel(
    client, conn
) -> None:
    """The wiring, which nothing else asserts: both headlines and the target are
    screened, and screening happens before any panelist is bought."""
    seen: list[str] = []

    class Recording:
        def screen(self, text: str) -> ScreeningVerdict:
            seen.append(text)
            return ScreeningVerdict(flagged=False, reason="clean")

    seed_japanese(conn, 3)
    app.dependency_overrides[get_screener] = lambda: Recording()

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 200
    assert set(seen) == {
        _REQUEST_BODY["target_description"],
        _REQUEST_BODY["headline_a"],
        _REQUEST_BODY["headline_b"],
    }


def test_a_detected_injection_is_refused_and_costs_no_votes(client, conn) -> None:
    """The refusal, and the reason it is cheap: screening runs before the panel,
    so a blocked run buys nothing. The message names the remedy and never
    repeats what the screener said."""

    class Flagging:
        def screen(self, text: str) -> ScreeningVerdict:
            return ScreeningVerdict(flagged=True, reason="<script>alert(1)</script>")

    seed_japanese(conn, 3)
    app.dependency_overrides[get_screener] = lambda: Flagging()

    response = client.post("/evaluate", json=_REQUEST_BODY)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Rephrase" in detail
    assert "<script>" not in detail
