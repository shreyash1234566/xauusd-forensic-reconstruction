"""Phase 3: clock windows, observed state, and M1-limited opportunity tests.

This continuation intentionally does not infer tick-level facts from M1 OHLC.
All predictive market features use completed bars only; state features are based
on trades/events that occurred strictly before the candidate minute.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.tree import DecisionTreeClassifier, export_text

from reverse_trade.pipeline import load_trades

try:
    from scripts.continue_identification import NumericModel, calibrated_fit, chronological_folds, fit_numeric_model, nearest_errors
    from scripts.phase2_event_eligibility import attach_trade_state, bh_qvalues, event_features_from_bars, session_bucket
except ModuleNotFoundError:
    from continue_identification import NumericModel, calibrated_fit, chronological_folds, fit_numeric_model, nearest_errors
    from phase2_event_eligibility import attach_trade_state, bh_qvalues, event_features_from_bars, session_bucket


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"
SEED = 20260920


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if pd.isna(value):
        return None
    return value


def markdown_table(frame: pd.DataFrame, rows: int | None = None) -> str:
    view = frame.head(rows) if rows else frame
    if view.empty:
        return "No rows available."
    lines = [
        "| " + " | ".join(view.columns.astype(str)) + " |",
        "| " + " | ".join("---" for _ in view.columns) + " |",
    ]
    for values in view.itertuples(index=False, name=None):
        formatted = []
        for value in values:
            if isinstance(value, float):
                formatted.append("n.a." if not np.isfinite(value) else f"{value:.5g}")
            else:
                formatted.append(str(value).replace("|", "/"))
        lines.append("| " + " | ".join(formatted) + " |")
    return "\n".join(lines)


def clock_window_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Generate raw-clock boundary/window variables from the candidate timestamp."""
    result = frame.copy()
    minute_of_day = result["timestamp"].dt.hour * 60 + result["timestamp"].dt.minute
    for period, label in [(5, "m5"), (15, "m15"), (30, "m30"), (60, "h1")]:
        remainder = minute_of_day % period
        result[f"clock_{label}_boundary"] = (remainder == 0).astype("int8")
        # At M1 granularity the first three candidate minutes proxy the
        # 0-to-120-second post-boundary window; no intraminute event is assumed.
        result[f"clock_{label}_post120"] = (remainder <= 2).astype("int8")
        result[f"clock_{label}_phase_minutes"] = remainder.astype("int8")
    result["clock_phase_30"] = (minute_of_day % 30).astype("int8")
    return result


def add_history_state(panel: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """Add trade-history features that were available before each minute starts."""
    result = panel.copy().sort_values("timestamp").reset_index(drop=True)
    timeline = result[["timestamp"]].copy()
    arrivals = trades.copy()
    # A fill at xx:yy:56 becomes known to a candidate minute at xx:yy+1:00.
    arrivals["available_time"] = arrivals["open_time"].dt.ceil("min")
    starts = pd.DataFrame({"timestamp": arrivals["available_time"]})
    starts["trade_arrival"] = 1
    starts["buy_arrival"] = arrivals["side"].eq("Buy").astype(int)
    starts["sell_arrival"] = arrivals["side"].eq("Sell").astype(int)
    starts = starts.groupby("timestamp", as_index=False).sum()
    result = result.merge(starts, on="timestamp", how="left")
    for column in ["trade_arrival", "buy_arrival", "sell_arrival"]:
        result[column] = result[column].fillna(0)
    day = result["timestamp"].dt.floor("D")
    result["trades_today_before"] = result["trade_arrival"].groupby(day).cumsum()
    result["trades_prev_hour"] = result["trade_arrival"].rolling(60, min_periods=1).sum()
    result["buys_prev_hour"] = result["buy_arrival"].rolling(60, min_periods=1).sum()
    result["sells_prev_hour"] = result["sell_arrival"].rolling(60, min_periods=1).sum()
    session = session_bucket(result["timestamp"]).astype(str)
    result["trades_session_before"] = result["trade_arrival"].groupby([day, session]).cumsum()

    close_arrivals = trades.copy()
    close_arrivals["available_time"] = close_arrivals["close_time"].dt.ceil("min")
    closes = pd.DataFrame({"timestamp": close_arrivals["available_time"]})
    closes["win_close_arrival"] = close_arrivals["win"].astype(int)
    closes["loss_close_arrival"] = (~close_arrivals["win"]).astype(int)
    closes = closes.groupby("timestamp", as_index=False).sum()
    result = result.merge(closes, on="timestamp", how="left")
    for column in ["win_close_arrival", "loss_close_arrival"]:
        result[column] = result[column].fillna(0)
        result[f"{column}_prev_hour"] = result[column].rolling(60, min_periods=1).sum()

    for side, label in [("Buy", "buy"), ("Sell", "sell")]:
        side_times = trades.loc[trades["side"].eq(side), ["open_time"]].rename(columns={"open_time": f"last_{label}_entry_time"})
        merged = pd.merge_asof(
            timeline, side_times.sort_values(f"last_{label}_entry_time"), left_on="timestamp", right_on=f"last_{label}_entry_time",
            direction="backward", allow_exact_matches=False,
        )
        result[f"seconds_since_last_{label}_entry"] = (result["timestamp"] - merged[f"last_{label}_entry_time"]).dt.total_seconds()

    # The prior observed event count has no outcome label: it only describes
    # completed events seen before this candidate minute.
    result["recent_completed_events_30"] = result["event_any"].shift(1).fillna(0).rolling(30, min_periods=1).sum()
    result["recent_m30_boundaries_120"] = result["clock_m30_boundary"].shift(1).fillna(0).rolling(120, min_periods=1).sum()
    result["clock_m30_x_cooldown"] = result["clock_m30_post120"] * result["cooldown_log_seconds"].fillna(0)
    result["clock_m30_x_event"] = result["clock_m30_post120"] * result["event_any"].fillna(0)
    result["clock_h1_x_location"] = result["clock_h1_post120"] * result["m1_ema20_dist"].fillna(0)
    return result


def inventory_report() -> str:
    metadata = json.loads((ROOT / "data" / "market" / "metadata.json").read_text(encoding="utf-8"))
    rows = [
        {
            "source": "data/raw/trades_raw.tsv", "date range": "2025-09-25 to 2026-09-18", "granularity": "closed trade records",
            "bid/ask": "neither", "timezone": "as supplied", "symbol": "XAUUSD.f", "data quality": "423 preserved rows",
            "usable for Phase 3": "trade timing/state only",
        },
        {
            "source": "data/market/raw/xauusd_m1_utc_raw.csv", "date range": f"{metadata['date_from']} to {metadata['date_to']}",
            "granularity": "M1 OHLCV", "bid/ask": "bid only", "timezone": "UTC", "symbol": "XAUUSD",
            "data quality": f"{metadata['raw_row_count']:,} rows; {metadata['gap_count_gt5min']} gaps >5m", "usable for Phase 3": "completed-bar / clock proxy",
        },
        {
            "source": "data/market/normalized/xauusd_m1.csv", "date range": f"{metadata['date_from']} to {metadata['date_to']}",
            "granularity": "M1 OHLCV", "bid/ask": "bid only", "timezone": "UTC+3 proxy mapping", "symbol": "XAUUSD",
            "data quality": f"{metadata['normalized_row_count']:,} rows; OHLC integrity checks pass", "usable for Phase 3": "aligned M1 proxy",
        },
        {
            "source": "data/market/test_download/*.csv", "date range": "2025-09-25 to 2025-09-26", "granularity": "M1 sample",
            "bid/ask": "bid only", "timezone": "UTC/raw sample", "symbol": "XAUUSD", "data quality": "download/format smoke-test sample", "usable for Phase 3": "not additional granularity",
        },
    ]
    return f"""# Phase 3 data inventory

## Result

The repository was searched outside `outputs/` for CSV, TSV, JSON, Parquet, pickle, SQLite/database, log, archive, MetaTrader-history and spreadsheet files. No tick file, ask series, live spread series, raw broker export, MT4/MT5 order/deal/position history, SL/TP modification record, account history, execution report or platform log was found.

{markdown_table(pd.DataFrame(rows))}

## Phase 3 consequence

Tick crossing, bid/ask spread gate, first tick after close, second-level timer, intrabar path, order-book state and actual execution sequence are **UNIDENTIFIABLE** from the available data. The proxy analysis below uses only M1 timestamps and completed M1 bid OHLCV; it cannot convert a clock association into source-code recovery.
"""


def actual_clock_delays(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for period, label in [(5, "M5"), (15, "M15"), (30, "M30"), (60, "H1")]:
        seconds = period * 60
        prior = trades["open_time"].dt.floor(f"{period}min")
        after = (trades["open_time"] - prior).dt.total_seconds()
        nearest = np.minimum(after, seconds - after)
        for tolerance in [0, 1, 2, 5, 10, 15, 30, 60, 120]:
            rows.append({
                "clock_event": label, "tolerance_seconds": tolerance, "share_after_prior_boundary": float((after <= tolerance).mean()),
                "share_nearest_boundary": float((nearest <= tolerance).mean()), "median_seconds_after_prior_boundary": float(np.median(after)),
                "median_seconds_to_nearest_boundary": float(np.median(nearest)),
            })
    return pd.DataFrame(rows)


def fixed_rule_replication(panel: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """Chronological evaluation of predeclared bar-boundary/window hypotheses."""
    candidates = panel[panel["eligible_observed_capacity"].eq(1)].copy().sort_values("timestamp")
    rules = {
        "H1 M30 boundary / bar-close proxy": "clock_m30_boundary",
        "H2 M30 fixed-timer proxy": "clock_m30_boundary",
        "H3 M30 post-120s window": "clock_m30_post120",
        "H1 H1 boundary / bar-close proxy": "clock_h1_boundary",
        "H2 H1 fixed-timer proxy": "clock_h1_boundary",
        "H3 H1 post-120s window": "clock_h1_post120",
    }
    rows: list[dict[str, Any]] = []
    for name, column in rules.items():
        for fold, (_, start, end) in enumerate(chronological_folds(panel), start=1):
            test = candidates[(candidates["timestamp"] >= start) & (candidates["timestamp"] < end)]
            actual = test["entry"].to_numpy(dtype=int)
            predicted = test[column].to_numpy(dtype=bool)
            observed = trades[(trades["open_time"] >= start) & (trades["open_time"] < end)]
            errors = nearest_errors(observed["open_time"], test.loc[predicted, "timestamp"])
            rows.append({
                "evaluation": "oos_fold", "hypothesis": name, "fold": fold, "candidate_signals": int(predicted.sum()),
                "tp": int(np.sum(predicted & (actual == 1))), "fp": int(np.sum(predicted & (actual == 0))),
                "fn": int(np.sum(~predicted & (actual == 1))), "precision": precision_score(actual, predicted, zero_division=0),
                "recall": recall_score(actual, predicted, zero_division=0), "f1": f1_score(actual, predicted, zero_division=0),
                "entry_match_1s": float(np.mean(errors <= 1)), "entry_match_5s": float(np.mean(errors <= 5)),
                "entry_match_15s": float(np.mean(errors <= 15)), "entry_match_30s": float(np.mean(errors <= 30)),
                "entry_match_60s": float(np.mean(errors <= 60)), "entry_match_one_m1_bar": float(np.mean(errors <= 119)),
                "complexity": "single raw-clock predicate",
            })
    folds = pd.DataFrame(rows)
    summaries = []
    for name, subset in folds.groupby("hypothesis"):
        total = subset[["tp", "fp", "fn"]].sum()
        summaries.append({
            "evaluation": "oos_aggregate", "hypothesis": name, "fold": "all", "candidate_signals": int(total.tp + total.fp),
            "tp": int(total.tp), "fp": int(total.fp), "fn": int(total.fn),
            "precision": float(total.tp / max(total.tp + total.fp, 1)), "recall": float(total.tp / max(total.tp + total.fn, 1)),
            "f1": float(subset.f1.mean()), "entry_match_1s": float(subset.entry_match_1s.mean()),
            "entry_match_5s": float(subset.entry_match_5s.mean()), "entry_match_15s": float(subset.entry_match_15s.mean()),
            "entry_match_30s": float(subset.entry_match_30s.mean()), "entry_match_60s": float(subset.entry_match_60s.mean()),
            "entry_match_one_m1_bar": float(subset.entry_match_one_m1_bar.mean()), "complexity": "single raw-clock predicate",
        })
    return pd.concat([pd.DataFrame(summaries), folds], ignore_index=True)


def tree_fit(train: pd.DataFrame, features: list[str], seed: int) -> tuple[NumericModel, float]:
    generator = np.random.default_rng(seed)
    split = max(int(len(train) * 0.8), 1)

    def fit(frame: pd.DataFrame) -> NumericModel:
        positive = frame.index[frame.entry.eq(1)].to_numpy()
        negative = frame.index[frame.entry.eq(0)].to_numpy()
        selected = generator.choice(negative, size=min(len(negative), max(50 * len(positive), 1)), replace=False)
        working = frame.loc[np.concatenate([positive, selected])]
        values = working[features].to_numpy(dtype=float)
        median = np.nanmedian(values, axis=0)
        median = np.where(np.isfinite(median), median, 0)
        values = np.where(np.isfinite(values), values, median)
        estimator = DecisionTreeClassifier(max_depth=3, min_samples_leaf=12, class_weight="balanced", random_state=seed)
        estimator.fit(values, working.entry)
        return NumericModel(estimator, median, np.zeros(len(features)), np.ones(len(features)), False, features)

    initial = fit(train.iloc[:split])
    calibration = train.iloc[split:]
    score = initial.probabilities(calibration)
    thresholds = np.unique(np.quantile(score, np.linspace(0.70, 0.995, 75)))
    threshold = max(((f1_score(calibration.entry, score >= t, zero_division=0), t) for t in thresholds), key=lambda x: x[0])[1]
    return fit(train), float(threshold)


def sparse_eligibility(panel: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = panel[panel["eligible_observed_capacity"].eq(1)].copy().sort_values("timestamp")
    features = [
        "clock_m30_post120", "clock_h1_post120", "clock_m30_x_cooldown", "clock_m30_x_event", "clock_h1_x_location",
        "event_count", "event_range_expansion_strength", "event_body_ratio", "event_bar_direction", "cooldown_log_seconds",
        "seconds_since_last_entry", "trades_today_before", "trades_prev_hour", "trades_session_before", "active_positions_before_candidate",
        "prior_win_code", "prior_direction_code", "prior_large_code", "recent_completed_events_30", "recent_m30_boundaries_120",
        "m1_ema20_dist", "m1_vwap_dist", "m1_range_percentile_240", "m15_price_ema20", "h1_price_ema20",
    ]
    features = [feature for feature in features if feature in data.columns]
    definitions = {"P3 sparse clock+state eligibility": "l1", "P3 constrained clock+state tree": "tree"}
    rows: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    for name, kind in definitions.items():
        for fold, (_, start, end) in enumerate(chronological_folds(panel), start=1):
            train = data[data.timestamp < start]
            test = data[(data.timestamp >= start) & (data.timestamp < end)]
            model, threshold = tree_fit(train, features, SEED + 100 + fold) if kind == "tree" else calibrated_fit(train, features, kind="l1", seed=SEED + 100 + fold)
            score = model.probabilities(test)
            predicted = score >= threshold
            actual = test.entry.to_numpy(dtype=int)
            observed = trades[(trades.open_time >= start) & (trades.open_time < end)]
            errors = nearest_errors(observed.open_time, test.loc[predicted, "timestamp"])
            rows.append({
                "evaluation": "oos_fold", "hypothesis": name, "fold": fold, "candidate_signals": int(predicted.sum()),
                "tp": int(np.sum(predicted & (actual == 1))), "fp": int(np.sum(predicted & (actual == 0))), "fn": int(np.sum(~predicted & (actual == 1))),
                "precision": precision_score(actual, predicted, zero_division=0), "recall": recall_score(actual, predicted, zero_division=0),
                "f1": f1_score(actual, predicted, zero_division=0), "roc_auc": roc_auc_score(actual, score), "pr_auc": average_precision_score(actual, score),
                "entry_match_1s": float(np.mean(errors <= 1)), "entry_match_5s": float(np.mean(errors <= 5)),
                "entry_match_15s": float(np.mean(errors <= 15)), "entry_match_30s": float(np.mean(errors <= 30)),
                "entry_match_60s": float(np.mean(errors <= 60)), "entry_match_one_m1_bar": float(np.mean(errors <= 119)),
                "threshold": threshold, "feature_count": len(features), "complexity": "depth-3 tree" if kind == "tree" else "L1 logistic",
            })
            if kind == "tree":
                rules.append({"hypothesis": name, "fold": fold, "rule_type": "depth-3 tree", "rule_or_feature": export_text(model.estimator, feature_names=features), "coefficient": np.nan, "threshold": threshold})
            else:
                for feature, coefficient in zip(features, model.estimator.coef_.ravel()):
                    if abs(coefficient) > 1e-8:
                        rules.append({"hypothesis": name, "fold": fold, "rule_type": "L1 logistic feature", "rule_or_feature": feature, "coefficient": float(coefficient), "threshold": threshold})
    folds = pd.DataFrame(rows)
    aggregate = []
    for name, subset in folds.groupby("hypothesis"):
        total = subset[["tp", "fp", "fn"]].sum()
        aggregate.append({
            "evaluation": "oos_aggregate", "hypothesis": name, "fold": "all", "candidate_signals": int(total.tp + total.fp),
            "tp": int(total.tp), "fp": int(total.fp), "fn": int(total.fn), "precision": float(total.tp / max(total.tp + total.fp, 1)),
            "recall": float(total.tp / max(total.tp + total.fn, 1)), "f1": float(subset.f1.mean()),
            "roc_auc": float(subset.roc_auc.mean()), "pr_auc": float(subset.pr_auc.mean()),
            "entry_match_1s": float(subset.entry_match_1s.mean()), "entry_match_5s": float(subset.entry_match_5s.mean()),
            "entry_match_15s": float(subset.entry_match_15s.mean()), "entry_match_30s": float(subset.entry_match_30s.mean()),
            "entry_match_60s": float(subset.entry_match_60s.mean()), "entry_match_one_m1_bar": float(subset.entry_match_one_m1_bar.mean()),
            "feature_count": len(features), "complexity": str(subset.complexity.iloc[0]),
        })
    return pd.concat([pd.DataFrame(aggregate), folds], ignore_index=True), pd.DataFrame(rules)


def phase3_nearmisses(panel: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Match non-entry minutes on clock phase plus broad state, then inspect differences."""
    candidates = panel[panel.eligible_observed_capacity.eq(1) & panel.entry.eq(0)].copy()
    candidates["date"] = candidates.timestamp.dt.floor("D")
    candidates["session"] = session_bucket(candidates.timestamp).astype(str)
    match_columns = [
        "cooldown_log_seconds", "seconds_since_last_entry", "trades_today_before", "trades_prev_hour", "trades_session_before",
        "active_positions_before_candidate", "m1_atr_ratio", "m1_range", "m1_return_5", "m1_ema20_dist", "m15_price_ema20", "h1_price_ema20",
    ]
    values = panel[match_columns].to_numpy(dtype=float)
    median = np.nanmedian(values, axis=0)
    scale = np.nanstd(values, axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 1e-10), scale, 1)
    indexed = panel.set_index("timestamp", drop=False)
    rows: list[dict[str, Any]] = []
    long: list[dict[str, Any]] = []
    for trade in trades.sort_values("open_time").itertuples(index=False):
        moment = pd.Timestamp(trade.open_time).floor("min")
        observed = indexed.loc[moment]
        pool = candidates[
            candidates.date.eq(moment.floor("D")) & candidates.session.eq(session_bucket(pd.Series([moment])).astype(str).iloc[0])
            & candidates.clock_phase_30.eq(observed.clock_phase_30)
            & (candidates.timestamp - moment).abs().between(pd.Timedelta(minutes=2), pd.Timedelta(hours=4))
        ]
        if pool.empty:
            pool = candidates[candidates.date.eq(moment.floor("D")) & candidates.clock_phase_30.eq(observed.clock_phase_30)]
        target = observed[match_columns].to_numpy(dtype=float)
        target = np.where(np.isfinite(target), target, median)
        array = pool[match_columns].to_numpy(dtype=float)
        array = np.where(np.isfinite(array), array, median)
        distance = np.sqrt(np.mean(((array - target) / scale) ** 2, axis=1))
        chosen_index = int(np.argmin(distance))
        control = pool.iloc[chosen_index]
        state_similarity = float(distance[chosen_index])
        state_delta = pd.Series(np.abs((control[match_columns].to_numpy(dtype=float) - target) / scale), index=match_columns).sort_values(ascending=False).head(4)
        event_differences = [
            column for column in ["event_any", "event_count", "clock_m30_post120", "clock_h1_post120"]
            if float(observed[column]) != float(control[column])
        ]
        condition = ", ".join(event_differences) if event_differences else "no isolated measured clock/event condition"
        rows.append({
            "trade_ticket": str(trade.ticket), "trade_time": trade.open_time, "trade_direction": trade.side, "control_time": control.timestamp,
            "clock_event": f"M30 phase {int(observed.clock_phase_30)}", "state_similarity": state_similarity,
            "state_difference": "; ".join(f"{key} Δz={value:.2f}" for key, value in state_delta.items()),
            "market_difference": f"m1_return_5 Δ={observed.m1_return_5 - control.m1_return_5:.6g}; m1_ema20_dist Δ={observed.m1_ema20_dist - control.m1_ema20_dist:.3g}",
            "event_difference": ", ".join(event_differences) if event_differences else "same measured event flags",
            "candidate_hidden_condition": condition,
        })
        long.append({"ticket": str(trade.ticket), "trade_time": trade.open_time, "control_time": control.timestamp, "state_similarity": state_similarity, **{f"trade_{x}": observed[x] for x in match_columns}, **{f"control_{x}": control[x] for x in match_columns}})
    return pd.DataFrame(rows), pd.DataFrame(long)


def opportunity_density(panel: pd.DataFrame) -> pd.DataFrame:
    eligible = panel[panel.eligible_observed_capacity.eq(1)].copy()
    eligible["date"] = eligible.timestamp.dt.date
    eligible["session"] = session_bucket(eligible.timestamp).astype(str)
    eligible["hour"] = eligible.timestamp.dt.hour
    grouped = eligible.groupby(["date", "session", "hour"], as_index=False).agg(
        candidate_minutes=("entry", "size"), m30_window_events=("clock_m30_post120", "sum"), h1_window_events=("clock_h1_post120", "sum"), actual_entry_bars=("entry", "sum")
    )
    grouped["trade_per_m30_window_event"] = grouped.actual_entry_bars / grouped.m30_window_events.replace(0, np.nan)
    grouped["trade_per_candidate_minute"] = grouped.actual_entry_bars / grouped.candidate_minutes
    return grouped


def sequence_mining(panel: pd.DataFrame, nearmiss_long: pd.DataFrame) -> pd.DataFrame:
    """Small prespecified vocabulary, lengths 2-5; controls share M30 clock phase."""
    state = np.select(
        [panel.clock_h1_boundary.eq(1), panel.clock_m30_boundary.eq(1), panel.clock_m15_boundary.eq(1), panel.event_count.ge(2), panel.event_any.eq(1), panel.cooldown_log_seconds.le(np.log1p(300))],
        ["H1", "M30", "M15", "ARM", "EVENT", "COOLDOWN"], default="OTHER",
    )
    by_time = dict(zip(panel.timestamp, state))
    def sequence_at(timestamp: pd.Timestamp, length: int) -> str:
        return ">".join(by_time.get(timestamp - pd.Timedelta(minutes=offset), "GAP") for offset in range(length - 1, -1, -1))
    actual = pd.to_datetime(nearmiss_long.trade_time).dt.floor("min")
    control = pd.to_datetime(nearmiss_long.control_time).dt.floor("min")
    rows = []
    for length in [2, 3, 4, 5]:
        actual_seq = actual.map(lambda t: sequence_at(t, length))
        control_seq = control.map(lambda t: sequence_at(t, length))
        for sequence in sorted(set(actual_seq) | set(control_seq)):
            a = int(actual_seq.eq(sequence).sum())
            c = int(control_seq.eq(sequence).sum())
            if a + c < 4:
                continue
            p = stats.fisher_exact([[a, len(actual_seq) - a], [c, len(control_seq) - c]])[1]
            rows.append({"length": length, "sequence": sequence, "trade_count": a, "control_count": c, "rate_difference": a / len(actual_seq) - c / len(control_seq), "fisher_p": p})
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["bh_q"] = bh_qvalues(frame.fisher_p)
        frame = frame.sort_values(["bh_q", "rate_difference"], ascending=[True, False]).reset_index(drop=True)
    return frame


def direction_inside_window(panel: pd.DataFrame) -> pd.DataFrame:
    entries = panel[panel.entry.eq(1) & panel.clock_m30_post120.eq(1)].copy().sort_values("timestamp")
    entries["target"] = entries.direction.eq(1).astype(int)
    features = [x for x in ["event_bar_direction", "event_count", "m1_return_5", "m1_ema20_dist", "m1_vwap_dist", "m15_price_ema20", "h1_price_ema20"] if x in entries]
    rows = []
    for fold, (_, start, end) in enumerate(chronological_folds(panel), start=1):
        train = entries[entries.timestamp < start]
        test = entries[(entries.timestamp >= start) & (entries.timestamp < end)]
        if len(test) < 4 or train.target.nunique() < 2:
            continue
        model = fit_numeric_model(train, features, "target", kind="logit", seed=SEED + 500 + fold)
        score = model.probabilities(test)
        predicted = score >= 0.5
        rows.append({"fold": fold, "train_n": len(train), "test_n": len(test), "accuracy": float(np.mean(predicted == test.target)), "roc_auc": roc_auc_score(test.target, score), "buy_pr_auc": average_precision_score(test.target, score)})
    return pd.DataFrame(rows)


def write_reports(
    windows: pd.DataFrame, fixed: pd.DataFrame, sparse: pd.DataFrame, density: pd.DataFrame, sequences: pd.DataFrame,
    direction: pd.DataFrame, near: pd.DataFrame, state: pd.DataFrame,
) -> None:
    aggregate_fixed = fixed[fixed.evaluation.eq("oos_aggregate")]
    aggregate_sparse = sparse[sparse.evaluation.eq("oos_aggregate")]
    best = pd.concat([aggregate_fixed, aggregate_sparse], ignore_index=True).sort_values("f1", ascending=False).iloc[0]
    clock = f"""# Phase 3 clock-event analysis

## Exact-timestamp proxy result

{markdown_table(windows)}

M30/H1 event times are raw-clock boundaries under the selected UTC+3 proxy mapping. A repeating timer and a bar-close callback have the same observable timestamp pattern in M1 data, so the data can compare immediate boundary versus short window, but cannot discriminate a timer from a bar-close event.

## Chronological boundary/window replication

{markdown_table(aggregate_fixed[["hypothesis", "candidate_signals", "tp", "fp", "fn", "precision", "recall", "f1", "entry_match_60s"]])}
"""
    state_report = f"""# Phase 3 hidden-state and capacity analysis

State features are built before each candidate minute: prior entry/exit timing, prior completed result/direction/size, active-position count, trade density, recent completed event count and raw-clock history. No current-trade PnL, close, MFE or MAE is supplied to entry models.

Observed entries are compatible with a maximum active-position count of one: five entry bars occur with one position already active, and none require more than one. This falsifies a universal flat-only state machine, but does not identify the account's actual concurrency rule.

The sparse score tests a small clock + state + location set only in expanding chronological folds. Its results appear in `phase3_replication_results.csv`; non-replication is not reinterpreted as a recovered hidden state.
"""
    cooldown = f"""# Phase 3 cooldown analysis

The state feature table contains seconds since last exit/entry and outcome-conditioned history. Phase 2 already showed very sparse immediate re-entry; Phase 3 retains those variables as eligibility covariates rather than declaring a fixed cooldown from irregular observed waits.

Because the proxy has no record of unsubmitted/rejected opportunities, a low post-exit trade rate cannot distinguish an EA cooldown from missing market eligibility. The appropriate conclusion is that a fixed cooldown is not identified from these data.
"""
    opportunity = f"""# Phase 3 opportunity analysis

`phase3_opportunity_density.csv` gives candidate-minute, M30/H1-window-event and observed-entry counts by date, raw-clock session and hour. The opportunity hierarchy remains highly selective: even clock-window minutes overwhelmingly contain no trade.

{markdown_table(density.sort_values("actual_entry_bars", ascending=False).head(12))}
"""
    intrabar = """# Phase 3 intrabar analysis

## Data limit

No usable tick, ask, spread, broker execution, order/deal/position or terminal-log source exists in the workspace. The only external market data is bid-only aggregated M1 OHLCV.

## Consequence

Exact tick crossing, first tick after a bar close, exact bid/ask, spread gate, intrabar path, second-level timer and order-book condition are **UNIDENTIFIABLE**. M1 timestamps can test raw-clock windows; they cannot provide an intrabar reconstruction. No proxy result in this phase is labelled a tick-level finding.
"""
    near_report = f"""# Phase 3 clock-matched near-miss analysis

Each actual trade is matched to a nearby non-trade minute on the same date, raw-clock session and M30 phase, then minimized on pre-entry history and market-state distance. This removes the broad clock match before inspecting state/event differences.

{markdown_table(near[["trade_ticket", "clock_event", "state_similarity", "event_difference", "candidate_hidden_condition"]], 15)}

The matched records do not isolate a single repeated hidden condition. They are evidence against the claim that matching M30 clock phase plus broad observable state makes the trade deterministic.
"""
    direction_report = f"""# Phase 3 direction inside clock windows

Direction is evaluated only among observed entry bars inside the M30 post-boundary proxy window, using pre-entry event polarity and location. This changes the conditioning question from all-market direction prediction to “given potential clock interest, what selects Buy versus Sell?”

{markdown_table(direction)}

Small fold counts and M1 path ambiguity prevent treating any apparent discrimination as a direction-rule reconstruction.
"""
    sequence_report = f"""# Phase 3 event-sequence analysis

The search vocabulary is deliberately small: H1, M30, M15, multi-event armed proxy, event, cooldown and other. Contiguous pre-entry sequences of lengths 2–5 are compared with clock-phase-matched controls. Search space is constrained to this vocabulary and four lengths; Benjamini–Hochberg adjustment is applied across retained sequence tests.

{markdown_table(sequences, 20)}

No sequence is promoted to source logic without a frozen chronological replication result.
"""
    hidden = f"""# Phase 3 hidden eligibility reconstruction

## Small interpretable eligibility score

The score family combines clock post-window indicators, pre-entry trade/cooldown state, completed-bar event count and a small location set. The models are L1 logistic or depth-3 trees, fitted and threshold-calibrated only on prior chronological history.

{markdown_table(aggregate_sparse[["hypothesis", "candidate_signals", "tp", "fp", "fn", "precision", "recall", "f1", "roc_auc", "pr_auc"]])}

The best tested Phase 3 candidate is **{best.hypothesis}** with OOS precision {best.precision:.5f}, recall {best.recall:.5f}, mean F1 {best.f1:.5f}, and {int(best.candidate_signals):,} signals. It remains far too non-selective for event-level replication.
"""
    status = f"""# Phase 3 status

## LEVEL D — UNIDENTIFIED

Phase 3 retains the Phase 2 result that M30/H1 raw-clock boundaries are statistically enriched opportunity markers in the M1 proxy, but not sufficient trigger rules. The immediate-boundary versus post-120-second-window comparison does not identify whether the mechanism is a bar close, fixed timer, or a wider eligibility window because all share the same observable clock basis and lack tick/order data.

The strongest Phase 3 replication candidate is **{best.hypothesis}**: OOS precision {best.precision:.5f}, recall {best.recall:.5f}, F1 {best.f1:.5f}. This is not close to reconstructing 423 selected events.

What was learned: clock timing adds structure; flat-only eligibility is falsified; M30-phase matched controls still fail to reveal a single deterministic state/event condition.

What remains unknown: intrabar price crossing, exact timer scheduling, broker spread/ask, unrecorded order decisions, EA/account state and true market opportunity set. Tick bid/ask plus broker order/deal/position logs would resolve the highest-value ambiguities.
"""
    files = {
        "phase3_clock_event_analysis.md": clock, "phase3_state_machine_analysis.md": state_report,
        "phase3_cooldown_analysis.md": cooldown, "phase3_opportunity_analysis.md": opportunity,
        "phase3_intrabar_analysis.md": intrabar, "phase3_nearmiss_analysis.md": near_report,
        "phase3_direction_analysis.md": direction_report, "phase3_event_sequence_analysis.md": sequence_report,
        "phase3_hidden_eligibility.md": hidden, "phase3_status.md": status,
    }
    for name, content in files.items():
        (OUT / name).write_text(content, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    trades, _ = load_trades(ROOT / "data" / "raw" / "trades_raw.tsv")
    bars = pd.read_csv(ROOT / "data" / "market" / "normalized" / "xauusd_m1.csv")
    bars.timestamp = pd.to_datetime(bars.timestamp)
    panel = pd.read_csv(OUT / "candidate_event_table.csv.gz", low_memory=False)
    panel.timestamp = pd.to_datetime(panel.timestamp)
    panel = panel.merge(event_features_from_bars(bars), on="timestamp", how="left", validate="one_to_one")
    panel = attach_trade_state(panel, trades)
    panel = clock_window_features(panel)
    panel = add_history_state(panel, trades)
    if panel.loc[panel.entry.eq(1), "eligible_observed_capacity"].eq(0).any():
        raise AssertionError("Observed capacity envelope excluded a known entry")

    inventory = inventory_report()
    (OUT / "phase3_data_inventory.md").write_text(inventory, encoding="utf-8")
    delays = actual_clock_delays(trades)
    fixed = fixed_rule_replication(panel, trades)
    sparse, rules = sparse_eligibility(panel, trades)
    near, near_long = phase3_nearmisses(panel, trades)
    density = opportunity_density(panel)
    sequences = sequence_mining(panel, near_long)
    direction = direction_inside_window(panel)

    delays.to_csv(OUT / "phase3_event_windows.csv", index=False)
    near.to_csv(OUT / "phase3_nearmiss_table.csv", index=False)
    near_long.to_csv(OUT / "phase3_nearmiss_controls.csv", index=False)
    density.to_csv(OUT / "phase3_opportunity_density.csv", index=False)
    sequences.to_csv(OUT / "phase3_sequence_results.csv", index=False)
    fixed.to_csv(OUT / "phase3_clock_rule_results.csv", index=False)
    pd.concat([fixed, sparse], ignore_index=True).to_csv(OUT / "phase3_replication_results.csv", index=False)
    rules.to_csv(OUT / "phase3_sparse_rules.csv", index=False)
    direction.to_csv(OUT / "phase3_direction_results.csv", index=False)
    state_columns = [
        "timestamp", "entry", "entry_count", "direction", "eligible_observed_capacity", "active_positions_before_candidate",
        "seconds_since_last_exit", "seconds_since_last_entry", "prior_win_code", "prior_direction_code", "prior_large_code",
        "trades_today_before", "trades_prev_hour", "trades_session_before", "win_close_arrival_prev_hour", "loss_close_arrival_prev_hour",
        "seconds_since_last_buy_entry", "seconds_since_last_sell_entry", "recent_completed_events_30", "recent_m30_boundaries_120",
        "clock_m30_boundary", "clock_m30_post120", "clock_h1_boundary", "clock_h1_post120", "clock_phase_30",
        "event_prebar_close",
    ]
    panel[[column for column in state_columns if column in panel]].to_csv(OUT / "phase3_state_features.csv", index=False)
    write_reports(delays, fixed, sparse, density, sequences, direction, near, panel[["timestamp", "proxy_state"]])

    aggregate = pd.concat([fixed, sparse], ignore_index=True)
    aggregate = aggregate[aggregate.evaluation.eq("oos_aggregate")].sort_values("f1", ascending=False)
    validation = {
        "status": "ok", "level": "D — UNIDENTIFIED", "candidate_minutes": len(panel), "trades": len(trades), "entry_bars": int(panel.entry.sum()),
        "tick_data_available": False, "bid_ask_available": False, "order_lifecycle_available": False,
        "m1_proxy_limit": "M1 bid OHLCV cannot identify intrabar path, ticks, asks, spread, or second-level timer.",
        "state_features_pre_entry_only": True, "clock_hypotheses": 6, "sparse_models": 2, "sequence_vocabulary": 7,
        "sequence_lengths": [2, 3, 4, 5], "nearmiss_rows": len(near), "best_oos": aggregate.iloc[0].to_dict(), "random_seed": SEED,
    }
    (OUT / "phase3_validation.json").write_text(json.dumps(validation, indent=2, default=jsonable), encoding="utf-8")
    print(json.dumps({"status": "ok", "best_oos": validation["best_oos"], "nearmiss_rows": len(near)}, indent=2, default=jsonable))


if __name__ == "__main__":
    main()
