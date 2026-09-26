import numpy as np

from scripts.ctpi_next_tracks import _f1_threshold


def test_f1_threshold_is_discovery_label_driven_and_counts_unscored_cases_as_fn():
    scores = np.array([3.0, 2.0, 1.0, np.nan])
    labels = np.array([1, 0, 1, 1])
    threshold, metrics = _f1_threshold(scores, labels, total_cases=3)
    assert threshold == 1.0
    assert metrics["discovery_signals"] == 3
    assert metrics["discovery_recall"] == 2 / 3


def test_f1_threshold_respects_tied_scores():
    scores = np.array([2.0, 2.0, 1.0])
    labels = np.array([1, 0, 0])
    threshold, metrics = _f1_threshold(scores, labels, total_cases=1)
    assert threshold == 2.0
    assert metrics["discovery_signals"] == 2

