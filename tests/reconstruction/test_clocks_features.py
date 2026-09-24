import pandas as pd

from reverse_trade.reconstruction.clocks import ClockSpec, completed_bar_opportunities, regular_opportunities
from reverse_trade.reconstruction.features import causal_quote_window, feature_return


def _quotes() -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp_utc": pd.to_datetime([
            "2026-01-01T00:00:00Z", "2026-01-01T00:00:05Z", "2026-01-01T00:00:10Z"
        ], utc=True),
        "bid": [100.0, 101.0, 120.0],
        "ask": [101.0, 102.0, 121.0],
    })


def test_causal_window_excludes_boundary_and_future() -> None:
    boundary = pd.Timestamp("2026-01-01T00:00:10Z")
    window = causal_quote_window(_quotes(), boundary, pd.Timedelta(seconds=20))
    assert window["timestamp_utc"].max() < boundary
    assert len(window) == 2
    result = feature_return(_quotes(), boundary, pd.Timedelta(seconds=20))
    assert result.status == "observed"
    assert result.maximum_input_time < boundary


def test_regular_and_completed_bar_clocks_do_not_use_labels() -> None:
    grid = regular_opportunities(
        pd.Timestamp("2026-01-01T00:00:02Z"), pd.Timestamp("2026-01-01T00:02:02Z"),
        ClockSpec("timer", pd.Timedelta(minutes=1)),
    )
    assert list(grid) == [pd.Timestamp("2026-01-01T00:01:00Z"), pd.Timestamp("2026-01-01T00:02:00Z")]
    bars = completed_bar_opportunities(_quotes()["timestamp_utc"], pd.Timedelta(seconds=5))
    assert (bars["decision_time_utc"] >= bars["completed_bar_end_utc"]).all()
