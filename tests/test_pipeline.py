from pathlib import Path

import numpy as np
import pandas as pd

from reverse_trade.pipeline import direction_analysis, load_trades
from reverse_trade.statistics import benjamini_hochberg, longest_streak, runs_test


ROOT = Path(__file__).resolve().parents[1]


def test_source_shape_and_known_counts():
    trades, quality = load_trades(ROOT / "data" / "raw" / "trades_raw.tsv")
    assert len(trades) == 423
    assert quality["columns"] == 8
    assert quality["empty_cells"] == 0
    assert quality["duplicate_ticket_values"] == 0
    assert quality["leading_zero_ticket_count"] == 1
    assert trades["side"].value_counts().to_dict() == {"Buy": 214, "Sell": 209}
    assert trades["lot_size"].value_counts().sort_index().to_dict() == {0.01: 401, 0.02: 21, 0.03: 1}
    assert np.isclose(trades["pnl"].sum(), 1451.22)


def test_transition_counts_match_independent_control():
    trades, _ = load_trades(ROOT / "data" / "raw" / "trades_raw.tsv")
    _, transitions, _ = direction_analysis(trades)
    expected = pd.DataFrame([[105, 108], [108, 101]], index=["Buy", "Sell"], columns=["Buy", "Sell"])
    pd.testing.assert_frame_equal(transitions, expected)


def test_statistical_helpers():
    assert longest_streak([True, True, False, True], True) == 2
    assert runs_test([1, 0, 1, 0])["runs"] == 4
    adjusted = benjamini_hochberg([0.01, 0.04, 0.03])
    assert all(0 <= value <= 1 for value in adjusted)
    assert np.allclose(adjusted, [0.03, 0.04, 0.04])

