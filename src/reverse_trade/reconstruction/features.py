"""Causal tick features and explicit unknown support states."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FeatureValue:
    value: float | None
    status: str
    maximum_input_time: pd.Timestamp | None


def causal_quote_window(quotes: pd.DataFrame, decision_time: pd.Timestamp, lookback: pd.Timedelta) -> pd.DataFrame:
    """Return only rows with timestamp strictly before the decision boundary."""

    if not {"timestamp_utc", "bid", "ask"}.issubset(quotes.columns):
        raise ValueError("quotes require timestamp_utc, bid, and ask")
    boundary = pd.Timestamp(decision_time)
    boundary = boundary.tz_localize("UTC") if boundary.tzinfo is None else boundary.tz_convert("UTC")
    timestamps = pd.to_datetime(quotes["timestamp_utc"], utc=True)
    result = quotes.loc[(timestamps >= boundary - lookback) & (timestamps < boundary)].copy()
    return result.sort_values("timestamp_utc", kind="mergesort").reset_index(drop=True)


def feature_return(quotes: pd.DataFrame, decision_time: pd.Timestamp, lookback: pd.Timedelta) -> FeatureValue:
    window = causal_quote_window(quotes, decision_time, lookback)
    if len(window) < 2:
        return FeatureValue(None, "unknown_insufficient_quotes", None)
    boundary = pd.Timestamp(decision_time)
    boundary = boundary.tz_localize("UTC") if boundary.tzinfo is None else boundary.tz_convert("UTC")
    stamps = pd.to_datetime(window["timestamp_utc"], utc=True)
    if stamps.iloc[0] > boundary - lookback + pd.Timedelta(seconds=1):
        return FeatureValue(None, "unknown_incomplete_lookback", None)
    if stamps.iloc[-1] < boundary - pd.Timedelta(seconds=1):
        return FeatureValue(None, "unknown_stale_last_quote", None)
    mid = (window["bid"].to_numpy(dtype=float) + window["ask"].to_numpy(dtype=float)) / 2.0
    if mid[0] <= 0 or not np.isfinite(mid).all():
        return FeatureValue(None, "unknown_invalid_quote", None)
    maximum = pd.to_datetime(window["timestamp_utc"].iloc[-1], utc=True)
    return FeatureValue(float(mid[-1] / mid[0] - 1.0), "observed", maximum)


def feature_tick_rate(quotes: pd.DataFrame, decision_time: pd.Timestamp, lookback: pd.Timedelta) -> FeatureValue:
    window = causal_quote_window(quotes, decision_time, lookback)
    if window.empty:
        return FeatureValue(None, "unknown_insufficient_quotes", None)
    boundary = pd.Timestamp(decision_time)
    boundary = boundary.tz_localize("UTC") if boundary.tzinfo is None else boundary.tz_convert("UTC")
    stamps = pd.to_datetime(window["timestamp_utc"], utc=True)
    if stamps.iloc[0] > boundary - lookback + pd.Timedelta(seconds=1):
        return FeatureValue(None, "unknown_incomplete_lookback", None)
    if stamps.iloc[-1] < boundary - pd.Timedelta(seconds=1):
        return FeatureValue(None, "unknown_stale_last_quote", None)
    maximum = pd.to_datetime(window["timestamp_utc"].iloc[-1], utc=True)
    return FeatureValue(float(len(window) / lookback.total_seconds()), "observed", maximum)


def feature_spread(quotes: pd.DataFrame, decision_time: pd.Timestamp, lookback: pd.Timedelta) -> FeatureValue:
    window = causal_quote_window(quotes, decision_time, lookback)
    if window.empty:
        return FeatureValue(None, "unknown_insufficient_quotes", None)
    last = window.iloc[-1]
    boundary = pd.Timestamp(decision_time)
    boundary = boundary.tz_localize("UTC") if boundary.tzinfo is None else boundary.tz_convert("UTC")
    if boundary - pd.Timestamp(last.timestamp_utc) > pd.Timedelta(seconds=1):
        return FeatureValue(None, "unknown_stale_last_quote", None)
    value = float(last.ask) - float(last.bid)
    if value < 0 or not np.isfinite(value):
        return FeatureValue(None, "unknown_invalid_quote", None)
    return FeatureValue(value, "observed", pd.to_datetime(last.timestamp_utc, utc=True))


def build_feature_frame(quotes: pd.DataFrame, opportunities: Iterable[pd.Timestamp]) -> pd.DataFrame:
    """A compact, deterministic initial feature registry for policy search."""

    rows: list[dict[str, object]] = []
    for time in opportunities:
        ts = pd.Timestamp(time)
        ret5 = feature_return(quotes, ts, pd.Timedelta(seconds=5))
        ret30 = feature_return(quotes, ts, pd.Timedelta(seconds=30))
        rate30 = feature_tick_rate(quotes, ts, pd.Timedelta(seconds=30))
        spread = feature_spread(quotes, ts, pd.Timedelta(seconds=30))
        observed = [ret5, ret30, rate30, spread]
        rows.append({
            "decision_time_utc": ts,
            "ret5": ret5.value,
            "ret30": ret30.value,
            "tick_rate_30": rate30.value,
            "spread_now": spread.value,
            "feature_status": "observed" if all(item.status == "observed" for item in observed) else "unknown",
            "maximum_input_time": max((item.maximum_input_time for item in observed if item.maximum_input_time is not None), default=pd.NaT),
        })
    return pd.DataFrame(rows)


# Aliases for cross-module compatibility
build_causal_feature_frame = build_feature_frame
