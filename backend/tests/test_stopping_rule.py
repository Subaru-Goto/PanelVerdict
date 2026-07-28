import numpy as np

from experiments.stopping_rule import CAP, CHUNK, decision_table, simulate


class TestDecisionTable:
    def test_direction_is_coded_from_the_majority_side(self) -> None:
        """The table's only logic of its own is the 1-vs-2 direction split; the
        stop/continue decision itself comes from the production function, so
        asserting it here would be circular."""
        boundaries = np.arange(CHUNK, CAP + 1, CHUNK)
        table = decision_table(boundaries)

        assert table[100][80] == 1  # decisive, B leading
        assert table[100][20] == 2  # decisive, A leading
        assert table[100][50] == 0  # dead even at 100 continues
        assert table[200][100] == 3  # proven tie at the cap


class TestConfirmationStreak:
    """The finding that killed the confirmation count rests on this logic, so it
    gets its own check against a rigged table rather than real posteriors."""

    def _always_decisive(self) -> dict[int, np.ndarray]:
        return {
            int(n): np.ones(n + 1, dtype=np.int8)
            for n in np.arange(CHUNK, CAP + 1, CHUNK)
        }

    def test_one_confirmation_stops_at_the_first_boundary(self) -> None:
        reading = simulate(
            true_share=0.7,
            confirmations=1,
            runs=200,
            table=self._always_decisive(),
            rng=np.random.default_rng(0),
        )
        assert reading.mean_votes == CHUNK

    def test_two_confirmations_need_two_consecutive_boundaries(self) -> None:
        reading = simulate(
            true_share=0.7,
            confirmations=2,
            runs=200,
            table=self._always_decisive(),
            rng=np.random.default_rng(0),
        )
        assert reading.mean_votes == 2 * CHUNK
