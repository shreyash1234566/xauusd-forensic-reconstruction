import numpy as np
import pandas as pd

from scripts.ctpi_exit_peak_distance import add_exact_exposure, counting_process_ll, time_rescaling


def test_exact_exposure_preserves_short_final_interval():
    frame = pd.DataFrame(
        {
            "ticket": ["a", "a", "a", "b"],
            "age_seconds": [15.0, 30.0, 34.0, 4.0],
            "event": [0, 0, 1, 1],
        }
    )
    result = add_exact_exposure(frame)
    assert result.exposure_seconds.tolist() == [15.0, 15.0, 4.0, 4.0]


def test_counting_process_likelihood_rewards_matching_rate():
    frame = pd.DataFrame({"event": [0, 1], "exposure_seconds": [10.0, 10.0]})
    plausible = counting_process_ll(frame, np.array([0.05, 0.05]))
    implausible = counting_process_ll(frame, np.array([2.0, 2.0]))
    assert plausible > implausible


def test_time_rescaling_returns_declared_fields():
    frame = pd.DataFrame(
        {
            "ticket": ["a", "b", "c", "d"],
            "exposure_seconds": [1.0, 1.0, 1.0, 1.0],
        }
    )
    result = time_rescaling(frame, np.array([0.2, 0.7, 1.4, 3.0]))
    assert result["n_trades"] == 4
    assert result["gate"] in {"PASS", "FAIL"}
    assert 0 <= result["ks_pvalue"] <= 1
