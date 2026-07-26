"""Post-seed QC: does a sampled persona read as one coherent person?

A thin custom G-Eval. An injected judge LLM rates a sample of the persisted pool
and the deliverable is the aggregate pass-rate, never a per-persona gate.

Weaker than it looks, and worth knowing before trusting it: every field it judges
is now sampled from a committed table or the published norms, so coherence is
largely guaranteed by construction. Treat a high pass-rate as a smoke test. The
check that can actually fail — realized pool distributions against the priors they
were drawn from — is numpy, needs no judge, and lives in app.pool_overview.

The judge is injected as a Protocol so this is unit-testable without the network;
the concrete OpenRouter adapter lives in app.llm.
"""

from dataclasses import dataclass
from typing import Protocol

import psycopg

from app.panel import render_persona_prompt
from app.persistence import load_persona_sample
from app.schemas import Persona, PlausibilityScore

_RUBRIC = (
    "Rate on a 1-5 scale how plausibly this reads as a real, coherent individual: "
    "do the age, education, income and personality hang together as one person? "
    "5 = fully believable; 1 = incoherent or a lazy demographic stereotype. "
    "Give a brief reason."
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


def run_plausibility_qc(
    conn: psycopg.Connection, *, judge: Judge, sample_size: int
) -> PlausibilityReport:
    """Judge a random sample of the persisted pool."""
    return evaluate_sample(load_persona_sample(conn, limit=sample_size), judge=judge)


def format_report(report: PlausibilityReport) -> str:
    return (
        "=== Pool QC ===\n"
        f"Plausibility (n={report.n}): pass_rate {report.pass_rate:.2f}, "
        f"mean_rating {report.mean_rating:.2f}, {len(report.failures)} failures"
    )
