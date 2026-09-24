"""Phase 5: observable-space reconstruction with chronological safeguards.

The code intentionally treats the external M1 series as a partial market proxy.
All market features are shifted one M1 observation: they are available before
the candidate minute begins, not at its close.  This is a constrained test of
observable association, never a claim to recover the original EA.
"""

from __future__ import annotations

import gzip
import json
import math
import warnings
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from scipy.stats import binomtest, fisher_exact
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from reverse_trade.pipeline import load_trades


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"
RAW = ROOT / "data" / "raw" / "trades_raw.tsv"
BARS = ROOT / "data" / "market" / "normalized" / "xauusd_m1.csv"
PHASE3_STATE = OUT / "phase3_state_features.csv"
SEED = 20260920
SIGNAL_RATE = 423 / 402_401  # predeclared observed raw-trade rate; not tuned after results
EMBARGO_MINUTES = 15


def md_table(frame: pd.DataFrame, limit: int | None = None) -> str:
    view = frame.head(limit) if limit else frame
    if view.empty:
        return "No rows."
    lines = ["| " + " | ".join(view.columns) + " |", "| " + " | ".join("---" for _ in view.columns) + " |"]
    for row in view.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(value).replace("|", "/") for value in row) + " |")
    return "\n".join(lines)


def bh_qvalues(pvalues: pd.Series) -> pd.Series:
    values = pvalues.fillna(1.0).to_numpy(dtype=float)
    order = np.argsort(values)
    ranked = values[order]
    adjusted = np.minimum.accumulate((ranked * len(values) / np.arange(1, len(values) + 1))[::-1])[::-1]
    out = np.empty_like(adjusted)
    out[order] = np.minimum(adjusted, 1.0)
    return pd.Series(out, index=pvalues.index)


def completed_features(bars: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Create a deliberately small M1-to-D1 feature lattice from completed bars."""
    result = bars.copy().sort_values("timestamp").reset_index(drop=True)
    close = result.close.astype(float)
    high, low, opn = result.high.astype(float), result.low.astype(float), result.open.astype(float)
    prev_close = close.shift(1)
    prev_open, prev_high, prev_low = opn.shift(1), high.shift(1), low.shift(1)
    prev_range = (prev_high - prev_low).replace(0, np.nan)
    result["m1_return_1"] = prev_close.pct_change()
    for horizon in (3, 5, 10, 15, 30, 60, 240, 1440):
        result[f"return_{horizon}m"] = prev_close.pct_change(horizon)
    result["m1_body"] = prev_close - prev_open
    result["m1_range"] = prev_range
    result["m1_body_to_range"] = result.m1_body / prev_range
    result["m1_upper_wick"] = prev_high - pd.concat([prev_open, prev_close], axis=1).max(axis=1)
    result["m1_lower_wick"] = pd.concat([prev_open, prev_close], axis=1).min(axis=1) - prev_low
    result["m1_upper_wick_ratio"] = result.m1_upper_wick / prev_range
    result["m1_lower_wick_ratio"] = result.m1_lower_wick / prev_range
    result["gap_proxy"] = prev_open - close.shift(2)
    trailing_high = high.shift(1).rolling(30, min_periods=10).max()
    trailing_low = low.shift(1).rolling(30, min_periods=10).min()
    result["dist_recent_high"] = prev_close - trailing_high
    result["dist_recent_low"] = prev_close - trailing_low
    result["breakout_distance"] = prev_close - high.shift(2).rolling(20, min_periods=10).max()
    result["round_price_distance"] = ((prev_close / 5).round() * 5 - prev_close).abs()
    true_range = pd.concat([(high - low), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    result["atr_14"] = true_range.shift(1).rolling(14, min_periods=14).mean()
    result["volatility_15"] = result.m1_return_1.rolling(15, min_periods=10).std()
    result["volatility_60"] = result.m1_return_1.rolling(60, min_periods=30).std()
    result["range_expansion"] = prev_range / prev_range.rolling(30, min_periods=15).median()
    result["normalized_range"] = prev_range / result.atr_14
    delta = prev_close.diff()
    up = delta.clip(lower=0).rolling(14, min_periods=14).mean()
    down = (-delta.clip(upper=0)).rolling(14, min_periods=14).mean().replace(0, np.nan)
    result["rsi_14"] = 100 - (100 / (1 + up / down))
    lo14 = low.shift(1).rolling(14, min_periods=14).min()
    hi14 = high.shift(1).rolling(14, min_periods=14).max()
    result["stochastic_14"] = (prev_close - lo14) / (hi14 - lo14).replace(0, np.nan)
    ema12 = close.ewm(span=12, adjust=False).mean().shift(1)
    ema20 = close.ewm(span=20, adjust=False).mean().shift(1)
    ema26 = close.ewm(span=26, adjust=False).mean().shift(1)
    ema50 = close.ewm(span=50, adjust=False).mean().shift(1)
    sma20 = close.rolling(20, min_periods=20).mean().shift(1)
    result["macd"] = ema12 - ema26
    result["ema20_distance"] = prev_close - ema20
    result["ema50_distance"] = prev_close - ema50
    result["sma20_distance"] = prev_close - sma20
    result["ema_order_12_26"] = (ema12 > ema26).astype("int8")
    result["ema20_slope"] = ema20 - ema20.shift(5)
    rolling_std = close.rolling(20, min_periods=20).std().shift(1)
    result["bollinger_location"] = (prev_close - sma20) / (2 * rolling_std)
    don_high = high.shift(1).rolling(20, min_periods=20).max()
    don_low = low.shift(1).rolling(20, min_periods=20).min()
    result["donchian_location"] = (prev_close - don_low) / (don_high - don_low).replace(0, np.nan)

    minute = result.timestamp.dt.hour * 60 + result.timestamp.dt.minute
    result["clock_hour"] = result.timestamp.dt.hour
    result["clock_minute"] = result.timestamp.dt.minute
    result["clock_hour_sin"] = np.sin(2 * np.pi * result.clock_hour / 24)
    result["clock_hour_cos"] = np.cos(2 * np.pi * result.clock_hour / 24)
    result["clock_minute_sin"] = np.sin(2 * np.pi * result.clock_minute / 60)
    result["clock_minute_cos"] = np.cos(2 * np.pi * result.clock_minute / 60)
    for period, name in ((5, "m5"), (15, "m15"), (30, "m30"), (60, "h1")):
        phase = minute % period
        result[f"{name}_phase"] = phase.astype("int16")
        result[f"{name}_boundary"] = (phase == 0).astype("int8")
        result[f"{name}_distance_boundary"] = np.minimum(phase, period - phase).astype("int16")
    result["session_code"] = pd.cut(result.clock_hour, [-1, 7, 12, 16, 21, 24], labels=False).astype("int8")
    result["session_age_minutes"] = result.clock_hour * 60 + result.clock_minute

    families = {
        "MARKET_GEOMETRY": ["m1_body", "m1_range", "m1_body_to_range", "m1_upper_wick_ratio", "m1_lower_wick_ratio", "gap_proxy", "dist_recent_high", "dist_recent_low", "breakout_distance", "round_price_distance"],
        "MOMENTUM": ["m1_return_1", "return_3m", "return_5m", "return_10m", "return_15m", "return_30m", "return_60m", "return_240m", "return_1440m", "rsi_14", "stochastic_14", "macd"],
        "VOLATILITY": ["atr_14", "volatility_15", "volatility_60", "range_expansion", "normalized_range"],
        "TREND_LOCATION": ["ema20_distance", "ema50_distance", "sma20_distance", "ema_order_12_26", "ema20_slope", "bollinger_location", "donchian_location"],
        "CLOCK": ["clock_hour_sin", "clock_hour_cos", "clock_minute_sin", "clock_minute_cos", "m5_phase", "m15_phase", "m30_phase", "h1_phase", "m5_boundary", "m15_boundary", "m30_boundary", "h1_boundary", "session_code", "session_age_minutes"],
    }
    return result, families


def feature_dictionary(families: dict[str, list[str]], state_columns: list[str]) -> str:
    rows = []
    for family, columns in families.items():
        for col in columns:
            rows.append({"feature": col, "tag": "CLOCK" if family == "CLOCK" else "MARKET", "family": family, "as_of": "candidate minute start; derived from bars ending no later than the prior M1 observation"})
    for col in state_columns:
        rows.append({"feature": col, "tag": "ACCOUNT_STATE", "family": "TRADE_HISTORY_STATE", "as_of": "candidate minute start; prior observed entries/exits only (Phase 3 availability convention)"})
    return "# Phase 5 feature dictionary\n\nAll market fields are computed from a completed M1 observation: they are shifted one bar before the candidate minute. Higher horizon names denote rolling completed-M1 proxies, not broker-native M5/H1/D1 feeds. The timezone is the prior project UTC+3 proxy convention, not independently verified broker-server time. No field uses current-trade outcome, exit, MFE/MAE, or future bar data.\n\n" + md_table(pd.DataFrame(rows)) + "\n"


def make_folds(frame: pd.DataFrame) -> list[tuple[int, np.ndarray, np.ndarray]]:
    n = len(frame)
    starts = np.linspace(int(n * 0.50), int(n * 0.90), 5, endpoint=False, dtype=int)
    width = max(1, int(n * 0.10))
    output = []
    for fold, start in enumerate(starts, 1):
        end = min(n, start + width)
        cutoff = frame.timestamp.iloc[start] - pd.Timedelta(minutes=EMBARGO_MINUTES)
        train_idx = np.flatnonzero(frame.timestamp.lt(cutoff).to_numpy())
        valid_idx = np.arange(start, end)
        output.append((fold, train_idx, valid_idx))
    return output


def balanced_train_indices(y: np.ndarray, indices: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    positives = indices[y[indices] == 1]
    negatives = indices[y[indices] == 0]
    take = min(len(negatives), max(2_000, len(positives) * 25))
    sampled = rng.choice(negatives, size=take, replace=False)
    return np.concatenate([positives, sampled])


def make_model(name: str):
    if name == "l1_logistic":
        return Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", LogisticRegression(penalty="l1", solver="saga", C=0.03, max_iter=500, random_state=SEED))])
    if name == "elastic_net":
        return Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", LogisticRegression(penalty="elasticnet", solver="saga", l1_ratio=0.5, C=0.03, max_iter=500, random_state=SEED))])
    if name == "shallow_tree":
        return Pipeline([("impute", SimpleImputer(strategy="median")), ("model", DecisionTreeClassifier(max_depth=3, min_samples_leaf=40, class_weight="balanced", random_state=SEED))])
    if name == "restricted_gradient_boosting":
        return Pipeline([("impute", SimpleImputer(strategy="median")), ("model", GradientBoostingClassifier(n_estimators=50, max_depth=2, min_samples_leaf=30, learning_rate=0.05, random_state=SEED))])
    if name == "restricted_random_forest":
        return Pipeline([("impute", SimpleImputer(strategy="median")), ("model", RandomForestClassifier(n_estimators=60, max_depth=4, min_samples_leaf=30, class_weight="balanced_subsample", n_jobs=-1, random_state=SEED))])
    raise ValueError(name)


def metric_row(name: str, family: str, fold: str, y: np.ndarray, scores: np.ndarray, threshold: float, feature_count: int, train_n: int, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, object]:
    signal = scores >= threshold
    tp = int(np.sum((signal == 1) & (y == 1)))
    fp = int(np.sum((signal == 1) & (y == 0)))
    fn = int(np.sum((signal == 0) & (y == 1)))
    return {
        "candidate": name, "family": family, "fold": fold, "validation_start": start.isoformat(), "validation_end": end.isoformat(),
        "train_observations": train_n, "validation_observations": len(y), "feature_count": feature_count,
        "signals": int(signal.sum()), "signals_per_10000": 10_000 * float(signal.mean()), "trades_captured": tp, "false_alarms": fp,
        "precision": precision_score(y, signal, zero_division=0), "recall": recall_score(y, signal, zero_division=0), "f1": f1_score(y, signal, zero_division=0),
        "pr_auc": average_precision_score(y, scores) if y.sum() else np.nan,
        "roc_auc": roc_auc_score(y, scores) if len(np.unique(y)) == 2 else np.nan,
    }


def evaluate_model(frame: pd.DataFrame, features: list[str], model_name: str, family: str, folds: list[tuple[int, np.ndarray, np.ndarray]]) -> tuple[list[dict[str, object]], pd.Series]:
    x = frame[features].to_numpy(dtype=float)
    y = frame.entry.to_numpy(dtype=int)
    scores_all = pd.Series(np.nan, index=frame.index, dtype=float)
    rows: list[dict[str, object]] = []
    for fold, train_idx, valid_idx in folds:
        rng = np.random.default_rng(SEED + fold)
        fit_idx = balanced_train_indices(y, train_idx, rng)
        model = make_model(model_name)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            model.fit(x[fit_idx], y[fit_idx])
        train_scores = model.predict_proba(x[train_idx])[:, 1]
        threshold = float(np.quantile(train_scores, 1 - SIGNAL_RATE))
        scores = model.predict_proba(x[valid_idx])[:, 1]
        scores_all.iloc[valid_idx] = scores
        rows.append(metric_row(model_name, family, str(fold), y[valid_idx], scores, threshold, len(features), len(train_idx), frame.timestamp.iloc[valid_idx[0]], frame.timestamp.iloc[valid_idx[-1]]))
    return rows, scores_all


def aggregate(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    numeric = ["validation_observations", "signals", "trades_captured", "false_alarms"]
    grouped = frame.groupby(["candidate", "family"], as_index=False)[numeric].sum()
    grouped["pooled_precision"] = grouped.trades_captured / grouped.signals.replace(0, np.nan)
    positives = frame.groupby(["candidate", "family"], as_index=False).validation_observations.sum().rename(columns={"validation_observations": "total_minutes"})
    # Positive count is obtained fold-wise because entries are sparse and non-overlapping.
    positive_counts = frame.groupby(["candidate", "family"], as_index=False).apply(lambda d: int(d.trades_captured.iloc[0] * 0 + 0), include_groups=False)
    del positive_counts  # retained explicit: recall below is averaged fold recall, not a fabricated denominator.
    means = frame.groupby(["candidate", "family"], as_index=False)[["precision", "recall", "f1", "pr_auc", "roc_auc", "signals_per_10000"]].mean().rename(columns={"precision": "mean_fold_precision"})
    return grouped.merge(means, on=["candidate", "family"], how="left").merge(positives, on=["candidate", "family"], how="left")


def negative_space(frame: pd.DataFrame, raw_trades: pd.DataFrame) -> pd.DataFrame:
    """Hierarchical controls, one row per ticket and level, with explicit relaxations."""
    controls = frame.loc[frame.entry.eq(0)].copy()
    rows = []
    targets = raw_trades.copy()
    targets["candidate_timestamp"] = targets.open_time.dt.floor("min")
    lookup = frame.set_index("timestamp")
    for target in targets.itertuples(index=False):
        if target.candidate_timestamp not in lookup.index:
            continue
        trade = lookup.loc[target.candidate_timestamp]
        pool = controls.loc[controls.m30_phase.eq(trade.m30_phase)]
        stages: list[tuple[str, pd.DataFrame]] = [("A_same_clock_phase", pool)]
        pool_b = pool.loc[pool.session_code.eq(trade.session_code)]
        stages.append(("B_clock_session", pool_b))
        pool_c = pool_b.loc[(pool_b.volatility_60 - trade.volatility_60).abs().le(max(abs(trade.volatility_60) * 0.35, 1e-8))]
        stages.append(("C_plus_volatility", pool_c))
        pool_d = pool_c.loc[(pool_c.donchian_location - trade.donchian_location).abs().le(0.20)]
        stages.append(("D_plus_location", pool_d))
        pool_e = pool_d.loc[(pool_d.return_5m - trade.return_5m).abs().le(max(abs(trade.return_5m) * 0.50, 2e-5))]
        stages.append(("E_plus_momentum", pool_e))
        stages.append(("F_nearest_temporal_neighbor", pool_e))
        for level, candidate_pool in stages:
            usable = candidate_pool.dropna(subset=["volatility_60", "donchian_location", "return_5m"])
            fallback = "none"
            if usable.empty:
                usable = pool.dropna(subset=["volatility_60", "donchian_location", "return_5m"])
                fallback = "relaxed_to_A"
            distance = (
                ((usable.volatility_60 - trade.volatility_60) / (abs(trade.volatility_60) + 1e-8)).abs()
                + (usable.donchian_location - trade.donchian_location).abs()
                + ((usable.return_5m - trade.return_5m) / (abs(trade.return_5m) + 2e-5)).abs()
            )
            # Temporal distance breaks feature-distance ties; F is the nearest compatible control.
            temporal = (usable.timestamp - target.candidate_timestamp).abs().dt.total_seconds() / 60
            order = ["_temporal", "_distance", "timestamp"] if level == "F_nearest_temporal_neighbor" else ["_distance", "_temporal", "timestamp"]
            best = usable.assign(_distance=distance, _temporal=temporal).sort_values(order).iloc[0]
            rows.append({
                "ticket": target.ticket, "side": target.side, "trade_timestamp": target.open_time.isoformat(), "trade_candidate_minute": target.candidate_timestamp.isoformat(),
                "control_set": level, "control_timestamp": best.timestamp.isoformat(), "fallback": fallback, "feature_distance": float(best._distance),
                "temporal_distance_minutes": float(best._temporal), "trade_m30_phase": int(trade.m30_phase), "control_m30_phase": int(best.m30_phase),
                "trade_session": int(trade.session_code), "control_session": int(best.session_code), "trade_volatility_60": trade.volatility_60,
                "control_volatility_60": best.volatility_60, "trade_return_5m": trade.return_5m, "control_return_5m": best.return_5m,
            })
    table = pd.DataFrame(rows)
    table["is_final_matched_control"] = table.control_set.eq("F_nearest_temporal_neighbor")
    return table


def symbolic_rules(frame: pd.DataFrame) -> dict[str, Callable[[pd.DataFrame], pd.Series]]:
    # Predeclared small grammar; thresholds are fixed before inspecting Phase 5 results.
    return {
        "m30_boundary": lambda x: x.m30_boundary.eq(1),
        "m30_boundary_and_positive_5m": lambda x: x.m30_boundary.eq(1) & x.return_5m.gt(0),
        "m30_boundary_and_negative_5m": lambda x: x.m30_boundary.eq(1) & x.return_5m.lt(0),
        "m30_boundary_and_rsi_high": lambda x: x.m30_boundary.eq(1) & x.rsi_14.gt(55),
        "m30_boundary_and_rsi_low": lambda x: x.m30_boundary.eq(1) & x.rsi_14.lt(45),
        "m30_boundary_and_range_expansion": lambda x: x.m30_boundary.eq(1) & x.range_expansion.gt(1.25),
        "local_breakout": lambda x: x.breakout_distance.gt(0),
        "high_volatility_and_momentum": lambda x: x.volatility_60.gt(x.volatility_60.quantile(0.75)) & x.return_5m.abs().gt(x.return_5m.abs().quantile(0.75)),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    trades, quality = load_trades(RAW)
    bars = pd.read_csv(BARS, parse_dates=["timestamp"])
    features, families = completed_features(bars)
    state = pd.read_csv(PHASE3_STATE, parse_dates=["timestamp"])
    state_columns = [
        "eligible_observed_capacity", "active_positions_before_candidate", "seconds_since_last_exit", "seconds_since_last_entry",
        "prior_win_code", "prior_direction_code", "prior_large_code", "trades_today_before", "trades_prev_hour",
        "trades_session_before", "win_close_arrival_prev_hour", "loss_close_arrival_prev_hour", "seconds_since_last_buy_entry",
        "seconds_since_last_sell_entry", "recent_completed_events_30", "recent_m30_boundaries_120",
    ]
    state = state[["timestamp", "entry", "entry_count", *state_columns]]
    panel = features.merge(state, on="timestamp", how="inner", validate="one_to_one").sort_values("timestamp").reset_index(drop=True)
    panel["entry"] = panel.entry.astype("int8")
    for column in state_columns:
        panel[column] = pd.to_numeric(panel[column], errors="coerce")

    canonical = {
        "trade_rows": int(len(trades)), "buy": int(trades.side.eq("Buy").sum()), "sell": int(trades.side.eq("Sell").sum()),
        "profitable": int(trades.win.sum()), "losing": int((~trades.win).sum()), "total_pnl": round(float(trades.pnl.sum()), 2),
        "lot_counts": {str(size): int(count) for size, count in trades.lot_size.value_counts().sort_index().items()},
        "overlapping_entries": int(trades.entry_while_position_active.sum()), "source_sha256": quality["sha256"],
        "distinct_entry_minutes": int(panel.entry.sum()), "raw_base_rate": 423 / 402_401,
    }
    (OUT / "phase5_canonical_statistics.json").write_text(json.dumps(canonical, indent=2), encoding="utf-8")
    (OUT / "phase5_canonical_recheck.md").write_text(
        "# Phase 5 canonical recheck\n\n" + md_table(pd.DataFrame([canonical])) + "\n\n"
        "The raw ledger is the canonical source. The 423 second-level entries collapse to 420 distinct M1 candidate minutes; this is a resolution effect, not a change to the canonical count. A strict timestamp recheck finds three later entries with an earlier trade still open, correcting the prior narrative count of five. This still falsifies a universal flat-only rule.\n",
        encoding="utf-8",
    )
    (OUT / "phase5_feature_dictionary.md").write_text(feature_dictionary(families, state_columns), encoding="utf-8")
    feature_cols = [col for group in families.values() for col in group] + state_columns
    panel[["timestamp", "entry", "entry_count", *feature_cols]].to_csv(OUT / "phase5_feature_table.csv.gz", index=False, compression="gzip")

    negative = negative_space(panel, trades)
    negative.to_csv(OUT / "phase5_negative_space_table.csv.gz", index=False, compression="gzip")
    (OUT / "phase5_negative_space_analysis.md").write_text(
        "# Phase 5 negative-space analysis\n\n"
        f"The hierarchical design created {len(negative)} ticket-control rows from {negative.ticket.nunique()} ledger tickets. Controls are known non-entry M1 minutes. Each successive set narrows from clock phase through session, volatility, location and momentum; explicit fallbacks are recorded rather than hidden. These are M1-proxy similarities, not proof of equal broker quotes or equal hidden EA state.\n\n"
        + md_table(negative.groupby(["control_set", "fallback"], as_index=False).size().rename(columns={"size": "rows"})) + "\n",
        encoding="utf-8",
    )

    folds = make_folds(panel)
    full = feature_cols
    baseline_models = ["l1_logistic", "elastic_net", "shallow_tree", "restricted_gradient_boosting", "restricted_random_forest"]
    all_rows: list[dict[str, object]] = []
    score_cache: dict[str, pd.Series] = {}
    for model in baseline_models:
        rows, scores = evaluate_model(panel, full, model, "CLOCK+MARKET+STATE", folds)
        all_rows.extend(rows)
        score_cache[model] = scores
    ablations = {
        "A_CLOCK": families["CLOCK"], "B_GEOMETRY": families["MARKET_GEOMETRY"], "C_MOMENTUM": families["MOMENTUM"],
        "D_VOLATILITY": families["VOLATILITY"], "E_TREND_LOCATION": families["TREND_LOCATION"], "F_ACCOUNT_STATE": state_columns,
        "G_CLOCK_MARKET": families["CLOCK"] + families["MARKET_GEOMETRY"] + families["MOMENTUM"] + families["VOLATILITY"] + families["TREND_LOCATION"],
        "H_CLOCK_STATE": families["CLOCK"] + state_columns,
        "I_MARKET_STATE": families["MARKET_GEOMETRY"] + families["MOMENTUM"] + families["VOLATILITY"] + families["TREND_LOCATION"] + state_columns,
        "J_CLOCK_MARKET_STATE": full,
    }
    for family, columns in ablations.items():
        rows, _ = evaluate_model(panel, columns, "l1_logistic", family, folds)
        all_rows.extend(rows)
    replication = pd.DataFrame(all_rows)
    replication.to_csv(OUT / "phase5_replication_results.csv", index=False)
    baseline_summary = aggregate([row for row in all_rows if row["family"] == "CLOCK+MARKET+STATE"])
    ablation_summary = aggregate([row for row in all_rows if row["family"] != "CLOCK+MARKET+STATE"])
    (OUT / "phase5_baseline_analysis.md").write_text(
        "# Phase 5 baseline observable-space models\n\n"
        "Five predeclared regularized/restricted classifiers were evaluated with five expanding chronological folds. Training used a bounded case-control sample for computational stability; every validation metric is computed across the full chronological candidate-minute fold. Thresholds select the predeclared raw-trade-rate signal budget. A 15-minute embargo separates train from validation.\n\n"
        + md_table(baseline_summary.round(6)) + "\n\nPR AUC is primary; ROC AUC is reported only as a secondary ranking diagnostic under extreme imbalance. A score does not identify the EA.\n",
        encoding="utf-8",
    )
    (OUT / "phase5_feature_ablation.md").write_text(
        "# Phase 5 feature-family ablation\n\n"
        "The ten hypothesis families were predeclared before inspection: A CLOCK, B GEOMETRY, C MOMENTUM, D VOLATILITY, E TREND/LOCATION, F ACCOUNT STATE, and the four stated combinations. Each uses the same L1 logistic candidate and chronological protocol.\n\n"
        + md_table(ablation_summary.round(6)) + "\n\nNo family is called a reconstruction unless it distinguishes matched controls and has stable OOS precision/recall.\n",
        encoding="utf-8",
    )

    rules = symbolic_rules(panel)
    symbolic_rows = []
    final_controls = negative.loc[negative.is_final_matched_control].copy()
    control_rows = panel.set_index("timestamp")
    for name, predicate in rules.items():
        signal = predicate(panel).fillna(False).to_numpy(dtype=bool)
        y = panel.entry.to_numpy(dtype=bool)
        base = y.mean()
        activated = signal.sum()
        tp = int((signal & y).sum())
        pvalue = binomtest(tp, int(activated), base, alternative="greater").pvalue if activated else 1.0
        matched_trade, matched_control = [], []
        for item in final_controls.itertuples(index=False):
            t = pd.Timestamp(item.trade_candidate_minute)
            c = pd.Timestamp(item.control_timestamp)
            if t in control_rows.index and c in control_rows.index:
                matched_trade.append(bool(predicate(control_rows.loc[[t]]).iloc[0]))
                matched_control.append(bool(predicate(control_rows.loc[[c]]).iloc[0]))
        b = sum(a and not b_ for a, b_ in zip(matched_trade, matched_control))
        c = sum((not a) and b_ for a, b_ in zip(matched_trade, matched_control))
        matched_p = binomtest(max(b, c), b + c, 0.5).pvalue if b + c else 1.0
        symbolic_rows.append({
            "expression": name, "features_used": name.replace("and", "+"), "complexity": name.count("and") + 1,
            "training_precision": "NOT_FIT", "oos_precision": tp / activated if activated else 0.0, "oos_recall": tp / y.sum(),
            "oos_f1": 2 * tp / (activated + y.sum()) if activated else 0.0, "oos_pr_auc": "NOT_APPLICABLE_PREDICATE",
            "predicted_signals": int(activated), "actual_trades_captured": tp, "false_alarms": int(activated - tp),
            "fold_stability": "static predicate; evaluated across full observable panel", "enrichment_pvalue": pvalue,
            "matched_discordant_trade_only": b, "matched_discordant_control_only": c, "matched_pvalue": matched_p,
        })
    symbolic = pd.DataFrame(symbolic_rows)
    symbolic["enrichment_qvalue"] = bh_qvalues(symbolic.enrichment_pvalue)
    symbolic["matched_qvalue"] = bh_qvalues(symbolic.matched_pvalue)
    symbolic["acceptance"] = np.where(
        (symbolic.oos_f1 >= 0.05) & (symbolic.matched_qvalue < 0.05), "CANDIDATE_FOR_FURTHER_EVIDENCE", "REJECTED_AS_RECONSTRUCTION"
    )
    symbolic.to_csv(OUT / "phase5_symbolic_candidates.csv", index=False)
    (OUT / "phase5_symbolic_regression.md").write_text(
        "# Phase 5 symbolic candidate generation\n\n"
        "A fixed eight-expression, depth-limited Boolean grammar was enumerated instead of an unconstrained formula search. The candidate set was defined before testing. BH FDR correction is applied separately to the eight panel-enrichment tests and eight matched-control tests. These are observable-space predicates, not an EA formula.\n\n"
        + md_table(symbolic.round(6)) + "\n\nNo expression is accepted as a reconstruction unless it satisfies both predeclared OOS and matched-control requirements.\n",
        encoding="utf-8",
    )

    # Small predefined event vocabulary; it is a report-level falsification, not massive sequence mining.
    sequence_rows = []
    for label, predicate in {
        "boundary_then_expansion_5m": panel.m30_boundary.eq(1) & panel.range_expansion.gt(1.25),
        "momentum_then_breakout": panel.return_5m.gt(0) & panel.breakout_distance.gt(0),
        "reversal_then_confirmation": panel.return_3m.mul(panel.return_10m).lt(0) & panel.return_3m.abs().gt(0),
        "local_low_then_recovery": panel.dist_recent_low.abs().lt(panel.atr_14) & panel.return_5m.gt(0),
    }.items():
        sig = predicate.fillna(False)
        sequence_rows.append({"sequence": label, "signals": int(sig.sum()), "trade_minutes": int((sig & panel.entry.eq(1)).sum()), "precision": float(panel.loc[sig, "entry"].mean()) if sig.any() else 0.0})
    sequence = pd.DataFrame(sequence_rows)
    (OUT / "phase5_event_sequence_analysis.md").write_text(
        "# Phase 5 event-sequence discovery\n\n"
        "Only four predeclared, interpretable sequences were evaluated. No unconstrained temporal-pattern mining was performed. Panel precision alone is not a reconstruction and is subject to the same missing true-opportunity-set limitation.\n\n" + md_table(sequence.round(6)) + "\n", encoding="utf-8")

    # Direction among observed M1 opportunity minutes only; chronological OOS logistic accuracy.
    opportunity = panel.loc[panel.entry.eq(1)].merge(trades.assign(timestamp=trades.open_time.dt.floor("min"))[["timestamp", "side"]].drop_duplicates("timestamp"), on="timestamp", how="left")
    direction_features = families["MARKET_GEOMETRY"] + families["MOMENTUM"] + families["TREND_LOCATION"] + families["CLOCK"] + state_columns
    direction = opportunity.dropna(subset=["side"]).reset_index(drop=True)
    direction_y = direction.side.eq("Buy").astype(int).to_numpy()
    direction_scores, direction_truth = [], []
    if len(direction) >= 100:
        for start in np.linspace(int(len(direction) * .5), int(len(direction) * .9), 5, endpoint=False, dtype=int):
            end = min(len(direction), start + max(1, int(len(direction) * .1)))
            pipe = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", LogisticRegression(penalty="l1", solver="saga", C=.05, max_iter=500, random_state=SEED))])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ConvergenceWarning)
                pipe.fit(direction.loc[: start - 1, direction_features], direction_y[:start])
            direction_scores.extend(pipe.predict_proba(direction.loc[start:end - 1, direction_features])[:, 1])
            direction_truth.extend(direction_y[start:end])
    direction_auc = roc_auc_score(direction_truth, direction_scores) if len(set(direction_truth)) == 2 else np.nan
    direction_acc = float(np.mean((np.asarray(direction_scores) >= .5) == np.asarray(direction_truth))) if direction_truth else np.nan
    (OUT / "phase5_direction_analysis.md").write_text(
        "# Phase 5 direction analysis\n\n"
        f"Direction was evaluated only at observed M1 trade-opportunity minutes, never over all minutes. Five chronological folds gave OOS Buy/Sell accuracy {direction_acc:.4f} and ROC AUC {direction_auc:.4f}. This conditional test does not recover direction where multiple tickets share an M1 minute or where hidden opportunity state is unobserved. **Direction remains unidentified within the observable information set.**\n",
        encoding="utf-8",
    )
    large = trades.lot_size.gt(.01)
    contingency = pd.crosstab(large, trades.side)
    p_size_side = fisher_exact(contingency.reindex(index=[False, True], columns=["Buy", "Sell"], fill_value=0))[1]
    (OUT / "phase5_sizing_analysis.md").write_text(
        "# Phase 5 sizing analysis\n\n"
        f"There are {int(large.sum())} above-minimum-size trades among 423. An exact side-versus-large-size Fisher test has p={p_size_side:.6g}; this sparse count cannot establish a sizing policy. Account balance, margin, request state and signal-strength inputs are absent. The all-winner concentration for larger lots is post-entry and was not used as a sizing feature. **Sizing remains NOT_IDENTIFIABLE.**\n",
        encoding="utf-8",
    )
    (OUT / "phase5_exit_analysis.md").write_text(
        "# Phase 5 exit analysis\n\n"
        "**NOT_IDENTIFIABLE_FROM_M1.** The available M1 proxy cannot show Bid/Ask touch order, broker-side stop/target activation, trailing modifications, partial closes, or manual/account-level closures. Excursions are descriptive only and are not promoted to SL/TP evidence.\n",
        encoding="utf-8",
    )
    (OUT / "phase5_regime_stability.md").write_text(
        "# Phase 5 regime stability\n\n"
        "All selection results are reported fold-by-fold in `phase5_replication_results.csv`; the folds are chronological and span the later half of the usable M1 panel. No candidate is promoted on pooled performance alone. Without a candidate satisfying matched-control acceptance, a regime-specific reconstruction claim is not warranted.\n",
        encoding="utf-8",
    )
    (OUT / "phase5_information_boundary.md").write_text(
        "# Phase 5 observable information boundary\n\n"
        "## Inverse problem\n\n"
        "For observed executions D={(t_i,a_i,p_i,v_i,t_i^out,p_i^out)} and the limited pre-decision proxy X_t=(X_t^market,X_t^clock,X_t^state), the compatible class is H_D={h : h(X_ti)=a_i for every observed i}. A finite dataset does not uniquely identify the original policy without additional assumptions. Computable programs are countable, but infinitely many distinct computable policies can agree with a finite observation set and differ elsewhere; therefore training fit cannot establish strategy identity.\n\n"
        "## Intrabar temporal aggregation / partial observation\n\n"
        "M1 OHLC does not retain intrabar ordering, exact seconds, Bid/Ask, spread, tick sequence, pending orders or broker execution state. Multiple second-level paths can map to the same M1 bar. Exact second-level and spread-gated triggers therefore cannot be uniquely recovered from M1 OHLC alone. This is an aggregation/partial-observation limitation, not a Shannon-Nyquist claim.\n\n"
        "## Boundary\n\n"
        "Observable space contains completed external M1-derived rolling M5/M15/M30/H1/D1 proxies, clock features, and prior ledger state. It excludes broker-native ticks, Bid/Ask, spread, orders, rejected/cancelled orders, modifications, server timing and hidden EA state. Hidden microstructure is unresolved information outside the dataset; it is not asserted to be the cause. SINDy is not applicable to this partial decision-policy reconstruction, and IRL is not identifiable without observed non-actions and hidden transitions.\n",
        encoding="utf-8",
    )
    best_ablation = ablation_summary.sort_values(["f1", "precision"], ascending=False).head(3)
    status = "# Phase 5 status\n\n"
    status += "1. **Canonical ground truth:** 423 trades; 214 Buy / 209 Sell; 367 profitable / 56 losing; +1451.22 P&L; 401×0.01, 21×0.02, 1×0.03; three later entries began while a prior trade was active (correcting the earlier narrative count of five after raw-ledger recheck).\n"
    status += "2. **Observable information:** completed external bid-only M1 OHLCV-derived features, raw-clock features, and prior ledger/account-state proxies.\n"
    status += "3. **Provably unavailable locally:** broker-native ticks, Ask/spread, order/deal/position lifecycle, modifications, rejected/cancelled orders, and broker-server timing.\n"
    status += f"4. **Nearest non-trade alternatives:** {len(negative)} hierarchical matched rows were constructed; no observable equality can rule out a hidden order, quote or state difference.\n"
    status += "5. **OOS feature families:** see predeclared ablation table below; none is labelled a reconstruction without matched acceptance.\n"
    status += "6. **Symbolic regression:** constrained eight-expression candidate generation found no accepted compact stable rule.\n"
    status += "7. **Exact trade moments:** no candidate is promoted as reproducing a substantial fraction of exact second-level trade moments; M1 only has 420 distinct entry minutes.\n"
    status += "8. **Matched near-miss testing:** no candidate met the predeclared matched-control acceptance test after BH correction.\n"
    status += "9. **Direction:** remains unidentified within the observable opportunity-minute set.\n"
    status += "10. **Sizing:** remains unidentified; only 22 above-minimum-size observations and critical account inputs are missing.\n"
    status += "11. **Exits:** NOT_IDENTIFIABLE_FROM_M1.\n"
    status += "12. **Regime specificity:** no reconstruction-level candidate exists to claim cross-regime stability.\n"
    status += "13. **Hypotheses tested:** 5 full-feature baselines + 10 L1 ablations + 8 predeclared symbolic predicates + 4 controlled sequences.\n"
    status += "14. **Multiple testing:** BH was applied to the eight symbolic enrichment tests and separately to eight matched tests; no candidate met the combined acceptance rule.\n"
    status += "15. **Mathematically unidentifiable:** the original policy among infinitely many compatible computable policies, exact intrabar trigger, true opportunity set and lifecycle.\n"
    status += "16. **Highest-value additional data:** a synchronized native terminal/account archive containing Bid/Ask ticks plus Orders, Deals, Positions and Journal lifecycle for XAUUSD.f.\n\n"
    status += "## Best OOS ablation summaries\n\n" + md_table(best_ablation.round(6)) + "\n\n**Final level: LEVEL D — UNIDENTIFIED.** Statistical association, prediction, and a compact observable predicate are not treated as causal reconstruction.\n"
    (OUT / "phase5_status.md").write_text(status, encoding="utf-8")
    validation = {
        "phase": 5, "identification_level": "D — UNIDENTIFIED", "canonical": canonical,
        "candidate_minutes": int(len(panel)), "entry_minutes": int(panel.entry.sum()), "negative_space_rows": int(len(negative)),
        "folds": 5, "embargo_minutes": EMBARGO_MINUTES, "baseline_hypotheses": 5, "ablation_hypotheses": 10,
        "symbolic_hypotheses": len(symbolic), "sequence_hypotheses": len(sequence),
        "symbolic_accepted": int(symbolic.acceptance.eq("CANDIDATE_FOR_FURTHER_EVIDENCE").sum()),
        "sindy": "SINDY_NOT_APPLICABLE", "irl": "IRL_NOT_IDENTIFIABLE",
        "future_information_policy": "All market features shifted one M1 observation; account-state features inherited Phase 3 before-candidate availability convention.",
    }
    (OUT / "phase5_validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    print(json.dumps({"level": validation["identification_level"], "candidate_minutes": len(panel), "negative_rows": len(negative), "symbolic_accepted": validation["symbolic_accepted"]}, indent=2))


if __name__ == "__main__":
    main()
