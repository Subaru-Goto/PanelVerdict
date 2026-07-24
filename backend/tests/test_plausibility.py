from app.bigfive import bigfive_from_levels
from app.plausibility import (
    build_judge_prompt,
    evaluate_sample,
    score_persona,
)
from app.schemas import Persona, PlausibilityScore, TraitLevel


class StubJudge:
    """Judge double: returns each canned rating in turn, then repeats the last."""

    def __init__(self, *ratings: int) -> None:
        self._ratings = list(ratings)
        self.calls = 0

    def score(self, *, prompt: str) -> PlausibilityScore:
        rating = self._ratings[min(self.calls, len(self._ratings) - 1)]
        self.calls += 1
        return PlausibilityScore(rating=rating, reason="stub")


def _persona(persona_id: str, interests: list[str]) -> Persona:
    return Persona(
        id=persona_id,
        country="US",
        age=34,
        gender="female",
        income_quintile=3,
        education="tertiary",
        interests=interests,
        big_five=bigfive_from_levels(
            openness=TraitLevel.HIGH,
            conscientiousness=TraitLevel.HIGH,
            extraversion=TraitLevel.MEDIUM,
            agreeableness=TraitLevel.MEDIUM,
            neuroticism=TraitLevel.LOW,
        ),
    )


def test_build_judge_prompt_frames_persona_and_rubric() -> None:
    prompt = build_judge_prompt(_persona("p1", ["trail running", "home cooking"]))

    # the rendered persona (what the panel enacts) is embedded…
    assert "34-year-old female" in prompt
    assert "trail running" in prompt
    # …followed by the 1-5 rubric
    assert "1-5" in prompt
    assert "personality" in prompt


def test_score_persona_passes_the_judges_score_through() -> None:
    judge = StubJudge(5)
    result = score_persona(_persona("p1", ["x"]), judge=judge)

    assert result == PlausibilityScore(rating=5, reason="stub")
    assert judge.calls == 1


def test_evaluate_sample_aggregates_pass_rate_and_failures() -> None:
    personas = [_persona(f"p{i}", ["x"]) for i in range(3)]
    judge = StubJudge(5, 4, 2)  # two pass (>=4), one fails

    report = evaluate_sample(personas, judge=judge, pass_threshold=4)

    assert report.n == 3
    assert report.pass_rate == 2 / 3
    assert report.mean_rating == (5 + 4 + 2) / 3
    assert [f.persona_id for f in report.failures] == ["p2"]  # the rating-2 one
    assert report.failures[0].score.rating == 2


def test_evaluate_sample_handles_an_empty_sample() -> None:
    report = evaluate_sample([], judge=StubJudge(5))

    assert report.n == 0
    assert report.pass_rate == 0.0
    assert report.mean_rating == 0.0
    assert report.failures == []
