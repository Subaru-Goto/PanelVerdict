"""Plausibility QC over generated personas.

A thin custom G-Eval: an injected judge LLM rates whether a persona reads as a
plausible, coherent individual given its demographics + Big Five + interests. Runs
OFFLINE on a sample — the deliverable is the aggregate pass-rate, a health signal
on the *generation prompt* (a low rate means fix the prompt, not regenerate
individuals), never a per-persona gate. Complements the statistical audit: this
catches implausibility (mode 1), the audit catches variance collapse (mode 2).

The judge is injected as a Protocol so this is unit-testable without the network;
the concrete OpenRouter adapter lives in app.llm.
"""

from dataclasses import dataclass
from typing import Protocol

from app.panel import render_persona_prompt
from app.schemas import Persona, PlausibilityScore

_RUBRIC = (
    "Rate on a 1-5 scale how plausibly this reads as a real, coherent individual: "
    "are the interests appropriate for the age and life stage, and consistent with "
    "the stated personality? 5 = fully believable; 1 = incoherent or a lazy "
    "demographic stereotype. Give a brief reason."
)


class Judge(Protocol):
    def score(self, *, prompt: str) -> PlausibilityScore: ...


@dataclass(frozen=True)
class ScoredPersona:
    persona_id: str
    score: PlausibilityScore


@dataclass(frozen=True)
class PlausibilityReport:
    n: int
    pass_rate: float
    mean_rating: float
    failures: list[ScoredPersona]


def build_judge_prompt(persona: Persona) -> str:
    """Frame the (second-person) persona rendering the panel enacts, then the rubric."""
    return (
        "Here is a synthetic survey persona, written in the second person:\n"
        f"{render_persona_prompt(persona)}\n\n{_RUBRIC}"
    )


def score_persona(persona: Persona, *, judge: Judge) -> PlausibilityScore:
    return judge.score(prompt=build_judge_prompt(persona))


def evaluate_sample(
    personas: list[Persona], *, judge: Judge, pass_threshold: int = 4
) -> PlausibilityReport:
    """Score a sample and aggregate — the generation-health signal (not a gate)."""
    scored = [
        ScoredPersona(persona.id, score_persona(persona, judge=judge))
        for persona in personas
    ]
    if not scored:
        return PlausibilityReport(0, 0.0, 0.0, [])
    ratings = [s.score.rating for s in scored]
    failures = [s for s in scored if s.score.rating < pass_threshold]
    return PlausibilityReport(
        n=len(scored),
        pass_rate=(len(scored) - len(failures)) / len(scored),
        mean_rating=sum(ratings) / len(ratings),
        failures=failures,
    )
