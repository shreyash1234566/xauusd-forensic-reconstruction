"""External-market enrichment and feature engineering.

This module aligns a trade log to an explicitly supplied reference price series,
computes reference-feed excursion summaries, and constructs a candidate
no-trade panel.  It does not establish broker-feed equivalence, execution
prices, or the source strategy's rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STANDARD_OHLC_COLUMNS = {"open", "high", "low", "close"}


def normalize_market_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize diverse broker/vendor CSV export column names to standard lowercase."""
    data = df.copy()
    # Strip angle brackets and whitespace (common in MT4/MT5 exports like <DATE>, <TIME>, <OPEN>)
    data.columns = [str(c).strip("<>").strip().lower() for c in data.columns]

    # Handle split Date and Time columns
    if "timestamp" not in data.columns:
        if "date" in data.columns and "time" in data.columns:
            data["timestamp"] = pd.to_datetime(data["date"].astype(str) + " " + data["time"].astype(str), errors="coerce")
        elif "datetime" in data.columns:
            data["timestamp"] = pd.to_datetime(data["datetime"], errors="coerce")
        elif "time" in data.columns:
            data["timestamp"] = pd.to_datetime(data["time"], errors="coerce")
        elif "date" in data.columns:
            data["timestamp"] = pd.to_datetime(data["date"], errors="coerce")

    # Handle volume / tickvol aliases
    if "volume" not in data.columns:
        if "vol" in data.columns:
            data["volume"] = data["vol"]
        elif "tickvol" in data.columns:
            data["volume"] = data["tickvol"]
        elif "tick_volume" in data.columns:
            data["volume"] = data["tick_volume"]

    return data


def load_market_bars(path: str | Path, tz_offset_hours: float = 0.0) -> pd.DataFrame:
    """Load, validate, deduplicate, and sort market bar data."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Market data file not found: {path}")

    # Read with flexible delimiter detection (tab or comma)
    try:
        bars = pd.read_csv(path, sep=None, engine="python")
    except Exception:
        bars = pd.read_csv(path)

    bars = normalize_market_columns(bars)

    if "timestamp" not in bars.columns:
        raise ValueError("Market data must contain 'timestamp' or 'date' + 'time' columns.")

    missing = STANDARD_OHLC_COLUMNS.difference(bars.columns)
    if missing:
        raise ValueError(f"Market data is missing required OHLC columns: {sorted(missing)}")

    bars["timestamp"] = pd.to_datetime(bars["timestamp"], errors="coerce")
    bars = bars.dropna(subset=["timestamp"])

    if tz_offset_hours != 0.0:
        bars["timestamp"] = bars["timestamp"] + pd.Timedelta(hours=tz_offset_hours)

    # Ensure numerical OHLC
    for col in ["open", "high", "low", "close"]:
        bars[col] = pd.to_numeric(bars[col], errors="coerce")
    bars = bars.dropna(subset=["open", "high", "low", "close"])

    if "volume" not in bars.columns:
        bars["volume"] = np.nan
    else:
        bars["volume"] = pd.to_numeric(bars["volume"], errors="coerce")

    bars = bars.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    return bars


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Compute Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def add_market_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Generate candidate multi-scale market features for signal identification."""
    data = bars.copy()
    close = data["close"]
    high = data["high"]
    low = data["low"]
    open_p = data["open"]

    # 1. Multi-horizon Returns
    for period in [1, 3, 5, 10, 15, 30, 60]:
        data[f"return_{period}"] = close.pct_change(period)

    # 2. Moving Averages & Trend
    for period in [9, 20, 50, 100, 200]:
        data[f"ema_{period}"] = close.ewm(span=period, adjust=False).mean()
        data[f"sma_{period}"] = close.rolling(period).mean()
        data[f"distance_ema_{period}"] = (close - data[f"ema_{period}"]) / data[f"ema_{period}"]

    data["ema_9_20_diff"] = data["ema_9"] - data["ema_20"]
    data["ema_20_50_diff"] = data["ema_20"] - data["ema_50"]

    # 3. Momentum Oscillators
    data["rsi_7"] = _rsi(close, 7)
    data["rsi_14"] = _rsi(close, 14)
    data["rsi_21"] = _rsi(close, 21)

    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    data["macd"] = ema_12 - ema_26
    data["macd_signal"] = data["macd"].ewm(span=9, adjust=False).mean()
    data["macd_hist"] = data["macd"] - data["macd_signal"]

    # Stochastic (14, 3)
    low_14 = low.rolling(14).min()
    high_14 = high.rolling(14).max()
    stoch_k = 100.0 * (close - low_14) / (high_14 - low_14).replace(0.0, np.nan)
    data["stochastic_k_14"] = stoch_k
    data["stochastic_d_14"] = stoch_k.rolling(3).mean()

    # 4. Volatility & Bands
    previous_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - previous_close).abs(),
        (low - previous_close).abs()
    ], axis=1).max(axis=1)
    data["atr_14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    data["atr_ratio"] = data["atr_14"] / close

    rolling_mean_20 = close.rolling(20).mean()
    rolling_sd_20 = close.rolling(20).std()
    data["bollinger_upper_20"] = rolling_mean_20 + 2.0 * rolling_sd_20
    data["bollinger_lower_20"] = rolling_mean_20 - 2.0 * rolling_sd_20
    data["bollinger_z_20"] = (close - rolling_mean_20) / rolling_sd_20.replace(0.0, np.nan)
    data["bollinger_bandwidth_20"] = (data["bollinger_upper_20"] - data["bollinger_lower_20"]) / rolling_mean_20

    # 5. Price Action / Candlestick Geometry
    full_range = (high - low).replace(0.0, np.nan)
    data["candle_body"] = close - open_p
    data["candle_body_abs"] = (close - open_p).abs()
    data["candle_body_ratio"] = data["candle_body_abs"] / full_range
    data["upper_wick_ratio"] = (high - np.maximum(open_p, close)) / full_range
    data["lower_wick_ratio"] = (np.minimum(open_p, close) - low) / full_range

    # Breakout distances (Donchian-style)
    for period in [10, 20, 50]:
        data[f"distance_high_{period}"] = close / high.rolling(period).max().shift(1) - 1.0
        data[f"distance_low_{period}"] = close / low.rolling(period).min().shift(1) - 1.0

    # 6. Session VWAP (if volume is present)
    if data["volume"].notna().any() and (data["volume"] > 0).any():
        typical = (high + low + close) / 3.0
        day = data["timestamp"].dt.date
        num = (typical * data["volume"]).groupby(day).cumsum()
        denom = data["volume"].groupby(day).cumsum().replace(0.0, np.nan)
        data["vwap_session"] = num / denom
        data["distance_vwap"] = (close - data["vwap_session"]) / data["vwap_session"]
    else:
        data["vwap_session"] = np.nan
        data["distance_vwap"] = np.nan

    return data


def align_entries(
    trades: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    tolerance: pd.Timedelta = pd.Timedelta("2min"),
) -> pd.DataFrame:
    """Backward-asof match each entry to the most recent preceding market bar."""
    left = trades.sort_values("open_time").copy()
    right = bars.sort_values("timestamp").copy()

    # Merge as-of on open_time matching preceding bar timestamp
    matched = pd.merge_asof(
        left,
        right,
        left_on="open_time",
        right_on="timestamp",
        direction="backward",
        tolerance=tolerance,
    )
    matched["market_match_lag_seconds"] = (matched["open_time"] - matched["timestamp"]).dt.total_seconds()

    # Price discrepancy check between trade observed_price and market bar close/open
    if "observed_price" in matched.columns and "close" in matched.columns:
        matched["price_diff_vs_bar_close"] = matched["observed_price"] - matched["close"]
        matched["price_diff_vs_bar_open"] = matched["observed_price"] - matched["open"]

    return matched


def calculate_excursions(trades: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Calculate reference-feed high/low excursions during reported trade intervals.

    The values are diagnostic price-path summaries only.  Without the exact
    broker bid/ask stream, exit price, and field semantics, they must not be
    interpreted as realized MFE/MAE, stop distances, or take-profit distances.
    """
    results: list[dict[str, Any]] = []
    indexed = bars.set_index("timestamp").sort_index()

    for trade in trades.itertuples(index=False):
        # Extract all bars overlapping the trade's open-to-close interval
        path = indexed.loc[trade.open_time : trade.close_time]
        if path.empty:
            results.append({
                "ticket": trade.ticket,
                "side": trade.side,
                "mfe_price": np.nan,
                "mae_price": np.nan,
                "mfe_pips": np.nan,
                "mae_pips": np.nan,
                "time_to_mfe_minutes": np.nan,
                "time_to_mae_minutes": np.nan,
                "final_pnl": trade.pnl,
                "holding_minutes": (trade.close_time - trade.open_time).total_seconds() / 60.0
            })
            continue

        entry_price = float(trade.observed_price)

        if trade.side == "Buy":
            mfe = float(path["high"].max() - entry_price)
            mae = float(entry_price - path["low"].min())
            mfe_time = path["high"].idxmax()
            mae_time = path["low"].idxmin()
        else:  # Sell
            mfe = float(entry_price - path["low"].min())
            mae = float(path["high"].max() - entry_price)
            mfe_time = path["low"].idxmin()
            mae_time = path["high"].idxmax()

        # Kept for backward-compatible table columns.  Pip convention and feed
        # equivalence are broker-specific, so downstream reports call these
        # reference-feed price-unit conversions rather than execution evidence.
        results.append({
            "ticket": trade.ticket,
            "side": trade.side,
            "observed_price": entry_price,
            "mfe_price": mfe,
            "mae_price": -mae,  # Conventionally signed negative
            "mfe_pips": mfe * 10.0,
            "mae_pips": -mae * 10.0,
            "time_to_mfe_minutes": float((mfe_time - trade.open_time).total_seconds() / 60.0),
            "time_to_mae_minutes": float((mae_time - trade.open_time).total_seconds() / 60.0),
            "final_pnl": float(trade.pnl),
            "holding_minutes": float((trade.close_time - trade.open_time).total_seconds() / 60.0),
            "bars_in_trade": len(path)
        })

    return pd.DataFrame(results)


def build_counterfactual_decision_panel(
    market_features: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    tolerance: pd.Timedelta = pd.Timedelta("2min"),
) -> pd.DataFrame:
    """Construct counterfactual state panel labeled: Buy=1, Sell=-1, NoTrade=0.

    Includes entry gap tracking and forward returns.
    """
    panel = market_features.sort_values("timestamp").copy()
    panel["target_action"] = 0
    panel["matched_ticket"] = ""
    panel["matched_side"] = "None"

    times = panel["timestamp"].to_numpy(dtype="datetime64[ns]")

    for trade in trades.sort_values("open_time").itertuples(index=False):
        target = np.datetime64(trade.open_time)
        insertion = int(np.searchsorted(times, target))
        candidates = [idx for idx in [insertion - 1, insertion] if 0 <= idx < len(panel)]
        if not candidates:
            continue
        best = min(candidates, key=lambda idx: abs(times[idx] - target))
        lag = abs(pd.Timestamp(times[best]) - trade.open_time)
        if lag <= tolerance:
            action = 1 if trade.side == "Buy" else -1
            panel.iloc[best, panel.columns.get_loc("target_action")] = action
            panel.iloc[best, panel.columns.get_loc("matched_ticket")] = str(trade.ticket)
            panel.iloc[best, panel.columns.get_loc("matched_side")] = trade.side

    # Forward returns (1, 5, 15 bars ahead) to evaluate potential profitability of non-traded bars
    for horizon in [1, 5, 15]:
        panel[f"forward_return_{horizon}"] = panel["close"].pct_change(horizon).shift(-horizon)

    return panel
