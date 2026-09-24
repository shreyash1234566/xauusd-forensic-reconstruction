"""Continue the existing reverse-engineering project at the replication stage.

This script deliberately reuses the preserved trade file and external M1 proxy.
All entry predictors are available before the entry minute: M1 inputs are shifted
one completed bar and higher-timeframe inputs are joined only after their bar is
complete.  Models use expanding chronological validation; no random train/test
split is used.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)

from reverse_trade.pipeline import load_trades


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"
TABLES = OUT / "tables"
SEED = 20260920
RNG = np.random.default_rng(SEED)


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if pd.isna(value):
        return None
    return value


def bh_adjust(p_values: Iterable[float]) -> np.ndarray:
    values = np.asarray(list(p_values), dtype=float)
    order = np.argsort(np.nan_to_num(values, nan=np.inf))
    adjusted = np.full(len(values), np.nan)
    ranked = values[order]
    running = 1.0
    for index in range(len(values) - 1, -1, -1):
        if np.isfinite(ranked[index]):
            running = min(running, ranked[index] * len(values) / (index + 1))
            adjusted[order[index]] = running
    return adjusted


def markdown_table(frame: pd.DataFrame, *, digits: int = 4) -> str:
    def fmt(value: Any) -> str:
        if value is None or (isinstance(value, float) and not np.isfinite(value)):
            return "n.a."
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.{digits}g}"
        return str(value).replace("|", "\\|").replace("\n", " ")

    headers = [fmt(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(fmt(value) for value in row) + " |")
    return "\n".join(lines)


def empirical_ci(values: np.ndarray, statistic, *, draws: int = 2_000) -> tuple[float, float]:
    values = np.asarray(values)
    estimates = []
    for _ in range(draws):
        sample = values[RNG.integers(0, len(values), len(values))]
        estimates.append(statistic(sample))
    return float(np.quantile(estimates, 0.025)), float(np.quantile(estimates, 0.975))


def make_m1_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Build M1 features and shift market values one complete bar."""
    source = bars.copy().sort_values("timestamp").reset_index(drop=True)
    open_ = source["open"].astype(float)
    high = source["high"].astype(float)
    low = source["low"].astype(float)
    close = source["close"].astype(float)
    volume = source["volume"].astype(float)
    range_ = high - low
    body = close - open_
    previous_close = close.shift(1)
    tr = pd.concat(
        [range_, (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    result = pd.DataFrame({"timestamp": source["timestamp"]})
    current: dict[str, pd.Series] = {
        "m1_open": open_,
        "m1_high": high,
        "m1_low": low,
        "m1_close": close,
        "m1_body": body,
        "m1_body_abs": body.abs(),
        "m1_range": range_,
        "m1_body_ratio": body.abs() / range_.replace(0, np.nan),
        "m1_upper_wick_ratio": (high - np.maximum(open_, close)) / range_.replace(0, np.nan),
        "m1_lower_wick_ratio": (np.minimum(open_, close) - low) / range_.replace(0, np.nan),
        "m1_atr14": atr,
        "m1_atr_ratio": atr / close,
        "m1_range_expansion": range_ / range_.rolling(20, min_periods=10).median(),
        "m1_range_percentile_240": range_.rolling(240, min_periods=60).rank(pct=True),
        "m1_volume": volume,
        "m1_volume_z240": (np.log1p(volume) - np.log1p(volume).rolling(240, min_periods=60).mean())
        / np.log1p(volume).rolling(240, min_periods=60).std(),
    }
    for horizon in [1, 2, 3, 5, 10, 15, 30, 60]:
        current[f"m1_return_{horizon}"] = close.pct_change(horizon)
    current["m1_velocity_3"] = (close - close.shift(3)) / atr.replace(0, np.nan)
    current["m1_velocity_5"] = (close - close.shift(5)) / atr.replace(0, np.nan)
    emas: dict[int, pd.Series] = {}
    for period in [5, 9, 20, 50, 100, 200]:
        ema = close.ewm(span=period, adjust=False).mean()
        emas[period] = ema
        current[f"m1_ema{period}_dist"] = (close - ema) / atr.replace(0, np.nan)
        current[f"m1_ema{period}_slope5"] = (ema - ema.shift(5)) / atr.replace(0, np.nan)
    current["m1_ema5_9_spread"] = (emas[5] - emas[9]) / atr.replace(0, np.nan)
    current["m1_ema9_20_spread"] = (emas[9] - emas[20]) / atr.replace(0, np.nan)
    current["m1_ema20_50_spread"] = (emas[20] - emas[50]) / atr.replace(0, np.nan)
    typical = (high + low + close) / 3
    day = source["timestamp"].dt.floor("D")
    vwap = (typical * volume).groupby(day).cumsum() / volume.groupby(day).cumsum().replace(0, np.nan)
    current["m1_vwap_dist"] = (close - vwap) / atr.replace(0, np.nan)
    for lookback in [10, 20, 50]:
        prior_high = high.rolling(lookback, min_periods=lookback).max().shift(1)
        prior_low = low.rolling(lookback, min_periods=lookback).min().shift(1)
        current[f"m1_breakout_high_{lookback}"] = (close - prior_high) / atr.replace(0, np.nan)
        current[f"m1_breakout_low_{lookback}"] = (close - prior_low) / atr.replace(0, np.nan)
    session_high_before = high.groupby(day).transform(lambda series: series.cummax().shift(1))
    session_low_before = low.groupby(day).transform(lambda series: series.cummin().shift(1))
    current["m1_session_high_dist"] = (close - session_high_before) / atr.replace(0, np.nan)
    current["m1_session_low_dist"] = (close - session_low_before) / atr.replace(0, np.nan)
    rolling_range = range_.rolling(10, min_periods=5).mean()
    current["m1_compression_expansion"] = range_ / rolling_range.shift(1).replace(0, np.nan)

    # Entry at any second inside minute t cannot safely use final OHLC for t.
    # Every market-derived M1 feature is therefore shifted one full bar.
    for name, series in current.items():
        result[name] = series.shift(1).astype("float32")
    ts = result["timestamp"]
    minutes = ts.dt.hour * 60 + ts.dt.minute
    result["hour_sin"] = np.sin(2 * np.pi * minutes / 1440).astype("float32")
    result["hour_cos"] = np.cos(2 * np.pi * minutes / 1440).astype("float32")
    result["dow_sin"] = np.sin(2 * np.pi * ts.dt.dayofweek / 7).astype("float32")
    result["dow_cos"] = np.cos(2 * np.pi * ts.dt.dayofweek / 7).astype("float32")
    result["minute_sin"] = np.sin(2 * np.pi * ts.dt.minute / 60).astype("float32")
    result["minute_cos"] = np.cos(2 * np.pi * ts.dt.minute / 60).astype("float32")
    for boundary in [5, 15, 30, 60]:
        result[f"boundary_{boundary}"] = (
            (ts.dt.minute % boundary == 0) if boundary < 60 else (ts.dt.minute == 0)
        ).astype("int8")
    return result


def make_htf_features(bars: pd.DataFrame, minutes: int, prefix: str) -> pd.DataFrame:
    indexed = bars.set_index("timestamp")
    frame = indexed.resample(f"{minutes}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(subset=["open", "high", "low", "close"])
    range_ = frame["high"] - frame["low"]
    body = frame["close"] - frame["open"]
    prev_close = frame["close"].shift(1)
    tr = pd.concat(
        [range_, (frame["high"] - prev_close).abs(), (frame["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    ema9 = frame["close"].ewm(span=9, adjust=False).mean()
    ema20 = frame["close"].ewm(span=20, adjust=False).mean()
    ema50 = frame["close"].ewm(span=50, adjust=False).mean()
    out = pd.DataFrame(index=frame.index)
    out[f"{prefix}_body_abs"] = body.abs()
    out[f"{prefix}_body_ratio"] = body.abs() / range_.replace(0, np.nan)
    out[f"{prefix}_return_1"] = frame["close"].pct_change()
    out[f"{prefix}_return_3"] = frame["close"].pct_change(3)
    out[f"{prefix}_atr_ratio"] = atr / frame["close"]
    out[f"{prefix}_range_expansion"] = range_ / range_.rolling(20, min_periods=10).median()
    out[f"{prefix}_ema9_20_spread"] = (ema9 - ema20) / atr.replace(0, np.nan)
    out[f"{prefix}_ema20_50_spread"] = (ema20 - ema50) / atr.replace(0, np.nan)
    out[f"{prefix}_ema20_slope3"] = (ema20 - ema20.shift(3)) / atr.replace(0, np.nan)
    out[f"{prefix}_price_ema20"] = (frame["close"] - ema20) / atr.replace(0, np.nan)
    out[f"{prefix}_breakout20"] = (
        frame["close"] - frame["high"].rolling(20, min_periods=20).max().shift(1)
    ) / atr.replace(0, np.nan)
    out = out.astype("float32").reset_index()
    # A bar labeled 10:00 becomes available only at 10:00 + timeframe.
    out["timestamp"] = out["timestamp"] + pd.Timedelta(minutes=minutes)
    return out


def build_event_panel(bars: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    panel = make_m1_features(bars)
    for minutes, prefix in [(5, "m5"), (15, "m15"), (60, "h1")]:
        htf = make_htf_features(bars, minutes, prefix)
        panel = pd.merge_asof(
            panel.sort_values("timestamp"), htf.sort_values("timestamp"), on="timestamp", direction="backward"
        )
    start = trades["open_time"].min().floor("min")
    end = trades["open_time"].max().ceil("min")
    panel = panel[(panel["timestamp"] >= start) & (panel["timestamp"] <= end)].reset_index(drop=True)
    panel["entry_count"] = 0
    panel["entry"] = 0
    panel["direction"] = 0
    panel["tickets"] = ""
    lookup = pd.Series(panel.index, index=panel["timestamp"]).to_dict()
    grouped = trades.assign(entry_minute=trades["open_time"].dt.floor("min")).groupby("entry_minute")
    for timestamp, group in grouped:
        if timestamp not in lookup:
            continue
        index = lookup[timestamp]
        signs = np.where(group["side"].eq("Buy"), 1, -1)
        panel.at[index, "entry_count"] = len(group)
        panel.at[index, "entry"] = 1
        panel.at[index, "direction"] = 1 if signs.sum() >= 0 else -1
        panel.at[index, "tickets"] = ";".join(group["ticket"].astype(str))
    return panel


@dataclass
class NumericModel:
    estimator: Any
    median: np.ndarray
    mean: np.ndarray
    std: np.ndarray
    scale: bool
    columns: list[str]

    def probabilities(self, frame: pd.DataFrame) -> np.ndarray:
        values = frame[self.columns].to_numpy(dtype=float)
        values = np.where(np.isfinite(values), values, self.median)
        if self.scale:
            values = (values - self.mean) / self.std
        return self.estimator.predict_proba(values)[:, 1]


def fit_numeric_model(
    frame: pd.DataFrame,
    columns: list[str],
    target: str,
    *,
    kind: str,
    seed: int,
    negative_ratio: int | None = None,
) -> NumericModel:
    y = frame[target].to_numpy(dtype=int)
    if negative_ratio is not None:
        positive = np.flatnonzero(y == 1)
        negative = np.flatnonzero(y == 0)
        generator = np.random.default_rng(seed)
        keep_negative = generator.choice(
            negative, size=min(len(negative), max(len(positive) * negative_ratio, 1)), replace=False
        )
        keep = np.sort(np.concatenate([positive, keep_negative]))
        working = frame.iloc[keep]
        y = y[keep]
    else:
        working = frame
    values = working[columns].to_numpy(dtype=float)
    median = np.nanmedian(values, axis=0)
    median = np.where(np.isfinite(median), median, 0.0)
    values = np.where(np.isfinite(values), values, median)
    scale = kind != "hist"
    mean = values.mean(axis=0) if scale else np.zeros(values.shape[1])
    std = values.std(axis=0) if scale else np.ones(values.shape[1])
    std = np.where(std > 1e-12, std, 1.0)
    transformed = (values - mean) / std if scale else values
    if kind == "hist":
        estimator = HistGradientBoostingClassifier(
            learning_rate=0.06,
            max_iter=120,
            max_depth=3,
            min_samples_leaf=50,
            l2_regularization=1.0,
            class_weight="balanced",
            random_state=seed,
        )
    else:
        estimator = LogisticRegression(
            C=0.35 if kind == "l1" else 1.0,
            penalty="l1" if kind == "l1" else "l2",
            solver="liblinear" if kind == "l1" else "lbfgs",
            class_weight="balanced",
            max_iter=2_000,
            random_state=seed,
        )
    estimator.fit(transformed, y)
    return NumericModel(estimator, median, mean, std, scale, columns)


def calibrated_fit(
    train: pd.DataFrame,
    columns: list[str],
    *,
    kind: str,
    seed: int,
) -> tuple[NumericModel, float]:
    split = max(int(len(train) * 0.80), 1)
    fit_part = train.iloc[:split]
    calibration = train.iloc[split:]
    if fit_part["entry"].sum() < 5 or calibration["entry"].sum() < 2:
        model = fit_numeric_model(train, columns, "entry", kind=kind, seed=seed, negative_ratio=50)
        return model, 0.5
    first = fit_numeric_model(fit_part, columns, "entry", kind=kind, seed=seed, negative_ratio=50)
    probability = first.probabilities(calibration)
    precision, recall, thresholds = precision_recall_curve(calibration["entry"], probability)
    if len(thresholds) == 0:
        threshold = 0.5
    else:
        f1 = 2 * precision[:-1] * recall[:-1] / (precision[:-1] + recall[:-1] + 1e-12)
        threshold = float(thresholds[int(np.nanargmax(f1))])
    final = fit_numeric_model(train, columns, "entry", kind=kind, seed=seed + 100, negative_ratio=50)
    return final, threshold


def chronological_folds(panel: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    start = panel["timestamp"].min()
    end = panel["timestamp"].max() + pd.Timedelta(minutes=1)
    span = end - start
    initial_end = start + span * 0.35
    test_width = span * (0.65 / 5)
    folds = []
    for fold in range(5):
        test_start = initial_end + test_width * fold
        test_end = end if fold == 4 else initial_end + test_width * (fold + 1)
        folds.append((start, test_start, test_end))
    return folds


def nearest_errors(observed: pd.Series, predicted: pd.Series) -> np.ndarray:
    if len(predicted) == 0:
        return np.full(len(observed), np.inf)
    target = observed.astype("int64").to_numpy()
    candidates = np.sort(predicted.astype("int64").to_numpy())
    positions = np.searchsorted(candidates, target)
    errors = np.full(len(target), np.iinfo(np.int64).max, dtype=np.int64)
    for offset in [0, -1]:
        indexes = np.clip(positions + offset, 0, len(candidates) - 1)
        errors = np.minimum(errors, np.abs(candidates[indexes] - target))
    return errors / 1e9


def entry_reconstruction(
    panel: pd.DataFrame, trades: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    time_features = [
        "hour_sin", "hour_cos", "dow_sin", "dow_cos", "minute_sin", "minute_cos",
        "boundary_5", "boundary_15", "boundary_30", "boundary_60",
    ]
    expansion = [
        "m1_body_abs", "m1_body_ratio", "m1_range", "m1_upper_wick_ratio", "m1_lower_wick_ratio",
        "m1_return_1", "m1_return_2", "m1_return_3", "m1_return_5", "m1_velocity_3", "m1_velocity_5",
        "m1_atr14", "m1_atr_ratio", "m1_range_expansion", "m1_range_percentile_240",
        "m1_volume_z240", "m1_compression_expansion",
    ]
    trend = [
        "m1_ema5_dist", "m1_ema9_dist", "m1_ema20_dist", "m1_ema50_dist", "m1_ema100_dist",
        "m1_ema5_slope5", "m1_ema9_slope5", "m1_ema20_slope5", "m1_ema50_slope5",
        "m1_ema5_9_spread", "m1_ema9_20_spread", "m1_ema20_50_spread",
        "m1_breakout_high_10", "m1_breakout_low_10", "m1_breakout_high_20", "m1_breakout_low_20",
        "m1_breakout_high_50", "m1_breakout_low_50", "m1_session_high_dist", "m1_session_low_dist",
    ]
    vwap = ["m1_vwap_dist"]
    htf = [column for column in panel.columns if column.startswith(("m5_", "m15_", "h1_"))]
    combined_prior = [
        "m1_body_abs", "m1_body_ratio", "m1_ema9_20_spread", "m1_vwap_dist", "m1_return_1"
    ]
    full = list(dict.fromkeys(time_features + expansion + trend + vwap + htf))
    architectures: dict[str, tuple[list[str], str, str]] = {
        "MODEL 0 time/session": (time_features, "logit", "Time and bar-clock state only"),
        "MODEL 1 M1 expansion": (expansion, "logit", "Prior completed M1 expansion only"),
        "MODEL 2 expansion+trend": (expansion + trend, "logit", "M1 expansion and trend/location"),
        "MODEL 3 expansion+trend+VWAP": (expansion + trend + vwap, "logit", "Adds session VWAP proxy"),
        "MODEL 4 expansion+session": (expansion + time_features, "logit", "M1 expansion plus clock state"),
        "MODEL 5 expansion+session+HTF": (expansion + time_features + htf, "logit", "Adds completed M5/M15/H1 context"),
        "MODEL 6 prior interpretable": (combined_prior, "logit", "Lagged version of prior body/EMA/VWAP candidate"),
        "MODEL 7 sparse rule": (full, "l1", "L1 sparse logistic rule"),
        "MODEL 8 constrained nonlinear": (full, "hist", "120 depth-3 boosted trees"),
    }
    folds = chronological_folds(panel)
    fold_rows: list[dict[str, Any]] = []
    stored_predictions: dict[str, list[pd.DataFrame]] = {name: [] for name in architectures}
    direction_actual = panel[panel["entry"].eq(1)].copy()

    for model_number, (name, (columns, kind, description)) in enumerate(architectures.items()):
        for fold_number, (_, test_start, test_end) in enumerate(folds, start=1):
            train = panel[panel["timestamp"] < test_start]
            test = panel[(panel["timestamp"] >= test_start) & (panel["timestamp"] < test_end)]
            model, threshold = calibrated_fit(train, columns, kind=kind, seed=SEED + model_number * 20 + fold_number)
            probability = model.probabilities(test)
            predicted = probability >= threshold
            actual = test["entry"].to_numpy(dtype=bool)
            tp = int(np.sum(predicted & actual))
            fp = int(np.sum(predicted & ~actual))
            fn = int(np.sum(~predicted & actual))
            roc = roc_auc_score(actual, probability) if actual.min() != actual.max() else np.nan
            pr_auc = average_precision_score(actual, probability) if actual.sum() else np.nan

            train_entries = train[train["entry"].eq(1)]
            test_entries = test[test["entry"].eq(1)]
            direction_model = None
            direction_accuracy = np.nan
            if train_entries["direction"].nunique() == 2 and len(test_entries):
                direction_training = train_entries.assign(buy=(train_entries["direction"] == 1).astype(int))
                direction_model = fit_numeric_model(
                    direction_training, columns, "buy", kind="logit", seed=SEED + 800 + fold_number
                )
                matched_test = test[predicted & actual]
                if len(matched_test):
                    direction_pred = np.where(direction_model.probabilities(matched_test) >= 0.5, 1, -1)
                    direction_accuracy = accuracy_score(matched_test["direction"], direction_pred)

            predicted_rows = test.loc[predicted, ["timestamp"]].copy()
            predicted_rows["probability"] = probability[predicted]
            predicted_rows["fold"] = fold_number
            if direction_model is not None and len(predicted_rows):
                predicted_rows["predicted_direction"] = np.where(
                    direction_model.probabilities(test.loc[predicted]) >= 0.5, "Buy", "Sell"
                )
            else:
                predicted_rows["predicted_direction"] = ""
            stored_predictions[name].append(predicted_rows)

            observed_trades = trades[
                (trades["open_time"] >= test_start) & (trades["open_time"] < test_end)
            ]
            errors = nearest_errors(observed_trades["open_time"], predicted_rows["timestamp"])
            entry_floor = observed_trades["open_time"].dt.floor("min")
            predicted_set = set(predicted_rows["timestamp"])
            one_bar = float(np.mean([any(abs((candidate - minute).total_seconds()) <= 60 for candidate in predicted_set) for minute in entry_floor])) if len(observed_trades) and predicted_set else 0.0
            fold_rows.append(
                {
                    "model": name,
                    "description": description,
                    "fold": fold_number,
                    "train_from": train["timestamp"].min(),
                    "train_to": train["timestamp"].max(),
                    "test_from": test_start,
                    "test_to": test_end,
                    "train_entry_bars": int(train["entry"].sum()),
                    "test_entry_bars": int(actual.sum()),
                    "historical_candidate_signals_test": int(predicted.sum()),
                    "tp": tp,
                    "fp": fp,
                    "fn": fn,
                    "precision": precision_score(actual, predicted, zero_division=0),
                    "recall": recall_score(actual, predicted, zero_division=0),
                    "f1": f1_score(actual, predicted, zero_division=0),
                    "roc_auc": roc,
                    "pr_auc": pr_auc,
                    "direction_accuracy_matched": direction_accuracy,
                    "entry_match_1s": float(np.mean(errors <= 1)) if len(errors) else np.nan,
                    "entry_match_5s": float(np.mean(errors <= 5)) if len(errors) else np.nan,
                    "entry_match_15s": float(np.mean(errors <= 15)) if len(errors) else np.nan,
                    "entry_match_30s": float(np.mean(errors <= 30)) if len(errors) else np.nan,
                    "entry_match_60s": float(np.mean(errors <= 60)) if len(errors) else np.nan,
                    "entry_match_one_m1_bar": one_bar,
                    "threshold": threshold,
                    "features_or_rules": len(columns) if kind != "hist" else 120,
                    "complexity": "linear" if kind == "logit" else ("sparse linear" if kind == "l1" else "depth-3 nonlinear"),
                    "bic_mdl": "not valid under class weighting/case-control fitting",
                }
            )

    walk = pd.DataFrame(fold_rows)
    summaries = []
    for name, (columns, kind, description) in architectures.items():
        part = walk[walk["model"].eq(name)]
        model, threshold = calibrated_fit(panel, columns, kind=kind, seed=SEED + 1_500)
        probability = model.probabilities(panel)
        predicted = probability >= threshold
        actual = panel["entry"].to_numpy(dtype=bool)
        nonzero = len(columns)
        if kind in {"logit", "l1"}:
            nonzero = int(np.sum(np.abs(model.estimator.coef_) > 1e-9))
        summaries.append(
            {
                "model": name,
                "description": description,
                "historical_candidate_signals": int(predicted.sum()),
                "historical_matched_entry_bars": int(np.sum(predicted & actual)),
                "historical_precision": precision_score(actual, predicted, zero_division=0),
                "historical_recall": recall_score(actual, predicted, zero_division=0),
                "oos_tp": int(part["tp"].sum()),
                "oos_fp": int(part["fp"].sum()),
                "oos_fn": int(part["fn"].sum()),
                "oos_precision": float(part["tp"].sum() / max(part["tp"].sum() + part["fp"].sum(), 1)),
                "oos_recall": float(part["tp"].sum() / max(part["tp"].sum() + part["fn"].sum(), 1)),
                "oos_f1_mean": float(part["f1"].mean()),
                "oos_roc_auc_mean": float(part["roc_auc"].mean()),
                "oos_pr_auc_mean": float(part["pr_auc"].mean()),
                "oos_direction_accuracy_matched": float(part["direction_accuracy_matched"].mean()),
                "oos_entry_match_1s_mean": float(part["entry_match_1s"].mean()),
                "oos_entry_match_5s_mean": float(part["entry_match_5s"].mean()),
                "oos_entry_match_15s_mean": float(part["entry_match_15s"].mean()),
                "oos_entry_match_30s_mean": float(part["entry_match_30s"].mean()),
                "oos_entry_match_60s_mean": float(part["entry_match_60s"].mean()),
                "oos_entry_match_one_m1_bar_mean": float(part["entry_match_one_m1_bar"].mean()),
                "parameters_or_rules": nonzero if kind != "hist" else 120,
                "complexity": "linear" if kind == "logit" else ("sparse linear" if kind == "l1" else "120 depth-3 trees"),
                "bic_mdl": "not valid",
            }
        )
    comparison = pd.DataFrame(summaries).sort_values(
        ["oos_f1_mean", "oos_pr_auc_mean"], ascending=False
    ).reset_index(drop=True)
    best_name = str(comparison.iloc[0]["model"])
    best_predictions = pd.concat(stored_predictions[best_name], ignore_index=True).sort_values("timestamp")

    # Per-observed-trade OOS match table. Initial 35% is shown as not OOS-evaluated.
    first_test = folds[0][1]
    match_rows = []
    pred_times = best_predictions["timestamp"]
    for trade in trades.sort_values("open_time").itertuples(index=False):
        scope = "OOS" if trade.open_time >= first_test else "initial training period"
        available = best_predictions if scope == "OOS" else best_predictions.iloc[0:0]
        if len(available):
            delta = (available["timestamp"] - trade.open_time).abs()
            selected = available.loc[delta.idxmin()]
            error = abs((selected["timestamp"] - trade.open_time).total_seconds())
            candidate_time = selected["timestamp"] if error <= 60 else pd.NaT
            candidate_direction = selected["predicted_direction"] if error <= 60 else ""
        else:
            error = np.nan
            candidate_time = pd.NaT
            candidate_direction = ""
        match_rows.append(
            {
                "ticket": trade.ticket,
                "evaluation_scope": scope,
                "observed_entry_time": trade.open_time,
                "observed_direction": trade.side,
                "observed_price": trade.observed_price,
                "observed_close_time": trade.close_time,
                "observed_pnl": trade.pnl,
                "candidate_entry_time": candidate_time,
                "candidate_direction": candidate_direction,
                "entry_error_seconds": error,
                "entry_match_within_1s": bool(np.isfinite(error) and error <= 1),
                "entry_match_within_5s": bool(np.isfinite(error) and error <= 5),
                "entry_match_within_15s": bool(np.isfinite(error) and error <= 15),
                "entry_match_within_30s": bool(np.isfinite(error) and error <= 30),
                "entry_match_within_60s": bool(np.isfinite(error) and error <= 60),
                "entry_match_within_one_m1_bar": bool(np.isfinite(error) and error < 120),
                "direction_match": bool(candidate_direction == trade.side) if candidate_direction else False,
                "model": best_name,
            }
        )
    match_table = pd.DataFrame(match_rows)

    # Negative-space: nearest same-day +/-120-minute non-entry states in an interpretable state space.
    near_columns = [
        "m1_body_abs", "m1_body_ratio", "m1_range_expansion", "m1_atr_ratio",
        "m1_velocity_5", "m1_ema9_20_spread", "m1_vwap_dist", "hour_sin", "hour_cos",
    ]
    values = panel[near_columns].to_numpy(dtype=float)
    med = np.nanmedian(values, axis=0)
    values = np.where(np.isfinite(values), values, med)
    scale = np.where(values.std(axis=0) > 1e-9, values.std(axis=0), 1)
    standardized = (values - values.mean(axis=0)) / scale
    panel_day = panel["timestamp"].dt.floor("D")
    near_rows = []
    for entry_index in panel.index[panel["entry"].eq(1)]:
        timestamp = panel.at[entry_index, "timestamp"]
        candidates = panel.index[
            panel["entry"].eq(0)
            & panel_day.eq(timestamp.floor("D"))
            & ((panel["timestamp"] - timestamp).abs() <= pd.Timedelta("120min"))
        ]
        if len(candidates) == 0:
            continue
        distances = np.sqrt(np.sum((standardized[candidates] - standardized[entry_index]) ** 2, axis=1))
        for rank, local in enumerate(np.argsort(distances)[:3], start=1):
            candidate_index = int(candidates[local])
            row = {
                "entry_timestamp": timestamp,
                "tickets": panel.at[entry_index, "tickets"],
                "near_miss_rank": rank,
                "near_miss_timestamp": panel.at[candidate_index, "timestamp"],
                "state_distance": float(distances[local]),
                "minutes_from_entry": float((panel.at[candidate_index, "timestamp"] - timestamp).total_seconds() / 60),
            }
            for column in near_columns:
                row[f"entry_{column}"] = panel.at[entry_index, column]
                row[f"near_miss_{column}"] = panel.at[candidate_index, column]
            near_rows.append(row)
    near_misses = pd.DataFrame(near_rows)
    metrics = {
        "best_model": best_name,
        "best_oos": comparison.iloc[0].to_dict(),
        "folds": 5,
        "initial_training_fraction": 0.35,
        "entry_bars": int(panel["entry"].sum()),
        "trades": int(len(trades)),
        "m1_limit": "Predictors use the previous completed M1 bar; exact intraminute trigger is unidentifiable.",
    }
    return comparison, walk, match_table, near_misses, metrics


def price_and_ticket_audit(trades: pd.DataFrame) -> dict[str, Any]:
    ordered = trades.sort_values("open_time").reset_index(drop=True).copy()
    ordered["ticket_numeric"] = pd.to_numeric(ordered["ticket"], errors="coerce")
    ticket_diff = ordered["ticket_numeric"].diff()
    tau, tau_p = stats.kendalltau(np.arange(len(ordered)), ordered["ticket_numeric"])
    jump_index = int(ticket_diff.idxmax())
    multipliers = [10, 50, 100, 200, 1_000]
    pair_rows = []
    for index in range(len(ordered) - 1):
        previous = ordered.iloc[index]
        following = ordered.iloc[index + 1]
        gap = (following["open_time"] - previous["close_time"]).total_seconds()
        if gap < 0 or gap > 600:
            continue
        side_sign = 1 if previous["side"] == "Buy" else -1
        row = {"previous_ticket": previous["ticket"], "next_ticket": following["ticket"], "gap_seconds": gap}
        row["exit_price_hypothesis_discrepancy"] = abs(previous["observed_price"] - following["observed_price"])
        for multiplier in multipliers:
            inferred_exit = previous["observed_price"] + side_sign * previous["pnl"] / (previous["lot_size"] * multiplier)
            row[f"entry_price_m{multiplier}_discrepancy"] = abs(inferred_exit - following["observed_price"])
        pair_rows.append(row)
    pairs = pd.DataFrame(pair_rows)
    median_by_multiplier = {
        str(multiplier): float(pairs[f"entry_price_m{multiplier}_discrepancy"].median()) for multiplier in multipliers
    }
    best_multiplier = int(min(multipliers, key=lambda value: median_by_multiplier[str(value)]))
    best = pairs[f"entry_price_m{best_multiplier}_discrepancy"]
    exit_hypothesis = pairs["exit_price_hypothesis_discrepancy"]
    wilcoxon = stats.wilcoxon(best, exit_hypothesis, alternative="less") if len(pairs) else None
    anomaly = ordered[ordered["ticket"].astype(str).eq("36227388")].iloc[0]
    parity_cents = anomaly["pnl"] * 100
    expected_increment_cents = anomaly["lot_size"] * 100 * 100
    return {
        "adjacent_ticket_inversions": int((ticket_diff.dropna() < 0).sum()),
        "adjacent_ticket_pairs": int(len(ordered) - 1),
        "kendall_tau": float(tau),
        "kendall_tau_p": float(tau_p),
        "ticket_jump_index": jump_index,
        "ticket_jump_time": ordered.loc[jump_index, "open_time"],
        "ticket_jump_size": float(ticket_diff.loc[jump_index]),
        "segment_a_n": jump_index,
        "segment_b_n": int(len(ordered) - jump_index),
        "price_pair_definition": "chronologically adjacent, non-overlapping, next open within 10 minutes of prior close",
        "price_pair_n": int(len(pairs)),
        "median_discrepancy_by_multiplier": median_by_multiplier,
        "best_multiplier": best_multiplier,
        "best_median_discrepancy": float(best.median()),
        "best_p75_discrepancy": float(best.quantile(0.75)),
        "best_share_le_1": float((best <= 1).mean()),
        "best_share_le_2": float((best <= 2).mean()),
        "entry_vs_exit_hypothesis_wilcoxon_p": float(wilcoxon.pvalue) if wilcoxon else np.nan,
        "anomaly_ticket": str(anomaly["ticket"]),
        "anomaly_pnl_cents": float(parity_cents),
        "expected_increment_cents_under_2dp_100oz": float(expected_increment_cents),
    }


def round_minute_audit(trades: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    entry = trades.copy()
    entry["entry_minute"] = entry["open_time"].dt.floor("min")
    eligible = panel[["timestamp"]].copy()
    eligible["date"] = eligible["timestamp"].dt.floor("D")
    eligible["hour"] = eligible["timestamp"].dt.hour
    groups = {
        key: group["timestamp"].to_numpy()
        for key, group in eligible.groupby(["date", "hour"], sort=False)
    }
    rows = []
    simulations = 5_000
    for boundary in [5, 15, 30, 60]:
        observed = int(
            ((entry["open_time"].dt.minute % boundary == 0) if boundary < 60 else (entry["open_time"].dt.minute == 0)).sum()
        )
        null_counts = np.zeros(simulations, dtype=int)
        for trade in entry.itertuples(index=False):
            key = (trade.open_time.floor("D"), trade.open_time.hour)
            candidates = groups.get(key)
            if candidates is None or len(candidates) == 0:
                continue
            chosen = candidates[RNG.integers(0, len(candidates), simulations)]
            minutes = pd.DatetimeIndex(chosen).minute.to_numpy()
            null_counts += (minutes % boundary == 0) if boundary < 60 else (minutes == 0)
        p_value = (1 + np.sum(null_counts >= observed)) / (simulations + 1)
        rows.append(
            {
                "boundary_minutes": boundary,
                "observed_count": observed,
                "sample_size": len(entry),
                "observed_share": observed / len(entry),
                "null_mean_count_same_day_hour": float(null_counts.mean()),
                "effect_observed_minus_null_share": float((observed - null_counts.mean()) / len(entry)),
                "permutation_p": p_value,
                "null": "entry minute exchangeable with eligible M1 bars from same date and raw hour",
                "limitations": "raw timezone; M1 eligibility proxy; within-hour intensity not fully modeled",
            }
        )
    result = pd.DataFrame(rows)
    result["bh_q"] = bh_adjust(result["permutation_p"])
    return result


def cliff_delta(large: np.ndarray, base: np.ndarray) -> float:
    if not len(large) or not len(base):
        return np.nan
    return float((np.sum(large[:, None] > base[None, :]) - np.sum(large[:, None] < base[None, :])) / (len(large) * len(base)))


def sizing_analysis(trades: pd.DataFrame, panel: pd.DataFrame, ticket_audit: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    data = trades.sort_values("open_time").reset_index(drop=True).copy()
    data["large_lot"] = (data["lot_size"] > 0.01).astype(int)
    data["previous_large"] = data["large_lot"].shift(1).fillna(0).astype(int)
    data["previous_win_pre"] = data["win"].shift(1).fillna(False).astype(int)
    data["previous_pnl_pre"] = data["pnl"].shift(1)
    data["previous_pnl_per_001_pre"] = data["pnl_per_0_01_lot"].shift(1)
    data["previous_size_pre"] = data["lot_size"].shift(1)
    data["recent5_pnl_pre"] = data["pnl"].shift(1).rolling(5, min_periods=1).sum()
    data["recent5_win_rate_pre"] = data["win"].shift(1).rolling(5, min_periods=1).mean()
    data["cumulative_pnl_pre"] = data["pnl"].cumsum().shift(1).fillna(0)
    data["first_trade_day"] = (~data["open_time"].dt.floor("D").duplicated()).astype(int)
    data["buy"] = data["side"].eq("Buy").astype(int)
    data["segment_b"] = (data["open_time"] >= pd.Timestamp(ticket_audit["ticket_jump_time"])).astype(int)
    data["gap_entry_pre"] = data["open_time"].diff().dt.total_seconds().div(60)
    data["gap_exit_pre"] = (data["open_time"] - data["close_time"].shift(1)).dt.total_seconds().div(60)
    minutes = data["open_time"].dt.hour * 60 + data["open_time"].dt.minute
    data["hour_sin"] = np.sin(2 * np.pi * minutes / 1440)
    data["hour_cos"] = np.cos(2 * np.pi * minutes / 1440)
    mapping = panel.set_index("timestamp")
    entry_minute = data["open_time"].dt.floor("min")
    for column in ["m1_atr14", "m1_atr_ratio", "m1_close", "m1_ema20_dist", "m1_range_percentile_240"]:
        data[column] = mapping[column].reindex(entry_minute).to_numpy()

    categorical = ["previous_large", "previous_win_pre", "first_trade_day", "buy", "segment_b"]
    continuous = [
        "previous_pnl_pre", "previous_size_pre", "recent5_pnl_pre", "recent5_win_rate_pre",
        "previous_pnl_per_001_pre", "cumulative_pnl_pre", "gap_entry_pre", "gap_exit_pre", "hour_sin", "hour_cos",
        "m1_atr14", "m1_atr_ratio", "m1_close", "m1_ema20_dist", "m1_range_percentile_240",
    ]
    tests = []
    for column in categorical:
        table = pd.crosstab(data[column], data["large_lot"]).reindex(index=[0, 1], columns=[0, 1], fill_value=0)
        odds, p_value = stats.fisher_exact(table.to_numpy())
        rate0 = table.loc[0, 1] / max(table.loc[0].sum(), 1)
        rate1 = table.loc[1, 1] / max(table.loc[1].sum(), 1)
        tests.append(
            {
                "predictor": column,
                "family": "pre-trade sizing univariate",
                "test": "Fisher exact",
                "n": len(data),
                "large_lot_n": int(data["large_lot"].sum()),
                "effect": rate1 - rate0,
                "effect_label": "large-lot rate difference (1 minus 0)",
                "odds_ratio": odds,
                "p_value": p_value,
                "null": "large-lot indicator independent of predictor",
            }
        )
    for column in continuous:
        valid = data[[column, "large_lot"]].dropna()
        large = valid.loc[valid["large_lot"].eq(1), column].to_numpy(float)
        base = valid.loc[valid["large_lot"].eq(0), column].to_numpy(float)
        if len(large) and len(base):
            mann = stats.mannwhitneyu(large, base, alternative="two-sided")
            effect = cliff_delta(large, base)
            combined = valid[column].to_numpy(float)
            labels = valid["large_lot"].to_numpy(int)
            observed = abs(np.median(large) - np.median(base))
            exceed = 0
            for _ in range(2_000):
                perm = RNG.permutation(labels)
                difference = abs(np.median(combined[perm == 1]) - np.median(combined[perm == 0]))
                exceed += difference >= observed
            permutation_p = (exceed + 1) / 2_001
        else:
            mann = None
            effect = np.nan
            permutation_p = np.nan
        tests.append(
            {
                "predictor": column,
                "family": "pre-trade sizing univariate",
                "test": "Mann-Whitney plus label permutation",
                "n": len(valid),
                "large_lot_n": len(large),
                "effect": effect,
                "effect_label": "Cliff delta (large minus base)",
                "odds_ratio": np.nan,
                "p_value": float(mann.pvalue) if mann else np.nan,
                "permutation_p": permutation_p,
                "null": "pre-trade distributions exchangeable across size groups",
            }
        )
    univariate = pd.DataFrame(tests)
    univariate["family_p"] = univariate[["p_value", "permutation_p"]].max(axis=1, skipna=True)
    univariate["bh_q"] = bh_adjust(univariate["family_p"])

    predictors = categorical + continuous
    fold_rows = []
    initial = int(len(data) * 0.35)
    width = math.ceil((len(data) - initial) / 5)
    for fold in range(5):
        test_start = initial + fold * width
        test_end = min(len(data), initial + (fold + 1) * width)
        if test_start >= len(data):
            break
        train = data.iloc[:test_start]
        test = data.iloc[test_start:test_end]
        model = fit_numeric_model(train, predictors, "large_lot", kind="l1", seed=SEED + fold)
        probability = model.probabilities(test)
        actual = test["large_lot"].to_numpy(int)
        fold_rows.append(
            {
                "fold": fold + 1,
                "train_n": len(train),
                "test_n": len(test),
                "train_large": int(train["large_lot"].sum()),
                "test_large": int(test["large_lot"].sum()),
                "roc_auc": roc_auc_score(actual, probability) if len(np.unique(actual)) == 2 else np.nan,
                "pr_auc": average_precision_score(actual, probability) if actual.sum() else np.nan,
                "base_rate": actual.mean(),
            }
        )
    walk = pd.DataFrame(fold_rows)
    segment_table = pd.crosstab(data["segment_b"], data["large_lot"]).reindex(index=[0, 1], columns=[0, 1], fill_value=0)
    segment_or, segment_p = stats.fisher_exact(segment_table.to_numpy())
    overall_probability = data["win"].mean()
    all_win_simple_p = overall_probability ** int(data["large_lot"].sum())
    segment_adjusted_all_win = 1.0
    for segment in [0, 1]:
        subset = data[data["segment_b"].eq(segment)]
        segment_adjusted_all_win *= float(subset["win"].mean() ** subset["large_lot"].sum())
    large_sequence = data["large_lot"].to_numpy()
    adjacent_large_pairs = int(np.sum((large_sequence[:-1] == 1) & (large_sequence[1:] == 1)))
    null_adjacent = []
    for _ in range(5_000):
        permuted = RNG.permutation(large_sequence)
        null_adjacent.append(int(np.sum((permuted[:-1] == 1) & (permuted[1:] == 1))))
    adjacent_permutation_p = (1 + np.sum(np.asarray(null_adjacent) >= adjacent_large_pairs)) / 5_001
    lot_equity_spearman = stats.spearmanr(data["lot_size"], data["cumulative_pnl_pre"])
    metrics = {
        "large_lot_n": int(data["large_lot"].sum()),
        "large_lot_wins": int(data.loc[data["large_lot"].eq(1), "win"].sum()),
        "simple_iid_all_win_probability": float(all_win_simple_p),
        "segment_adjusted_all_win_probability": float(segment_adjusted_all_win),
        "adjacent_large_pairs": adjacent_large_pairs,
        "adjacent_large_null_mean": float(np.mean(null_adjacent)),
        "adjacent_large_permutation_p": float(adjacent_permutation_p),
        "lot_vs_cumulative_pnl_pre_spearman": float(lot_equity_spearman.statistic),
        "lot_vs_cumulative_pnl_pre_p": float(lot_equity_spearman.pvalue),
        "segment_table": segment_table.to_dict(),
        "segment_fisher_odds_ratio": float(segment_or),
        "segment_fisher_p": float(segment_p),
        "segment_a_large_rate": float(data.loc[data["segment_b"].eq(0), "large_lot"].mean()),
        "segment_b_large_rate": float(data.loc[data["segment_b"].eq(1), "large_lot"].mean()),
        "significant_bh_predictors": univariate.loc[univariate["bh_q"] <= 0.05, "predictor"].tolist(),
        "walk_forward_mean_auc": float(walk["roc_auc"].mean()),
        "walk_forward_mean_pr_auc": float(walk["pr_auc"].mean()),
        "conclusion": "Size is dominated by the ticket/time segment; 22/22 wins does not identify conviction sizing.",
    }
    return univariate, walk, metrics


def inferred_exit_price(trade: pd.Series, multiplier: float = 100.0) -> float:
    sign = 1 if trade["side"] == "Buy" else -1
    return float(trade["observed_price"] + sign * trade["pnl"] / (trade["lot_size"] * multiplier))


def exit_candidate(
    trade: pd.Series,
    bars_indexed: pd.DataFrame,
    feature_indexed: pd.DataFrame,
    candidate: str,
    parameters: dict[str, float],
) -> tuple[pd.Timestamp, float, str]:
    start = trade["open_time"].floor("min")
    horizon = max(float(parameters.get("max_minutes", 60)), 1)
    end = start + pd.Timedelta(minutes=horizon)
    path = bars_indexed.loc[start:end]
    if path.empty:
        return pd.NaT, np.nan, "no_reference_path"
    side = 1 if trade["side"] == "Buy" else -1
    entry = float(trade["observed_price"])
    atr = float(parameters.get("atr", np.nan))
    stop = float(parameters.get("stop", np.nan))
    target = float(parameters.get("target", np.nan))
    if candidate == "median_time_stop":
        target_time = start + pd.Timedelta(minutes=parameters["median_minutes"])
        location = path.index.get_indexer([target_time], method="nearest")[0]
        row = path.iloc[location]
        return row.name + pd.Timedelta(minutes=1), float(row["close"]), "time"
    if candidate in {"fixed_barriers", "atr_barriers", "hybrid_barrier_time"}:
        if candidate == "atr_barriers":
            stop = parameters["stop_atr"] * atr
            target = parameters["target_atr"] * atr
        for timestamp, row in path.iterrows():
            favorable = (row["high"] - entry) if side == 1 else (entry - row["low"])
            adverse = (entry - row["low"]) if side == 1 else (row["high"] - entry)
            if adverse >= stop and favorable >= target:
                return timestamp + pd.Timedelta(minutes=1), entry - side * stop, "both_hit_adverse_first"
            if adverse >= stop:
                return timestamp + pd.Timedelta(minutes=1), entry - side * stop, "stop_proxy"
            if favorable >= target:
                return timestamp + pd.Timedelta(minutes=1), entry + side * target, "target_proxy"
        row = path.iloc[-1]
        return row.name + pd.Timedelta(minutes=1), float(row["close"]), "horizon"
    features = feature_indexed.reindex(path.index)
    if candidate == "ema9_failure":
        condition = (features["m1_ema9_dist"] < 0) if side == 1 else (features["m1_ema9_dist"] > 0)
    elif candidate == "vwap_failure":
        condition = (features["m1_vwap_dist"] < 0) if side == 1 else (features["m1_vwap_dist"] > 0)
    elif candidate == "momentum_failure":
        condition = (features["m1_return_3"] < 0) if side == 1 else (features["m1_return_3"] > 0)
    else:
        condition = pd.Series(False, index=path.index)
    hit = condition[condition.fillna(False)]
    if len(hit):
        timestamp = hit.index[0]
        return timestamp + pd.Timedelta(minutes=1), float(path.loc[timestamp, "close"]), candidate
    row = path.iloc[-1]
    return row.name + pd.Timedelta(minutes=1), float(row["close"]), "horizon"


def fit_exit_parameters(train: pd.DataFrame, feature_indexed: pd.DataFrame) -> dict[str, float]:
    working = train.copy()
    working["inferred_exit"] = working.apply(inferred_exit_price, axis=1)
    working["signed_move"] = np.where(
        working["side"].eq("Buy"),
        working["inferred_exit"] - working["observed_price"],
        working["observed_price"] - working["inferred_exit"],
    )
    entry_minute = working["open_time"].dt.floor("min")
    atr = feature_indexed["m1_atr14"].reindex(entry_minute).to_numpy()
    winners = working["signed_move"] > 0
    losers = working["signed_move"] < 0
    stop = float(np.median(np.abs(working.loc[losers, "signed_move"])))
    target = float(np.median(working.loc[winners, "signed_move"]))
    stop_atr = float(np.nanmedian(np.abs(working.loc[losers, "signed_move"].to_numpy()) / atr[losers]))
    target_atr = float(np.nanmedian(working.loc[winners, "signed_move"].to_numpy() / atr[winners]))
    return {
        "median_minutes": float(working["duration_minutes"].median()),
        "max_minutes": float(min(max(working["duration_minutes"].quantile(0.95), 15), 240)),
        "stop": stop,
        "target": target,
        "stop_atr": stop_atr,
        "target_atr": target_atr,
    }


def exit_reconstruction(trades: pd.DataFrame, bars: pd.DataFrame, panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    ordered = trades.sort_values("open_time").reset_index(drop=True)
    bars_indexed = bars.set_index("timestamp").sort_index()
    feature_indexed = panel.set_index("timestamp").sort_index()
    candidates = [
        "median_time_stop", "fixed_barriers", "atr_barriers", "ema9_failure", "vwap_failure", "momentum_failure"
    ]
    initial = int(len(ordered) * 0.35)
    width = math.ceil((len(ordered) - initial) / 5)
    rows = []
    predictions: dict[str, list[dict[str, Any]]] = {candidate: [] for candidate in candidates}
    for fold in range(5):
        test_start = initial + fold * width
        test_end = min(len(ordered), initial + (fold + 1) * width)
        if test_start >= len(ordered):
            break
        train = ordered.iloc[:test_start]
        test = ordered.iloc[test_start:test_end]
        parameters = fit_exit_parameters(train, feature_indexed)
        for candidate in candidates:
            time_errors = []
            price_errors = []
            outcome_matches = []
            within_1m = []
            within_5m = []
            for _, trade in test.iterrows():
                per_trade = dict(parameters)
                minute = trade["open_time"].floor("min")
                per_trade["atr"] = feature_indexed["m1_atr14"].get(minute, np.nan)
                predicted_time, predicted_price, reason = exit_candidate(
                    trade, bars_indexed, feature_indexed, candidate, per_trade
                )
                actual_price = inferred_exit_price(trade)
                time_error = abs((predicted_time - trade["close_time"]).total_seconds()) if pd.notna(predicted_time) else np.nan
                price_error = abs(predicted_price - actual_price) if np.isfinite(predicted_price) else np.nan
                side = 1 if trade["side"] == "Buy" else -1
                predicted_win = side * (predicted_price - trade["observed_price"]) > 0 if np.isfinite(predicted_price) else False
                outcome_match = predicted_win == bool(trade["win"])
                time_errors.append(time_error)
                price_errors.append(price_error)
                outcome_matches.append(outcome_match)
                within_1m.append(time_error <= 60 if np.isfinite(time_error) else False)
                within_5m.append(time_error <= 300 if np.isfinite(time_error) else False)
                predictions[candidate].append(
                    {
                        "ticket": trade["ticket"],
                        "fold": fold + 1,
                        "observed_entry_time": trade["open_time"],
                        "observed_close_time": trade["close_time"],
                        "observed_direction": trade["side"],
                        "observed_entry_price": trade["observed_price"],
                        "inferred_exit_price_100oz": actual_price,
                        "observed_pnl": trade["pnl"],
                        "candidate": candidate,
                        "predicted_exit_time": predicted_time,
                        "predicted_exit_price_reference": predicted_price,
                        "exit_reason": reason,
                        "close_time_error_seconds": time_error,
                        "exit_price_error": price_error,
                        "win_loss_match": outcome_match,
                    }
                )
            rows.append(
                {
                    "candidate": candidate,
                    "fold": fold + 1,
                    "train_n": len(train),
                    "test_n": len(test),
                    "median_abs_close_time_error_seconds": float(np.nanmedian(time_errors)),
                    "median_abs_exit_price_error": float(np.nanmedian(price_errors)),
                    "close_within_1m_rate": float(np.mean(within_1m)),
                    "close_within_5m_rate": float(np.mean(within_5m)),
                    "win_loss_match_rate": float(np.mean(outcome_matches)),
                    "parameters": json.dumps(parameters),
                }
            )
    results = pd.DataFrame(rows)
    summary = results.groupby("candidate", as_index=False).agg(
        median_abs_close_time_error_seconds=("median_abs_close_time_error_seconds", "median"),
        median_abs_exit_price_error=("median_abs_exit_price_error", "median"),
        close_within_1m_rate=("close_within_1m_rate", "mean"),
        close_within_5m_rate=("close_within_5m_rate", "mean"),
        win_loss_match_rate=("win_loss_match_rate", "mean"),
    ).sort_values(["close_within_5m_rate", "median_abs_close_time_error_seconds"], ascending=[False, True])
    best = str(summary.iloc[0]["candidate"])
    match_table = pd.DataFrame(predictions[best]).sort_values("observed_entry_time")
    match_table["evaluation_scope"] = "OOS"
    # Required per-trade comparison: add the initial training period with a
    # clearly labelled in-sample fit, never mixing it into OOS metrics.
    full_parameters = fit_exit_parameters(ordered, feature_indexed)
    initial_rows = []
    for _, trade in ordered.iloc[:initial].iterrows():
        per_trade = dict(full_parameters)
        minute = trade["open_time"].floor("min")
        per_trade["atr"] = feature_indexed["m1_atr14"].get(minute, np.nan)
        predicted_time, predicted_price, reason = exit_candidate(
            trade, bars_indexed, feature_indexed, best, per_trade
        )
        actual_price = inferred_exit_price(trade)
        side = 1 if trade["side"] == "Buy" else -1
        initial_rows.append(
            {
                "ticket": trade["ticket"],
                "fold": 0,
                "observed_entry_time": trade["open_time"],
                "observed_close_time": trade["close_time"],
                "observed_direction": trade["side"],
                "observed_entry_price": trade["observed_price"],
                "inferred_exit_price_100oz": actual_price,
                "observed_pnl": trade["pnl"],
                "candidate": best,
                "predicted_exit_time": predicted_time,
                "predicted_exit_price_reference": predicted_price,
                "exit_reason": reason,
                "close_time_error_seconds": abs((predicted_time - trade["close_time"]).total_seconds()),
                "exit_price_error": abs(predicted_price - actual_price),
                "win_loss_match": (side * (predicted_price - trade["observed_price"]) > 0) == bool(trade["win"]),
                "evaluation_scope": "initial training period (in-sample parameters)",
            }
        )
    match_table = pd.concat([pd.DataFrame(initial_rows), match_table], ignore_index=True).sort_values("observed_entry_time")
    metrics = {
        "best_candidate": best,
        "best_metrics": summary.iloc[0].to_dict(),
        "inferred_exit_warning": "Exit prices assume entry-price semantics, 100 oz/lot, no fees, and reference M1 bars; they are not broker executions.",
        "m1_timing_limit": "Predicted exit timestamps are minute-end proxies; second-level exit identity is untestable.",
    }
    return results, match_table, metrics


def write_reports(
    inventory: dict[str, Any],
    price_ticket: dict[str, Any],
    round_tests: pd.DataFrame,
    sizing_tests: pd.DataFrame,
    sizing_walk: pd.DataFrame,
    sizing_metrics: dict[str, Any],
    comparison: pd.DataFrame,
    walk: pd.DataFrame,
    entry_metrics: dict[str, Any],
    exit_results: pd.DataFrame,
    exit_metrics: dict[str, Any],
) -> dict[str, str]:
    p100 = price_ticket["median_discrepancy_by_multiplier"].get("100")
    continuity_p = price_ticket.get("entry_vs_exit_hypothesis_wilcoxon_p")
    price_status = (
        "STATISTICALLY SUPPORTED"
        if price_ticket["best_multiplier"] == 100
        and continuity_p is not None
        and continuity_p < 0.05
        else "PLAUSIBLE HYPOTHESIS"
    )
    best_entry = comparison.iloc[0]
    model0 = comparison[comparison["model"].str.startswith("MODEL 0")].iloc[0]
    model1 = comparison[comparison["model"].str.startswith("MODEL 1")].iloc[0]
    model5 = comparison[comparison["model"].str.startswith("MODEL 5")].iloc[0]
    ledger = f"""# Claude evidence ledger and independent checks

## Scope

The pasted Claude brief reports P1–P9b as completed and P10 as interrupted. No Claude scripts or raw P1–P9b output files were present in the current workspace, so the claims below are imported as a research ledger and cross-checked where the preserved files permit. They are not silently treated as primary artifacts.

## Workspace reuse inventory

{markdown_table(pd.DataFrame(inventory["items"]))}

## Imported findings and current disposition

| Finding | Claude result | Independent disposition |
| --- | --- | --- |
| Price/P&L semantics | Price behaves as entry; about 100 oz/lot | **{price_status}**. Under the preregistered adjacent-pair definition here, multiplier 100 median discrepancy is {p100:.3f}; best grid multiplier is {price_ticket['best_multiplier']}. The isolated ticket 36227388 remains incompatible with an exact 2-decimal/no-cost formula. |
| Ticket sequence | No inversions; large 2025-12-29 namespace jump | **DIRECTLY OBSERVED**: {price_ticket['adjacent_ticket_inversions']}/{price_ticket['adjacent_ticket_pairs']} adjacent inversions, Kendall tau {price_ticket['kendall_tau']:.6f}; largest jump {price_ticket['ticket_jump_size']:,.0f} at {pd.Timestamp(price_ticket['ticket_jump_time']).date()}. The single inversion is the preserved leading-zero ticket `00983845`, so the pasted zero-inversion claim is not literally reproduced. |
| Direction | No simple first-order dependence | Retained from verified trade-only analysis: LR p≈0.625 and runs test null. |
| Holding-time asymmetry | Winners held longer | Retained: median 8.27 vs 2.93 minutes; permutation and rank tests strongly reject equal distributions. Mechanism remains unidentified. |
| Round-minute structure | Nominal clustering | Re-tested against eligible M1 bars from the same raw date and hour; see `round_minute_tests.csv`. This is a timing clue, not a proven trigger. |
| Timezone/DST | Unresolved | Retained as **UNIDENTIFIABLE** from current data. UTC+3 is an assumed proxy mapping only. |
| Driftless two-barrier null | Rejected | Valid only as rejection of a stylized null; no exit mechanism follows. |
| Fixed target | Single invariant target unsupported | Retained with the narrower wording “not supported.” |
| Lot size | 22/22 larger-lot rows positive | P10 completed using pre-trade variables. Size is strongly concentrated before/after the ticket boundary, so “conviction sizing” is not identified. |
| Regimes / mixtures | Heterogeneous states | Retained as behavioral heterogeneity, never as a count of algorithms. |

## Independent price-pair definition

Pairs are chronologically adjacent, non-overlapping trades where the next entry is within ten minutes of the previous close (n={price_ticket['price_pair_n']}). The inferred previous exit under each multiplier is compared with the next recorded price. This check is sensitive to market movement during the gap and to the non-broker feed/accounting assumptions; it supports a working interpretation, not an exact accounting identity.
"""

    audit_rows = [
        ("price = entry price", price_status, f"Adjacent-pair test n={price_ticket['price_pair_n']}; 100x median discrepancy {p100:.3f}.", "Exact field metadata and broker deal records absent."),
        ("100-oz multiplier", price_status, f"Best multiplier on tested grid: {price_ticket['best_multiplier']}.", "Grid-limited; one parity anomaly; fees/rounding unknown."),
        ("broker timezone", "UNIDENTIFIABLE", "UTC+3 provides a useful alignment.", "No server metadata or DST rule."),
        ("Dukascopy feed equivalence", "INVALID/OVERSTATED", "External series is bid-only aggregated M1.", "No broker-feed identity evidence."),
        ("round-minute trigger", "PLAUSIBLE HYPOTHESIS", "Same-date/hour permutation detects clustering for some boundaries.", "Clustering does not establish causation or timer logic."),
        ("session filter", "PLAUSIBLE HYPOTHESIS", "Raw-clock concentration and MODEL 0 diagnostics.", "Timezone and opportunity set remain proxy-defined."),
        ("higher-timeframe context", "PLAUSIBLE HYPOTHESIS" if model5['oos_pr_auc_mean'] > model1['oos_pr_auc_mean'] else "UNIDENTIFIABLE", f"MODEL 5 OOS PR AUC {model5['oos_pr_auc_mean']:.5f} vs MODEL 1 {model1['oos_pr_auc_mean']:.5f}.", "Feature association is not source-code identity."),
        ("M1 impulse trigger", "PLAUSIBLE HYPOTHESIS", f"MODEL 1 OOS F1 {model1['oos_f1_mean']:.5f}; recall {model1['oos_recall']:.5f}.", "Prior simple rules fail exact replication."),
        ("EMA 9/20", "INVALID/OVERSTATED", "EMA spread is one correlated feature.", "No replication evidence that source code uses these periods."),
        ("VWAP", "INVALID/OVERSTATED", "VWAP-distance is one proxy feature.", "Vendor volume is a proxy and source-code usage is unproven."),
        ("breakout/liquidity break", "UNIDENTIFIABLE", "Breakout-distance features tested.", "M1 OHLC cannot identify order-flow liquidity events."),
        ("31.9-pip SL", "INVALID/OVERSTATED", "Value is an external-reference path excursion.", "Excursion is not an order level."),
        ("62.8-pip TP", "INVALID/OVERSTATED", "Value is an external-reference path excursion.", "Excursion is not an order level."),
        ("dynamic exit", "PLAUSIBLE HYPOTHESIS", "Winner/loser duration asymmetry is statistically strong.", "Many exit mechanisms generate the same asymmetry."),
        ("sizing based on conviction", "INVALID/OVERSTATED", f"Segment A/B large-lot rates {sizing_metrics['segment_a_large_rate']:.3f}/{sizing_metrics['segment_b_large_rate']:.3f}.", "Regime/namespace change is the leading observed explanation."),
        ("multiple algorithms", "UNIDENTIFIABLE", "Mixtures/HMMs describe heterogeneous states.", "Components do not map to persistent executable rules."),
        ("adaptive regimes", "PLAUSIBLE HYPOTHESIS", "Multiple trade-attribute change points are robust.", "Market regime or infrastructure changes are alternatives."),
        ("exact algorithm identification", "UNIDENTIFIABLE", f"Best OOS model is {entry_metrics['best_model']} with precision {best_entry['oos_precision']:.5f}, recall {best_entry['oos_recall']:.5f}.", "Replication is insufficient and M1 lacks intraminute path/broker execution."),
    ]
    audit_frame = pd.DataFrame(audit_rows, columns=["Claim", "Grade", "Evidence", "Limit"])
    statistical_register = pd.DataFrame(
        [
            ["Entry-price/100x paired continuity", "100x inferred exits are not closer than recorded-price-as-exit", price_ticket["price_pair_n"], "paired Wilcoxon, one-sided", f"median discrepancy={p100:.3f}", price_ticket["entry_vs_exit_hypothesis_wilcoxon_p"], "single prespecified comparison; multiplier grid descriptive", "gap movement and costs"],
            ["Ticket monotonicity", "ticket IDs unrelated to chronological rank", 423, "Kendall tau", f"tau={price_ticket['kendall_tau']:.6f}", price_ticket["kendall_tau_p"], "not part of a searched family", "namespace meaning unknown"],
            ["Round-minute boundaries", "entries exchangeable with eligible same-date/hour M1 bars", 423, "Monte Carlo permutation", "observed minus null shares in CSV", float(round_tests["permutation_p"].min()), "BH across 5/15/30/60-minute family", "raw hour and proxy eligibility"],
            ["Sizing univariates", "pre-trade predictor independent of lot>0.01", 423, "Fisher or Mann-Whitney + permutation", "effect sizes in CSV", float(sizing_tests["family_p"].min()), "BH within declared P10 univariate family", "22 positives; regime concentration"],
            ["Entry models", "pre-entry features do not discriminate entry bars", int(entry_metrics["entry_bars"]), "five expanding chronological folds", f"best PR AUC={best_entry['oos_pr_auc_mean']:.5f}", np.nan, "nine prespecified architectures; no p-value promotion", "extreme imbalance; feed/time proxy"],
            ["Exit candidates", "candidate does not improve time/price matching", 423, "five expanding chronological folds", f"best 5m match={exit_metrics['best_metrics']['close_within_5m_rate']:.4f}", np.nan, "six declared families; descriptive selection", "inferred exit price and M1 timing"],
        ],
        columns=["Test", "Null hypothesis", "Sample size", "Method", "Effect size", "p-value", "Multiple-testing treatment", "Limitations"],
    )
    audit = f"""# Algorithm claim audit

Every headline claim is graded using exactly one allowed label.

{markdown_table(audit_frame)}

## Statistical-test register

{markdown_table(statistical_register)}

P-values quantify compatibility with a stated null under its assumptions. They do not prove a source-code mechanism, broker identity, causality, or uniqueness.
"""

    sizing_report = f"""# Pre-trade sizing-state analysis (Claude P10 completion)

## Result

The large-lot indicator (`lot_size > 0.01`) occurs {sizing_metrics['large_lot_n']} times and all {sizing_metrics['large_lot_wins']} have positive reported result. The simple plug-in IID probability is {sizing_metrics['simple_iid_all_win_probability']:.4f}; using separate observed win fractions within the two ticket segments gives {sizing_metrics['segment_adjusted_all_win_probability']:.4f}. Neither is a valid identification test after exploratory selection, estimated base rates, dependence and regime concentration.

The strongest observed explanation is temporal/operational regime: the large-lot rate is {sizing_metrics['segment_a_large_rate']:.2%} before the ticket namespace jump and {sizing_metrics['segment_b_large_rate']:.2%} after it (Fisher p={sizing_metrics['segment_fisher_p']:.3g}). This supports a sizing regime change; it does not establish discretionary conviction, signal strength, or a second EA.

There are {sizing_metrics['adjacent_large_pairs']} adjacent large-lot pairs versus a shuffled mean of {sizing_metrics['adjacent_large_null_mean']:.2f} (permutation p={sizing_metrics['adjacent_large_permutation_p']:.4f}). Spearman correlation between lot size and cumulative reported result available before the trade is {sizing_metrics['lot_vs_cumulative_pnl_pre_spearman']:+.3f} (p={sizing_metrics['lot_vs_cumulative_pnl_pre_p']:.4f}); cumulative closed result is not account equity.

All predictors below are available before the current trade. Market variables use the prior completed M1 bar; cumulative result excludes the current row.

## Registered univariate tests

{markdown_table(sizing_tests[["predictor", "test", "n", "large_lot_n", "effect", "effect_label", "odds_ratio", "family_p", "bh_q"]])}

## Chronological sparse-logistic validation

{markdown_table(sizing_walk)}

Mean walk-forward ROC AUC is {sizing_metrics['walk_forward_mean_auc']:.3f}; mean PR AUC is {sizing_metrics['walk_forward_mean_pr_auc']:.3f}. Folds with no large-lot test rows cannot identify predictive discrimination. The model is diagnostic, not a deployable sizing rule.
"""

    entry_report = f"""# Entry reconstruction and negative-space analysis

## Leakage control and data granularity

The candidate panel uses the existing Dukascopy bid-only aggregated M1 proxy. Every M1 market feature is shifted one complete bar. M5/M15/H1 values are joined only when their bar has completed. Trade outcome, close time, P&L, MFE and MAE are excluded from entry predictors. Five expanding chronological folds begin after the first 35% of elapsed history.

Because entries contain seconds but the reference data are M1 OHLC, the analysis cannot distinguish bar open, first tick after close, intrabar threshold crossing or an N-second timer. Exact-second match rates are therefore diagnostic limits, not model failures alone.

## Candidate architectures

{markdown_table(comparison)}

The strongest OOS architecture by the prespecified F1/PR ordering is **{entry_metrics['best_model']}**. It produces OOS precision {best_entry['oos_precision']:.5f}, recall {best_entry['oos_recall']:.5f}, mean F1 {best_entry['oos_f1_mean']:.5f}, mean ROC AUC {best_entry['oos_roc_auc_mean']:.3f}, and mean PR AUC {best_entry['oos_pr_auc_mean']:.5f}. These values do not approach event-level replication of the 423 trades.

Time-only MODEL 0 has mean OOS PR AUC {model0['oos_pr_auc_mean']:.5f}. M1 expansion MODEL 1 has {model1['oos_pr_auc_mean']:.5f}; completed HTF context MODEL 5 has {model5['oos_pr_auc_mean']:.5f}. Incremental differences are clues, not proof that the source contains those indicators.

## Negative space

`near_miss_events.csv` supplies up to three same-day, ±120-minute non-entry bars nearest to each observed entry in lagged expansion, volatility, velocity, EMA-spread, VWAP-distance and clock space. The persistence of close near-misses confirms the central unresolved question: the available M1 state does not explain why the account selected these specific bars and rejected many similar bars.

## Current entry conclusion

No tested architecture reproduces enough exact events to identify the source algorithm. Body/volatility, clock, trend/location and HTF variables remain a **partial market fingerprint**, not an executable reconstruction.
"""

    exit_summary = exit_results.groupby("candidate", as_index=False).agg(
        median_time_error=("median_abs_close_time_error_seconds", "median"),
        median_price_error=("median_abs_exit_price_error", "median"),
        within_5m=("close_within_5m_rate", "mean"),
        outcome_match=("win_loss_match_rate", "mean"),
    )
    exit_report = f"""# Exit reconstruction

## Method and hard limitation

Entry-price semantics and a 100-oz multiplier are used only as a working approximation to infer an exit price from P&L. Broker-side rounding, fees, spreads and the 0.03-lot parity anomaly prevent treating this as exact. Candidate paths use the non-broker bid-only M1 proxy, so predicted timestamps are minute-end approximations and prices are reference values.

Six exit families were evaluated in five expanding chronological folds: median time, fixed price barriers, ATR-scaled barriers, EMA9 failure, VWAP failure and short-term momentum failure. Barrier parameters are learned from prior trades only.

{markdown_table(exit_summary)}

The best time-match candidate under the declared ordering is **{exit_metrics['best_candidate']}**, with mean five-minute close match {exit_metrics['best_metrics']['close_within_5m_rate']:.2%} and median absolute time error {exit_metrics['best_metrics']['median_abs_close_time_error_seconds']:.0f} seconds. This is insufficient to identify the original exit mechanism.

Observed winner/loser holding asymmetry still supports different favorable/adverse management behavior. It does not distinguish a stop, target, trailing, reversal, momentum-failure, bar-close or hybrid state machine.
"""

    strong = (
        best_entry["oos_recall"] >= 0.50
        and best_entry["oos_precision"] >= 0.10
        and exit_metrics["best_metrics"]["close_within_5m_rate"] >= 0.50
    )
    status = "LEVEL C — PLAUSIBLE STRUCTURAL HYPOTHESIS" if strong else "LEVEL D — UNIDENTIFIED"
    status_report = f"""# Algorithm identification status

## {status}

The actual original algorithm has **not** been identified. The strongest tested entry architecture is `{entry_metrics['best_model']}`, but its OOS event precision is {best_entry['oos_precision']:.5f}, recall is {best_entry['oos_recall']:.5f}, and mean one-M1-bar match rate is {best_entry['oos_entry_match_one_m1_bar_mean']:.3f}. The best declared exit family matches closes within five minutes at {exit_metrics['best_metrics']['close_within_5m_rate']:.2%}. This is not sufficient for Level B or Level A.

## Directly known

The file contains 423 XAUUSD.f closed intervals, 214 Buy and 209 Sell, mostly 0.01 size, with strong outcome-conditioned holding-time asymmetry and an operational ticket/size discontinuity. The copied raw file is unchanged.

## What the Claude ledger adds

It supplies independently developed hypotheses and checks for price semantics, ticket chronology, timing boundaries, payoff nulls, sizing, and behavioral regimes. Independent checks here support the entry-price/approximately-100-oz working interpretation and ticket discontinuity, while retaining the stated accounting caveat.

## What the external-market work adds

It permits pre-entry market-state and negative-space comparison. M1 impulse/expansion, clock, trend/location and completed HTF state have measurable associations, but none of the nine architectures replicates the event stream out of sample.

## Claims that do not survive

Dukascopy broker-feed equivalence, a proven UTC+3 broker timezone, exact EMA/VWAP source rules, a definitive breakout/liquidity algorithm, 31.9-pip SL, 62.8-pip TP, conviction sizing, and a specific number of algorithms are unsupported or overstated.

## Strongest current structural hypothesis

A timing/state gate followed by expansion/impulse and market-location filtering, with quicker adverse-trade handling and longer favorable-trade management. This is a hypothesis class, not the source algorithm.

## Historical and OOS match

The strongest candidate emits {int(best_entry['historical_candidate_signals'])} historical signals and matches {int(best_entry['historical_matched_entry_bars'])} entry bars in-sample (recall {best_entry['historical_recall']:.3f}). In chronological OOS evaluation it records TP={int(best_entry['oos_tp'])}, FP={int(best_entry['oos_fp'])}, FN={int(best_entry['oos_fn'])}, precision {best_entry['oos_precision']:.5f}, and recall {best_entry['oos_recall']:.5f}.

## Remaining identification barriers

Broker-specific bid/ask ticks, exact server timezone, actual exit prices, order/deal/position linkage, stops/targets and modifications, costs, rejected/cancelled orders, account state, EA identifiers and the true opportunity set remain absent. M1 bars cannot resolve second-level intrabar triggers. The present result is a statistical approximation and falsification exercise, not source-code recovery.
"""
    files = {
        "claude_evidence_ledger.md": ledger,
        "algorithm_claim_audit.md": audit,
        "sizing_state_analysis.md": sizing_report,
        "entry_reconstruction.md": entry_report,
        "exit_reconstruction.md": exit_report,
        "algorithm_identification_status.md": status_report,
    }
    for name, content in files.items():
        (OUT / name).write_text(content, encoding="utf-8")
    return files


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)
    trades, _ = load_trades(ROOT / "data" / "raw" / "trades_raw.tsv")
    bars = pd.read_csv(ROOT / "data" / "market" / "normalized" / "xauusd_m1.csv")
    bars["timestamp"] = pd.to_datetime(bars["timestamp"])
    bars = bars.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)

    inventory = {
        "items": [
            {"Artifact": "Raw trades", "Present": True, "Reuse": "data/raw/trades_raw.tsv; 423 preserved rows"},
            {"Artifact": "Processed trades", "Present": (ROOT / "data/processed/trades_enriched.csv").exists(), "Reuse": "existing trade-only outputs retained"},
            {"Artifact": "Claude scripts/results", "Present": False, "Reuse": "pasted P1–P9b claims imported as ledger; P10 newly completed"},
            {"Artifact": "External XAUUSD", "Present": True, "Reuse": f"{len(bars):,} Dukascopy bid M1 proxy rows"},
            {"Artifact": "M1 entry features", "Present": (TABLES / "entry_states.csv").exists(), "Reuse": "prior aligned table retained; new leakage-safe full panel built"},
            {"Artifact": "M5/M15/H1 tables", "Present": False, "Reuse": "new completed-bar features generated"},
            {"Artifact": "No-trade panel", "Present": True, "Reuse": "prior in-memory pipeline concept rebuilt and persisted with lagged features"},
            {"Artifact": "Rule sweep/tree/OOS", "Present": True, "Reuse": "prior failed OOS result retained as baseline"},
            {"Artifact": "MFE/MAE", "Present": True, "Reuse": "retained as external-reference excursions only"},
            {"Artifact": "Reports/charts", "Present": True, "Reuse": "existing reports preserved; required continuation reports added"},
        ]
    }
    price_ticket = price_and_ticket_audit(trades)
    panel = build_event_panel(bars, trades)
    round_tests = round_minute_audit(trades, panel)
    sizing_tests, sizing_walk, sizing_metrics = sizing_analysis(trades, panel, price_ticket)
    comparison, walk, entry_match, near_misses, entry_metrics = entry_reconstruction(panel, trades)
    exit_results, exit_match, exit_metrics = exit_reconstruction(trades, bars, panel)

    # Required and supporting machine-readable artifacts.
    comparison.to_csv(OUT / "candidate_rule_comparison.csv", index=False)
    walk.to_csv(OUT / "walk_forward_results.csv", index=False)
    entry_match.to_csv(OUT / "entry_match_table.csv", index=False)
    exit_match.to_csv(OUT / "exit_match_table.csv", index=False)
    near_misses.to_csv(OUT / "near_miss_events.csv", index=False)
    round_tests.to_csv(OUT / "round_minute_tests.csv", index=False)
    sizing_tests.to_csv(OUT / "sizing_univariate_tests.csv", index=False)
    sizing_walk.to_csv(OUT / "sizing_walk_forward.csv", index=False)
    exit_results.to_csv(OUT / "exit_walk_forward_results.csv", index=False)
    # Complete event table; compressed to preserve all eligible M1 rows and multiscale states.
    panel.to_csv(OUT / "candidate_event_table.csv.gz", index=False, compression="gzip", float_format="%.8g")

    reports = write_reports(
        inventory, price_ticket, round_tests, sizing_tests, sizing_walk, sizing_metrics,
        comparison, walk, entry_metrics, exit_results, exit_metrics,
    )
    metrics = {
        "inventory": inventory,
        "price_ticket_audit": price_ticket,
        "round_minute_tests": round_tests.to_dict(orient="records"),
        "sizing": sizing_metrics,
        "entry": entry_metrics,
        "exit": exit_metrics,
        "required_reports": list(reports),
        "candidate_event_rows": len(panel),
        "candidate_event_columns": list(panel.columns),
        "random_seed": SEED,
    }
    (OUT / "continuation_metrics.json").write_text(
        json.dumps(metrics, indent=2, default=jsonable), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "candidate_event_rows": len(panel),
                "entry_model": entry_metrics["best_model"],
                "entry_oos": entry_metrics["best_oos"],
                "exit_candidate": exit_metrics["best_candidate"],
                "reports": list(reports),
            },
            indent=2,
            default=jsonable,
        )
    )


def regenerate_reports() -> None:
    """Refresh prose reports from persisted results without refitting models."""
    metrics = json.loads((OUT / "continuation_metrics.json").read_text(encoding="utf-8"))
    walk = pd.read_csv(OUT / "walk_forward_results.csv")
    comparison = pd.read_csv(OUT / "candidate_rule_comparison.csv")
    for seconds in [1, 5, 15, 30, 60]:
        means = walk.groupby("model")[f"entry_match_{seconds}s"].mean()
        comparison[f"oos_entry_match_{seconds}s_mean"] = comparison["model"].map(means)
    comparison.to_csv(OUT / "candidate_rule_comparison.csv", index=False)
    entry_match = pd.read_csv(OUT / "entry_match_table.csv")
    error = pd.to_numeric(entry_match["entry_error_seconds"], errors="coerce")
    for seconds in [1, 5, 15, 30, 60]:
        entry_match[f"entry_match_within_{seconds}s"] = error.le(seconds).fillna(False)
    entry_match["entry_match_within_one_m1_bar"] = error.lt(120).fillna(False)
    entry_match.to_csv(OUT / "entry_match_table.csv", index=False)
    write_reports(
        metrics["inventory"],
        metrics["price_ticket_audit"],
        pd.read_csv(OUT / "round_minute_tests.csv"),
        pd.read_csv(OUT / "sizing_univariate_tests.csv"),
        pd.read_csv(OUT / "sizing_walk_forward.csv"),
        metrics["sizing"],
        comparison,
        walk,
        metrics["entry"],
        pd.read_csv(OUT / "exit_walk_forward_results.csv"),
        metrics["exit"],
    )
    print(json.dumps({"status": "ok", "mode": "reports-only"}, indent=2))


if __name__ == "__main__":
    regenerate_reports() if "--reports-only" in sys.argv else main()
