import numpy as np

from scripts.ctpi_exit_investigation import holm_adjust, sign_flip_pvalue


def test_holm_adjust_is_monotone_in_sorted_order():
    raw = [0.04, 0.001, 0.02, 0.8]
    adjusted = holm_adjust(raw)
    ordered = np.argsort(raw)
    values = np.asarray(adjusted)[ordered]
    assert np.all(np.diff(values) >= 0)
    assert all(0 <= value <= 1 for value in adjusted)


def test_sign_flip_detects_consistent_positive_lockbox_gain():
    values = np.full(40, 0.2)
    assert sign_flip_pvalue(values, permutations=4999, seed=7) < 0.01


def test_sign_flip_does_not_promote_zero_gain():
    values = np.r_[np.ones(20), -np.ones(20)]
    assert sign_flip_pvalue(values, permutations=1999, seed=8) > 0.2
