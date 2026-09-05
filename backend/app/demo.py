"""The $0 demo (061/#156): a real run whose panel is replayed from a capture.

Fixed inputs walk the same graph as a paid run — screen, select, vote,
assemble — with the panel model replaced by a replay of votes captured once
from a real `prod` run. No model is called at demo time, no budget is
touched, and every number the report shows is derived from the replayed
votes by the same assembly a paid run's numbers come from.

The capture is the honest half of the bargain: the votes in a fixture are a
real model's, bought once (`python -m app.demo` reruns the purchase), so the
demo never invents a vote — a panelist whose vote failed at capture fails
again at replay, and a pool that has drifted since the capture fails loudly
rather than voting as a guess.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Literal

import psycopg
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, model_validator

from app.config import PROFILES, settings
from app.graph import build_evaluate_graph
from app.llm import OpenRouterPanelLLM
from app.roleplay import RolePlayOutcome
from app.schemas import PanelEdit, PanelVoteOutput
from app.screening import OpenRouterScreener
from app.targeting import CROSS_SECTION_NOTICE, settled_query
from app.vote import VoteResponse

# The three pairs the demo shows: two clear wins in opposite directions and a
# genuine tradeoff the panel ran to exhaustion without calling — the case a
# naive A/B tool cannot express, so the one worth showing. The tradeoff
# replaced the ticket's too-close-to-call pair after the 2026-09-01 hunt:
# same-meaning rewrites all split decisively (015's sensitivity, live), and
# only a real tradeoff divided the cross-section. Slugs name the copy, not
# the promised verdict: the verdict is whatever the captured run found.
DEMO_CASES: dict[str, dict[str, str]] = {
    "save-half": {
        "a": "Save 50% this week",
        "b": "Members save half price this week",
    },
    "free-delivery": {
        "a": "Free delivery on orders over 50",
        "b": "10% off your first order",
    },
    "built-for-teams": {
        "a": "Built for teams",
        "b": "Built for teams like yours",
    },
}

_FIXTURES = Path(__file__).parent / "data" / "demo"


class NotCaptured(Exception):
    """The captured run has no vote to replay for this ask.

    Raised inside the vote loop, where it becomes one `VoteFailure` — the
    report then says how many voted, exactly as it would for a paid run that
    lost the same votes. Its name is what `_failure_kind` shows a reader.
    """


class DemoVote(BaseModel):
    persona_id: str
    variant: Literal["a", "b"]
    reason: str
    # The order the two options were shown in, as the ledger keeps it (110/#238):
    # what the free evaluation's position-bias check reads. Optional because the
    # three committed captures predate it; the next capture fills it.
    presentation_order: list[str] | None = None


class DemoFixture(BaseModel):
    """One captured run, committed as data.

    `size` is the panel size the capture requested; `votes` can be shorter
    when the real run lost votes, and the replay reports the same shortfall.
    """

    case: str
    variants: dict[str, str]
    captured_at: str
    configuration: str
    size: int
    # The captured run's own wall-clock seconds per graph node. Stored with
    # the votes because they are unrecoverable afterwards (061, 2026-08-24) —
    # the frontend replays these, and inventing durations is forbidden.
    step_seconds: dict[str, float]
    votes: list[DemoVote]

    @property
    def model(self) -> str:
        """The model that wrote the captured reasons (075/#165).

        `_capture` writes `configuration` as the run's JSON — model, effort, the
        ask — and the demo's provenance names the model from there, never from
        today's profile. A fixture whose configuration is not that JSON (the
        tests hand-build them) is read as naming the model outright.
        """
        try:
            recorded = json.loads(self.configuration)
        except ValueError:
            return self.configuration
        if isinstance(recorded, dict) and isinstance(recorded.get("model"), str):
            return recorded["model"]
        return self.configuration

    @model_validator(mode="after")
    def _canonical(self) -> "DemoFixture":
        if self.case not in DEMO_CASES:
            raise ValueError(f"unknown demo case {self.case!r}")
        if self.variants != DEMO_CASES[self.case]:
            # A fixture captured from different text is a different demo.
            raise ValueError("variants are not this case's canonical pair")
        ids = [vote.persona_id for vote in self.votes]
        if len(set(ids)) != len(ids):
            raise ValueError("a persona voted twice")
        if not self.votes:
            raise ValueError("a fixture with no votes has nothing to replay")
        if len(self.votes) > self.size:
            raise ValueError("more votes than the capture asked for")
        return self


def load_fixture(case: str) -> DemoFixture | None:
    """The committed capture for one case, or None where none is seeded yet."""
    path = _FIXTURES / f"{case}.json"
    if not path.exists():
        return None
    return DemoFixture.model_validate(json.loads(path.read_text()))


class ReplayPanel:
    """A `PanelLLM` that answers with the captured vote for the panelist asked.

    `vote()` receives only the rendered persona prompt, so the route hands in
    `prompts` — prompt → persona id, rendered from the same pool rows `select`
    seats — and the replay resolves the panelist from what it was shown.
    """

    def __init__(self, fixture: DemoFixture, prompts: dict[str, str]) -> None:
        # The captured model's configuration, so a replayed vote fingerprints
        # as the captured question, never as the live model's.
        self.configuration = fixture.configuration
        self._variants = fixture.variants
        self._votes = {vote.persona_id: vote for vote in fixture.votes}
        self._prompts = prompts

    def vote(
        self,
        *,
        system_prompt: str,
        option_1: str,
        option_2: str,
        enacted: str = "",
    ) -> VoteResponse:
        persona_id = self._prompts.get(system_prompt)
        if persona_id is None:
            raise NotCaptured("the pool has drifted since this demo was captured")
        recorded = self._votes.get(persona_id)
        if recorded is None:
            # The capture's own shortfall: this panelist's vote failed when
            # the run was bought, and inventing one now is the fake report
            # the ticket forbids.
            raise NotCaptured(f"{persona_id} cast no vote in the captured run")
        chosen_text = self._variants[recorded.variant]
        if chosen_text == option_1:
            chosen: Literal["option_1", "option_2"] = "option_1"
        elif chosen_text == option_2:
            chosen = "option_2"
        else:
            # The options shown are not the captured pair; the captured choice
            # names neither, and answering would attach a real reason to a
            # text it was never about.
            raise NotCaptured("the headlines no longer match the captured run")
        return VoteResponse(
            output=PanelVoteOutput(chosen=chosen, reason=recorded.reason),
            usage=None,
        )


class UnreachableGenerator:
    """The demo's audience is empty, so `roleplay` returns before drafting.

    A generator is required by the graph and must not be the paid one; if this
    is ever called, the route's premise broke — fail, never draft."""

    def draft(self, *, words: str) -> "RolePlayOutcome":
        raise RuntimeError("the demo has no audience words to draft from")

    def check(self, *, instruction: str) -> "RolePlayOutcome":
        raise RuntimeError("the demo has no instruction to check")


async def _capture(case: str, out_dir: Path) -> str | None:
    """Buy one real `prod` run for a case and write it down as a fixture.

    The one paid step in the demo's life (~$0.06 per case, 064's per-run
    figure). It walks the same graph the route replays through, so what is
    captured is exactly what will be served — votes and the graph's own
    per-node seconds both, because they are unrecoverable afterwards. Returns the
    run's stop reason, so the caller can retry the tie case.
    """
    profile = PROFILES["prod"]
    key = settings.openrouter_api_key
    if key is None:
        raise SystemExit("OPENROUTER_API_KEY is not set — a capture is a paid run")
    llm = OpenRouterPanelLLM(
        api_key=key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        model=profile.model,
    )
    screener = OpenRouterScreener(
        api_key=key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        model=settings.screening_model,
    )
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        graph = build_evaluate_graph(
            conn=conn,
            llm=llm,
            screener=screener,
            generator=UnreachableGenerator(),
            checkpointer=InMemorySaver(),
        )
        # The graph clocks its own nodes (033/#134): the seconds a paid run
        # stores beside its report are the seconds this fixture keeps.
        state = await graph.ainvoke(
            {
                "query": settled_query(PanelEdit()),
                "notices": [CROSS_SECTION_NOTICE],
                "audience": "",
                "instruction": "",
                "variants": DEMO_CASES[case],
                "size": profile.size,
                "reading_accepted": True,
                # A capture buys real votes, so it wants the ledger: a crashed
                # capture must resume, not re-pay. An internal label, not an
                # account — and never "" here, which would skip the ledger and
                # make every crash a full re-buy (086/#177).
                "owner": "internal:demo-capture",
            },
            {"configurable": {"thread_id": f"demo-capture-{case}"}},
        )
    result = state["result"]
    fixture = DemoFixture(
        case=case,
        variants=DEMO_CASES[case],
        captured_at=date.today().isoformat(),
        configuration=llm.configuration,
        size=profile.size,
        step_seconds=state["step_seconds"],
        votes=sorted(
            (
                DemoVote(
                    persona_id=record.persona_id,
                    variant=record.chosen_variant_id,
                    reason=record.reason,
                    presentation_order=list(record.presentation_order),
                )
                for record in result.votes.records
            ),
            key=lambda vote: vote.persona_id,
        ),
    )
    path = out_dir / f"{case}.json"
    path.write_text(fixture.model_dump_json(indent=2) + "\n")
    verdict = result.verdict
    low, high = verdict.credible_interval
    print(
        f"{case}: stop={result.stop_reason} "
        f"share_b={verdict.share_preferring_b:.2f} "
        f"interval=({low:.2f}, {high:.2f}) "
        f"voted={len(fixture.votes)}/{profile.size} -> {path}"
    )
    return result.stop_reason


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture demo fixtures: one real prod run per case (paid)."
    )
    parser.add_argument("--case", choices=sorted(DEMO_CASES), action="append")
    parser.add_argument("--out", type=Path, default=_FIXTURES)
    args = parser.parse_args()
    # No retry flag, deliberately: within the ledger's read window a re-run of
    # the same case replays the first run's votes byte-identically (010e), so
    # "try again" cannot land a different verdict — hunting means new pairs.
    for case in args.case or sorted(DEMO_CASES):
        asyncio.run(_capture(case, args.out))


if __name__ == "__main__":
    main()
