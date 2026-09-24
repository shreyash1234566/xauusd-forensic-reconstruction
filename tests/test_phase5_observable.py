import pandas as pd

from scripts.phase5_observable_reconstruction import completed_features


def test_completed_features_do_not_use_current_bar_close() -> None:
    bars = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=4, freq="min"),
        "open": [10., 20., 30., 40.], "high": [11., 22., 31., 41.],
        "low": [9., 19., 29., 39.], "close": [10.5, 21.5, 30.5, 40.5], "volume": [1, 1, 1, 1],
    })
    features, _ = completed_features(bars)
    assert features.loc[2, "m1_body"] == 1.5
    assert features.loc[2, "m1_body"] != bars.loc[2, "close"] - bars.loc[2, "open"]
