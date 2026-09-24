import numpy as np
import pandas as pd

from scripts.phase2_event_eligibility import event_features_from_bars


def test_completed_bar_events_are_timestamped_after_the_source_bar():
    timestamps = pd.date_range("2026-01-01", periods=40, freq="min")
    close = 100 + np.arange(40, dtype=float)
    bars = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.ones(40),
        }
    )
    events = event_features_from_bars(bars)
    assert events.loc[0, "timestamp"] == timestamps[0] + pd.Timedelta(minutes=1)
    assert events.loc[20, "event_prebar_close"] == bars.loc[20, "close"]
    assert events.loc[20, "timestamp"] > bars.loc[20, "timestamp"]
