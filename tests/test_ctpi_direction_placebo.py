import numpy as np

from scripts.ctpi_direction_placebo import shifted_event_max_test


def test_shifted_event_max_test_detects_broad_contrarian_effect():
    rng = np.random.default_rng(4)
    directions = rng.choice((-1, 1), size=80)
    actual = np.tile(-directions[:, None], (1, 15)).astype(float)
    alternatives = [rng.choice((-1.0, 1.0), size=(20, 15)) for _ in directions]
    table, summary = shifted_event_max_test(actual, alternatives, directions, permutations=999, seed=5)
    assert summary["gate"] == "SURVIVES_SHIFTED_EVENT_PLACEBO"
    assert summary["max_stat_shifted_event_pvalue"] <= 0.01
    assert (table.loc[table.window_minutes <= 20, "contrarian_accuracy"] == 1.0).all()


def test_accuracy_names_are_not_reversed():
    directions = np.array([1, 1, -1, -1])
    actual = np.tile(np.array([1.0, -1.0, -1.0, 1.0])[:, None], (1, 15))
    alternatives = [np.tile(row, (5, 1)) for row in actual]
    table, _ = shifted_event_max_test(actual, alternatives, directions, permutations=19, seed=6)
    assert np.allclose(table.momentum_accuracy, 0.5)
    assert np.allclose(table.contrarian_accuracy, 0.5)

