import numpy as np
import pandas as pd

from reverse_trade.reconstruction.risk_set import _features


def test_quote_boundary_features_are_strictly_causal() -> None:
    ts = np.arange(0, 31_001, 1_000, dtype=np.int64)
    bid = 100.0 + np.arange(len(ts), dtype=float)
    ask = bid + 1.0
    result = _features(ts, ask, bid, len(ts) - 1)
    assert result["feature_status"] == "observed"
    assert result["maximum_input_time"] < result["decision_time_utc"]
    assert result["spread_now"] == 1.0
    # A later quote cannot alter a previously computed feature row.
    later = _features(np.append(ts, 32_000), np.append(ask, 999.0), np.append(bid, 998.0), len(ts) - 1)
    for key in ("ret_5s", "ret_30s", "range_30s", "realized_vol_30s", "tick_rate_30s"):
        assert later[key] == result[key]
