import pandas as pd

from scripts.phase3_intrabar_state import clock_window_features


def test_clock_post_window_is_defined_from_candidate_timestamp_only():
    frame = pd.DataFrame({"timestamp": pd.to_datetime(["2026-01-01 10:30:00", "2026-01-01 10:31:00", "2026-01-01 10:33:00"])})
    result = clock_window_features(frame)
    assert result["clock_m30_boundary"].tolist() == [1, 0, 0]
    assert result["clock_m30_post120"].tolist() == [1, 1, 0]
    assert result["clock_h1_boundary"].tolist() == [0, 0, 0]


def test_clock_window_does_not_use_price_or_future_columns():
    frame = pd.DataFrame({"timestamp": pd.to_datetime(["2026-01-01 10:00:00"]), "future_price": [999.0]})
    result = clock_window_features(frame)
    assert result.loc[0, "clock_m30_post120"] == 1
    assert result.loc[0, "future_price"] == 999.0
