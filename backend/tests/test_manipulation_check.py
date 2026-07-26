import pytest

from app.bigfive import bigfive_from_levels, bucketize
from app.panel import render_persona_prompt
from app.schemas import TraitLevel
from experiments.manipulation_check import (
    ARMS,
    PAIRS,
    TRAITS,
    collect_rows,
    render_arm,
    sweep_personas,
)


def _levels(persona) -> dict[str, TraitLevel]:
    return {trait: bucketize(score) for trait, score in persona.big_five}


class TestSweepPersonas:
    def test_one_persona_per_level_of_the_swept_trait(self):
        personas = sweep_personas("openness")
        assert [_levels(p)["openness"] for p in personas] == list(TraitLevel)

    def test_every_other_trait_is_held_at_medium(self):
        for persona in sweep_personas("extraversion"):
            others = {
                t: lv for t, lv in _levels(persona).items() if t != "extraversion"
            }
            assert set(others.values()) == {TraitLevel.MEDIUM}

    def test_demographics_are_identical_across_the_sweep(self):
        personas = sweep_personas("neuroticism")
        demographics = {
            p.model_dump(exclude={"id", "big_five"})
            == personas[0].model_dump(exclude={"id", "big_five"})
            for p in personas
        }
        assert demographics == {True}

    def test_ids_are_unique_and_name_the_cell(self):
        ids = [p.id for p in sweep_personas("agreeableness")]
        assert len(set(ids)) == len(ids)
        assert all(id_.startswith("agreeableness-") for id_ in ids)

    def test_unknown_trait_is_rejected(self):
        with pytest.raises(KeyError):
            sweep_personas("charisma")


class TestRenderArm:
    def test_demographics_arm_is_the_vote_prompt_without_temperament(self):
        persona = sweep_personas("openness")[0]
        demographics = render_arm(persona, "demographics")
        assert render_persona_prompt(persona).startswith(demographics)
        assert len(demographics) < len(render_persona_prompt(persona))

    def test_five_level_arm_is_the_production_vote_prompt(self):
        for persona in sweep_personas("openness"):
            assert render_arm(persona, "traits_5") == render_persona_prompt(persona)

    def test_three_level_arm_collapses_the_extremes_onto_their_neighbours(self):
        """The 3-level arm must differ from the 5-level one only in granularity.

        Asserted by rebuilding the same persona at the collapsed level and
        demanding the exact production rendering, so a reworded phrase table
        cannot turn a granularity ablation into a wording ablation.
        """
        collapsed = {
            TraitLevel.VERY_LOW: TraitLevel.LOW,
            TraitLevel.VERY_HIGH: TraitLevel.HIGH,
        }
        for persona in sweep_personas("conscientiousness"):
            level = _levels(persona)["conscientiousness"]
            expected = persona.model_copy(
                update={
                    "big_five": bigfive_from_levels(
                        openness=TraitLevel.MEDIUM,
                        conscientiousness=collapsed.get(level, level),
                        extraversion=TraitLevel.MEDIUM,
                        agreeableness=TraitLevel.MEDIUM,
                        neuroticism=TraitLevel.MEDIUM,
                    )
                }
            )
            assert render_arm(persona, "traits_3") == render_persona_prompt(expected)

    def test_the_two_trait_arms_agree_wherever_no_extreme_is_drawn(self):
        for persona in sweep_personas("openness"):
            if _levels(persona)["openness"] in (
                TraitLevel.VERY_LOW,
                TraitLevel.VERY_HIGH,
            ):
                assert render_arm(persona, "traits_3") != render_arm(
                    persona, "traits_5"
                )
            else:
                assert render_arm(persona, "traits_3") == render_arm(
                    persona, "traits_5"
                )


class TestPairs:
    def test_every_swept_trait_has_a_loaded_pair(self):
        assert {pair.trait for pair in PAIRS if pair.trait} == set(TRAITS)

    def test_exactly_one_positive_control(self):
        assert sum(1 for pair in PAIRS if pair.trait is None) == 1

    def test_options_are_distinct_and_ids_unique(self):
        assert len({pair.id for pair in PAIRS}) == len(PAIRS)
        assert all(pair.predicted_high != pair.predicted_low for pair in PAIRS)


class StubLLM:
    """Votes option_1 always — position-fixed, so counterbalancing is observable."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def vote(self, *, system_prompt: str, option_1: str, option_2: str):
        from app.schemas import PanelVoteOutput

        self.prompts.append(system_prompt)
        return PanelVoteOutput(chosen="option_1", reason="stub")


class TestCollectRows:
    def test_one_row_per_arm_persona_pair_replicate_and_order(self):
        llm = StubLLM()
        rows = collect_rows(llm=llm, traits=["openness"], replicates=2)
        expected = len(ARMS) * len(TraitLevel) * len(PAIRS) * 2 * 2
        assert len(rows) == expected
        assert len(llm.prompts) == expected

    def test_every_persona_sees_both_orders_in_every_cell(self):
        """Position bias must not be able to masquerade as a trait effect.

        Panel-level counterbalancing cannot deliver this: the sweep has five
        personas, so index parity would give three one order and two the other,
        with the imbalance fixed to the level.
        """
        rows = collect_rows(llm=StubLLM(), traits=["openness"], replicates=1)
        cells: dict[tuple[str, str, str, int], set[str]] = {}
        for row in rows:
            key = (row.arm, row.persona_id, row.pair_id, row.replicate)
            cells.setdefault(key, set()).add(row.order)
        assert all(
            orders == {"predicted_high", "predicted_low"} for orders in cells.values()
        )

    def test_rows_carry_the_cell_they_came_from(self):
        rows = collect_rows(llm=StubLLM(), traits=["openness"], replicates=1)
        row = rows[0]
        assert row.arm in ARMS
        assert row.trait == "openness"
        assert row.level in list(TraitLevel)
        assert row.chosen in ("predicted_high", "predicted_low")
        assert row.replicate == 0

    def test_a_position_fixed_voter_splits_evenly_because_order_alternates(self):
        """Counterbalancing is the reason a positional bias can't fake an effect."""
        rows = collect_rows(llm=StubLLM(), traits=["openness"], replicates=2)
        chosen = [row.chosen for row in rows]
        assert chosen.count("predicted_high") == chosen.count("predicted_low")

    def test_the_prompt_actually_varies_by_arm(self):
        llm = StubLLM()
        collect_rows(llm=llm, traits=["openness"], replicates=1)
        assert len(set(llm.prompts)) > len(TraitLevel)
