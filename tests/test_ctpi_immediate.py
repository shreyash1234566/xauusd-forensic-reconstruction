import numpy as np

from scripts.ctpi_immediate_execution import same_clock_placebo_statistic


def test_same_clock_placebo_detects_consistent_positive_real_values():
    groups = [np.array([2.0, 0.8, 1.0, 1.2, 0.9]) for _ in range(30)]
    result = same_clock_placebo_statistic(
        groups, beta=1.0, mean=1.0, std=0.5, permutations=1999, seed=7,
    )
    assert result["bits_per_event"] > 0
    assert result["one_sided_random_day_pvalue"] < 0.01


def test_same_clock_placebo_rejects_consistent_negative_real_values():
    groups = [np.array([0.5, 0.8, 1.0, 1.2, 0.9]) for _ in range(30)]
    result = same_clock_placebo_statistic(
        groups, beta=1.0, mean=1.0, std=0.5, permutations=1999, seed=8,
    )
    assert result["bits_per_event"] < 0
    assert result["one_sided_random_day_pvalue"] > 0.5

