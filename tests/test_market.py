import numpy as np
import pandas as pd
from pathlib import Path

from reverse_trade.market import (
    load_market_bars,
    add_market_features,
    align_entries,
    calculate_excursions,
    build_counterfactual_decision_panel,
    normalize_market_columns,
)
from reverse_trade.pipeline import load_trades

ROOT = Path(__file__).resolve().parents[1]


def test_market_column_normalization():
    df_mt5 = pd.DataFrame({
        "<DATE>": ["2025.09.25"],
        "<TIME>": ["19:30:00"],
        "<OPEN>": [3735.0],
        "<HIGH>": [3738.0],
        "<LOW>": [3734.0],
        "<CLOSE>": [3736.0],
        "<TICKVOL>": [120]
    })
    norm = normalize_market_columns(df_mt5)
    assert "timestamp" in norm.columns
    assert "open" in norm.columns
    assert "high" in norm.columns
    assert "low" in norm.columns
    assert "close" in norm.columns
    assert "volume" in norm.columns
    assert norm["timestamp"].iloc[0] == pd.Timestamp("2025-09-25 19:30:00")


def test_market_features_and_alignment(tmp_path):
    # Create a synthetic 1-minute bar series around the first trade
    trades, _ = load_trades(ROOT / "data" / "raw" / "trades_raw.tsv")
    first_trade = trades.iloc[0] # oldest trade: 2025-09-25 19:32:56, Buy, price ~3736.13, close: 19:42:55

    times = pd.date_range(start="2025-09-25 19:00:00", end="2025-09-25 20:00:00", freq="1min")
    np.random.seed(42)
    prices = 3736.0 + np.cumsum(np.random.randn(len(times)) * 0.5)

    mock_df = pd.DataFrame({
        "timestamp": times,
        "open": prices,
        "high": prices + 0.8,
        "low": prices - 0.8,
        "close": prices + 0.2,
        "volume": np.random.randint(50, 200, size=len(times))
    })

    csv_path = tmp_path / "mock_market.csv"
    mock_df.to_csv(csv_path, index=False)

    bars = load_market_bars(csv_path)
    assert len(bars) == len(times)

    featured = add_market_features(bars)
    assert "rsi_14" in featured.columns
    assert "ema_20" in featured.columns
    assert "atr_14" in featured.columns
    assert "bollinger_z_20" in featured.columns

    aligned = align_entries(trades.head(5), featured)
    assert "timestamp" in aligned.columns
    assert len(aligned) == 5

    excursions = calculate_excursions(trades.head(5), bars)
    assert len(excursions) == 5
    assert "mfe_price" in excursions.columns
    assert "mae_price" in excursions.columns

    panel = build_counterfactual_decision_panel(featured, trades.head(5))
    assert len(panel) == len(bars)
    assert "target_action" in panel.columns
    assert (panel["target_action"] != 0).sum() >= 1
