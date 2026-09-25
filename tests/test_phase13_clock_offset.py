import numpy as np
import pandas as pd

from scripts.phase13_clock_offset_analysis import (
    clock_design,
    conditional_log_likelihood,
    fit_single_feature,
    holm_adjust,
)


def test_clock_design_is_deterministic_and_periodic():
    x1, names = clock_design([5, 23], [30, 45], [0, 4])
    x2, names2 = clock_design([5, 23], [30, 45], [0, 4])
    assert names == names2
    assert x1.shape == (2, 18)
    assert np.allclose(x1, x2)


def test_conditional_likelihood_uses_offset():
    frame = pd.DataFrame({"group": [0, 0, 1, 1], "y": [1, 0, 0, 1]})
    offset = np.array([2.0, 0.0, 0.0, 2.0])
    value, parts = conditional_log_likelihood(frame, offset, 0.0, np.zeros(4))
    assert len(parts) == 2
    assert value > -0.3


def test_feature_fit_does_not_need_case_specific_parameters():
    frame = pd.DataFrame({"group": [0, 0, 1, 1, 2, 2], "y": [1, 0, 1, 0, 1, 0]})
    offset = np.zeros(6)
    z = np.array([1.0, -1.0, 1.5, -1.5, 2.0, -2.0])
    beta = fit_single_feature(frame, offset, z)
    assert beta > 0


def test_holm_adjustment_is_monotone_in_sorted_order():
    raw = [0.01, 0.04, 0.02]
    adjusted = holm_adjust(raw)
    assert all(a >= p for a, p in zip(adjusted, raw))
    ordered = [adjusted[i] for i in np.argsort(raw)]
    assert ordered == sorted(ordered)
