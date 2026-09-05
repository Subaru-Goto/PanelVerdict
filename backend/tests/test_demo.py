"""The $0 demo (061/#156): fixed inputs through the real graph, votes replayed.

What is pinned here is the property the ticket is named for: unlimited people
can read a real report and the meter never moves. The demo route is deliberately
outside the edge guard and the budgets — a spent allowance must never take the
sample away — and every number it shows is derived from the replayed votes by
the same assembly a paid run uses.
"""

from datetime import datetime
from pathlib import Path

import pytest

import app.main as main
from app.demo import DEMO_CASES, DemoFixture, DemoVote, NotCaptured, ReplayPanel
from app.schemas import Persona
from tests.factories import make_persona, seed_japanese


def _fixture(
    case: str = "free-delivery", votes: list[DemoVote] | None = None
) -> DemoFixture:
    return DemoFixture(
        case=case,
        variants=DEMO_CASES[case],
        captured_at="2026-08-31",
        configuration="captured-model",
        size=5,
        step_seconds={"select": 0.4, "vote": 9.2, "assemble": 0.1},
        votes=votes
        if votes is not None
        else [
            DemoVote(
                persona_id=f"JP-{i:05d}",
                variant="a" if i < 3 else "b",
                reason=f"reason {i}",
            )
            for i in range(5)
        ],
    )


def _served(monkeypatch, fixture: DemoFixture | None) -> None:
    """Serve one fixture from memory: the disk directory is deployment data."""
    monkeypatch.setattr(main, "load_fixture", lambda case: fixture)


class TestTheDemoEndpoint:
    def test_serves_a_complete_report_with_no_credentials_and_no_spend(
        self, client, conn, monkeypatch
    ) -> None:
        """One GET, no key, no account — and afterwards every ledger is as
        empty as before, because the whole point of the demo is that reading
        it buys nothing."""
        seed_japanese(conn, 5)
        _served(monkeypatch, _fixture())

        response = client.get("/demo/free-delivery")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "complete"
        # The captured run's own seconds ride along, under the same key a
        # live report keeps its clock (033/#134): the frontend replays them,
        # and inventing durations is forbidden (061, 2026-08-24). The replay
        # itself took milliseconds, and those never reach the reader.
        assert body["timings"]["step_seconds"] == {
            "select": 0.4,
            "vote": 9.2,
            "assemble": 0.1,
        }
        assert "step_seconds" not in body
        # 075/#165: a replayed run's provenance is the capture's, not today's —
        # the model that wrote these reasons and the day it did, both read off
        # the fixture served above, never off the live profile or the clock.
        provenance = body["provenance"]
        assert provenance["generated_by"] == "captured-model"
        assert datetime.fromisoformat(provenance["recorded_at"]) == datetime(
            2026, 8, 31
        )
        assert provenance["text_marking"] == "none"
        # The honesty line names the day the run was bought.
        assert body["captured_at"] == "2026-08-31"
        # The report's numbers come from the replayed votes, not a literal.
        assert body["counts"]["voted"] == 5
        assert sorted(v["reason"] for v in body["votes"]) == sorted(
            f"reason {i}" for i in range(5)
        )
        # `votes` too (086/#177): the replay is nobody's — it must not seed a
        # resume buffer no account could ever read back.
        for table in ("request_ledger", "spend_ledger", "tests", "votes"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, (
                table
            )

    def test_stays_readable_when_the_edge_guard_is_armed(
        self, client, conn, monkeypatch
    ) -> None:
        """The states screen promises the sample stays free to read. The edge
        secret guards what spends; the demo spends nothing, so a caller without
        the secret still gets it."""
        from app.config import settings

        from pydantic import SecretStr

        seed_japanese(conn, 5)
        _served(monkeypatch, _fixture())
        monkeypatch.setattr(settings, "api_shared_secret", SecretStr("edge"))

        assert client.get("/demo/free-delivery").status_code == 200

    def test_an_unknown_case_is_refused_as_missing(self, client) -> None:
        assert client.get("/demo/summer-sale").status_code == 404

    def test_an_unseeded_case_says_so_rather_than_serving_nothing(
        self, client, monkeypatch
    ) -> None:
        """Before the capture runs exist there is nothing honest to serve."""
        _served(monkeypatch, None)

        response = client.get("/demo/free-delivery")

        assert response.status_code == 503
        assert "not seeded" in response.json()["detail"]

    def test_a_capture_shortfall_replays_as_the_same_shortfall(
        self, client, conn, monkeypatch
    ) -> None:
        """A panelist whose vote failed when the run was bought has no captured
        vote, and inventing one is the fake report the ticket forbids — so the
        replayed run reports the same count the real one did."""
        seed_japanese(conn, 5)
        short = [
            DemoVote(persona_id=f"JP-{i:05d}", variant="a", reason=f"reason {i}")
            for i in range(4)
        ]
        _served(monkeypatch, _fixture(votes=short))

        body = client.get("/demo/free-delivery").json()

        assert body["counts"]["voted"] == 4
        # And the notice tells the truth about why: a capture shortfall is
        # permanent, so no line may promise a re-run will recover it.
        messages = " ".join(n["message"] for n in body["notices"])
        assert "captured" in messages
        assert "transient" not in messages


def _prompt_index(personas: list[Persona]) -> dict[str, str]:
    from app.panel import render_persona_prompt

    return {render_persona_prompt(p): p.id for p in personas}


class TestReplayPanel:
    def test_answers_with_the_captured_vote_in_either_presentation_order(self) -> None:
        """The loop shuffles which headline is option 1 per panelist; the replay
        must answer relative to the order it was actually shown."""
        persona = make_persona(id_="JP-00000", country="JP", age=30)
        fixture = _fixture(
            votes=[
                DemoVote(
                    persona_id="JP-00000", variant="b", reason="the phrasing is warmer"
                )
            ]
        )
        panel = ReplayPanel(fixture, _prompt_index([persona]))
        from app.panel import render_persona_prompt

        prompt = render_persona_prompt(persona)
        a, b = fixture.variants["a"], fixture.variants["b"]

        straight = panel.vote(system_prompt=prompt, option_1=a, option_2=b)
        flipped = panel.vote(system_prompt=prompt, option_1=b, option_2=a)

        assert straight.output.chosen == "option_2"
        assert flipped.output.chosen == "option_1"
        assert straight.output.reason == "the phrasing is warmer"

    def test_a_panelist_the_capture_never_saw_is_a_loud_miss(self) -> None:
        """A drifted pool must fail as a failure, never vote as a guess."""
        fixture = _fixture(
            votes=[DemoVote(persona_id="JP-00000", variant="a", reason="r")]
        )
        panel = ReplayPanel(fixture, {})

        with pytest.raises(NotCaptured):
            panel.vote(
                system_prompt="a prompt from nobody",
                option_1=fixture.variants["a"],
                option_2=fixture.variants["b"],
            )

    def test_headline_drift_refuses_rather_than_mismapping(self) -> None:
        """If the options shown are not the captured pair, the captured choice
        names neither — answering would attach a real reason to a text it was
        never about."""
        persona = make_persona(id_="JP-00000", country="JP", age=30)
        fixture = _fixture(
            votes=[DemoVote(persona_id="JP-00000", variant="a", reason="r")]
        )
        panel = ReplayPanel(fixture, _prompt_index([persona]))
        from app.panel import render_persona_prompt

        with pytest.raises(NotCaptured):
            panel.vote(
                system_prompt=render_persona_prompt(persona),
                option_1="Some rewritten headline",
                option_2=fixture.variants["b"],
            )


class TestDemoFixture:
    def test_refuses_variants_that_are_not_the_case_s_canonical_pair(self) -> None:
        """The demo's pairs are decided on the ticket; a fixture captured from
        different text is a different demo, not this one."""
        with pytest.raises(ValueError):
            DemoFixture(
                case="free-delivery",
                variants={"a": "Edited", "b": DEMO_CASES["free-delivery"]["b"]},
                captured_at="2026-08-31",
                configuration="captured-model",
                size=5,
                step_seconds={"vote": 1.0},
                votes=[DemoVote(persona_id="JP-00000", variant="a", reason="r")],
            )

    def test_refuses_a_persona_voting_twice(self) -> None:
        with pytest.raises(ValueError):
            _fixture(
                votes=[
                    DemoVote(persona_id="JP-00000", variant="a", reason="r"),
                    DemoVote(persona_id="JP-00000", variant="b", reason="r2"),
                ]
            )


class TestCommittedFixtures:
    def test_every_committed_fixture_parses_and_names_a_real_case(self) -> None:
        """The fixtures are deployment data: a hand-edit that breaks one should
        fail here, not as a 500 on a visitor's first click."""
        from app.demo import _FIXTURES, load_fixture

        committed = sorted(_FIXTURES.glob("*.json")) if _FIXTURES.exists() else []
        for path in committed:
            fixture = load_fixture(path.stem)
            assert fixture is not None
            assert fixture.case == path.stem


class TestTheCapture:
    @pytest.mark.anyio
    async def test_writes_the_graph_s_own_clock_not_a_stopwatch_of_its_own(
        self, monkeypatch, tmp_path
    ) -> None:
        """033/#134: the run clocks itself inside the graph, so the capture
        reads that clock off the final state — one timer in the codebase, and
        the fixture's seconds are exactly what a paid run would have stored.
        Everything paid or networked is stubbed; the file written is real."""
        from types import SimpleNamespace

        import psycopg
        from pydantic import SecretStr

        from app import demo

        class Conn:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return None

        async def connect(cls, url):
            return Conn()

        clocked = {"roleplay": 0.0, "select": 0.4, "confirm": 0.0, "vote": 9.2}
        result = SimpleNamespace(
            stop_reason="decisive",
            verdict=SimpleNamespace(
                credible_interval=(0.1, 0.3), share_preferring_b=0.2
            ),
            votes=SimpleNamespace(
                records=[
                    SimpleNamespace(
                        persona_id="JP-00001", chosen_variant_id="a", reason="r"
                    )
                ]
            ),
        )

        class Graph:
            async def ainvoke(self, payload, config):
                return {"result": result, "step_seconds": clocked}

        monkeypatch.setattr(psycopg.AsyncConnection, "connect", classmethod(connect))
        monkeypatch.setattr(demo.settings, "openrouter_api_key", SecretStr("stub"))
        monkeypatch.setattr(demo, "build_evaluate_graph", lambda **deps: Graph())

        await demo._capture("free-delivery", tmp_path)

        written = DemoFixture.model_validate_json(
            (tmp_path / "free-delivery.json").read_text()
        )
        assert written.step_seconds == clocked


def test_a_committed_capture_names_the_model_that_wrote_it() -> None:
    """`_capture` writes `configuration` as the run's JSON; the demo's provenance
    reads the model out of it (075/#165). Pinned on the committed capture rather
    than a stub, so a capture written in some other shape is caught here and not
    as a wrong name on the public demo."""
    fixture = DemoFixture.model_validate_json(
        Path("app/data/demo/free-delivery.json").read_text()
    )

    assert fixture.model == "openai/gpt-5.6-luna"
    # And the tests' hand-built shape reads as the model outright.
    assert _fixture().model == "captured-model"
