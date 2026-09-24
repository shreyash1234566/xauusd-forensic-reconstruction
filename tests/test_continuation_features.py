import numpy as np
import pandas as pd

from scripts.continue_identification import make_htf_features, make_m1_features


def sample_bars(rows: int = 30) -> pd.DataFrame:
    timestamp = pd.date_range("2026-01-01", periods=rows, freq="min")
    close = 100 + np.arange(rows, dtype=float)
    return pd.DataFrame(
        {
            "timestamp": timestamp,
            "open": close - 0.25,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.arange(rows, dtype=float) + 1,
        }
    )


def test_m1_market_values_are_shifted_one_completed_bar():
    bars = sample_bars()
    features = make_m1_features(bars)
    assert np.isnan(features.loc[0, "m1_close"])
    assert features.loc[1, "m1_close"] == bars.loc[0, "close"]
    assert features.loc[10, "m1_body"] == bars.loc[9, "close"] - bars.loc[9, "open"]


def test_higher_timeframe_bar_is_available_only_after_completion():
    bars = sample_bars()
    features = make_htf_features(bars, 5, "m5")
    assert features.loc[0, "timestamp"] == bars.loc[0, "timestamp"] + pd.Timedelta(minutes=5)
    assert features.loc[0, "m5_body_abs"] == abs(bars.loc[4, "close"] - bars.loc[0, "open"])
