"""Phase 2: event / eligibility reconstruction on the preserved M1 proxy.

This is deliberately a falsification-oriented continuation of Phase 1.  All
market features at candidate minute T are generated from a bar that completed
before T.  The external series is bid-only M1, so no result is interpreted as
evidence of a tick, ask, spread, or exact-second broker trigger.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.tree import DecisionTreeClassifier, export_text

from reverse_trade.pipeline import load_trades
try:  # Supports both `python scripts/...` and package-style test imports.
    from scripts.continue_identification import (
        NumericModel, calibrated_fit, chronological_folds, fit_numeric_model, nearest_errors,
    )
except ModuleNotFoundError:
    from continue_identification import (
        NumericModel, calibrated_fit, chronological_folds, fit_numeric_model, nearest_errors,
    )


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"
SEED = 20260920
EVENT_PREFIX = "event_"
EVENT_NONFLAGS = {"event_count", "event_any", "event_range_expansion_strength", "event_body_ratio", "event_bar_direction", "event_prebar_close", "event_prebar_high", "event_prebar_low"}


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


def bh_qvalues(values: pd.Series) -> pd.Series:
    """Benjamini-Hochberg adjustment, retaining missing p-values."""
    output = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.dropna()
    if valid.empty:
        return output
    order = np.argsort(valid.to_numpy())
    ranked = valid.to_numpy()[order]
    adjusted = np.minimum.accumulate((ranked * len(ranked) / np.arange(1, len(ranked) + 1))[::-1])[::-1]
    positioned = np.empty(len(ranked))
    positioned[order] = np.minimum(adjusted, 1.0)
    output.loc[valid.index] = positioned
    return output


def session_bucket(timestamp: pd.Series) -> pd.Series:
    """Raw-clock buckets only; these are not asserted broker sessions."""
    hour = timestamp.dt.hour
    return pd.cut(hour, [-1, 6, 12, 17, 23], labels=["00-06", "07-12", "13-17", "18-23"])


def event_flag_columns(frame: pd.DataFrame) -> list[str]:
    return [
        column for column in frame.columns
        if column.startswith(EVENT_PREFIX) and column not in EVENT_NONFLAGS
    ]


def event_features_from_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Describe completed-bar events and timestamp them at bar completion.

    A source bar labelled 10:00 has completed at 10:01.  Thus its event row is
    only joined to candidate minute 10:01 or later.
    """
    source = bars.copy().sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    timestamp = pd.to_datetime(source["timestamp"])
    open_ = source["open"].astype(float)
    high = source["high"].astype(float)
    low = source["low"].astype(float)
    close = source["close"].astype(float)
    volume = source["volume"].astype(float)
    rng = high - low
    body = close - open_
    previous_close = close.shift(1)
    day = timestamp.dt.floor("D")
    prior_high_10 = high.rolling(10, min_periods=10).max().shift(1)
    prior_low_10 = low.rolling(10, min_periods=10).min().shift(1)
    prior_high_20 = high.rolling(20, min_periods=20).max().shift(1)
    prior_low_20 = low.rolling(20, min_periods=20).min().shift(1)
    prior_session_high = high.groupby(day).transform(lambda s: s.cummax().shift(1))
    prior_session_low = low.groupby(day).transform(lambda s: s.cummin().shift(1))
    rolling_median_range = rng.rolling(20, min_periods=10).median().shift(1)
    rolling_q25_range = rng.rolling(20, min_periods=10).quantile(0.25).shift(1)
    range_expansion = rng / rolling_median_range.replace(0, np.nan)
    typical = (high + low + close) / 3
    vwap = (typical * volume).groupby(day).cumsum() / volume.groupby(day).cumsum().replace(0, np.nan)
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()

    cross_high_10 = (close > prior_high_10) & (previous_close <= prior_high_10)
    cross_low_10 = (close < prior_low_10) & (previous_close >= prior_low_10)
    cross_high_20 = (close > prior_high_20) & (previous_close <= prior_high_20)
    cross_low_20 = (close < prior_low_20) & (previous_close >= prior_low_20)
    cross_session_high = (close > prior_session_high) & (previous_close <= prior_session_high)
    cross_session_low = (close < prior_session_low) & (previous_close >= prior_session_low)
    above_vwap = close >= vwap
    above_ema20 = close >= ema20
    cross_vwap = above_vwap.ne(above_vwap.shift(1))
    cross_ema20 = above_ema20.ne(above_ema20.shift(1))
    body_ratio = body.abs() / rng.replace(0, np.nan)
    direction = np.sign(body).fillna(0)
    small = rng <= rolling_q25_range
    large_impulse = (range_expansion >= 1.8) & (body_ratio >= 0.60)
    prior_small_1 = small.astype(bool).shift(1, fill_value=False)
    prior_small_2 = small.astype(bool).shift(2, fill_value=False)
    prior_impulse_2 = large_impulse.astype(bool).shift(2, fill_value=False)
    prior_impulse_1 = large_impulse.astype(bool).shift(1, fill_value=False)
    compression_to_expansion = prior_small_1 & prior_small_2 & large_impulse
    higher_low_break = (low > low.shift(1)) & cross_high_10
    lower_high_break = (high < high.shift(1)) & cross_low_10
    false_break_high = (high > prior_high_10) & (close <= prior_high_10)
    false_break_low = (low < prior_low_10) & (close >= prior_low_10)
    impulse_pullback_cont_up = (
        (direction.shift(2) > 0) & prior_impulse_2
        & (direction.shift(1) < 0) & (close > high.shift(2))
    )
    impulse_pullback_cont_down = (
        (direction.shift(2) < 0) & prior_impulse_2
        & (direction.shift(1) > 0) & (close < low.shift(2))
    )
    immediate_reversal = (direction.ne(direction.shift(1))) & large_impulse & prior_impulse_1
    out = pd.DataFrame(
        {
            "timestamp": timestamp + pd.Timedelta(minutes=1),
            "event_cross_prior_high_10": cross_high_10.astype("int8"),
            "event_cross_prior_low_10": cross_low_10.astype("int8"),
            "event_cross_prior_high_20": cross_high_20.astype("int8"),
            "event_cross_prior_low_20": cross_low_20.astype("int8"),
            "event_cross_session_high": cross_session_high.astype("int8"),
            "event_cross_session_low": cross_session_low.astype("int8"),
            "event_cross_vwap": cross_vwap.astype("int8"),
            "event_cross_ema20": cross_ema20.astype("int8"),
            "event_large_body_expansion": large_impulse.astype("int8"),
            "event_compression_to_expansion": compression_to_expansion.astype("int8"),
            "event_higher_low_break": higher_low_break.astype("int8"),
            "event_lower_high_break": lower_high_break.astype("int8"),
            "event_false_break_high": false_break_high.astype("int8"),
            "event_false_break_low": false_break_low.astype("int8"),
            "event_impulse_pullback_cont_up": impulse_pullback_cont_up.astype("int8"),
            "event_impulse_pullback_cont_down": impulse_pullback_cont_down.astype("int8"),
            "event_immediate_reversal": immediate_reversal.astype("int8"),
            "event_range_expansion_strength": range_expansion.astype("float32"),
            "event_body_ratio": body_ratio.astype("float32"),
            "event_bar_direction": direction.astype("float32"),
            "event_prebar_close": close.astype("float32"),
            "event_prebar_high": high.astype("float32"),
            "event_prebar_low": low.astype("float32"),
        }
    )
    binary = event_flag_columns(out)
    out["event_count"] = out[binary].sum(axis=1).astype("int8")
    out["event_any"] = (out["event_count"] > 0).astype("int8")
    return out


def attach_trade_state(panel: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """Attach only information available before each candidate minute."""
    result = panel.copy().sort_values("timestamp").reset_index(drop=True)
    result["raw_clock_session"] = session_bucket(result["timestamp"]).astype(str)
    ordered = trades.sort_values("open_time").reset_index(drop=True).copy()
    ordered["prior_direction_code"] = np.where(ordered["side"].eq("Buy"), 1, -1)
    ordered["prior_win_code"] = ordered["win"].astype(int)
    ordered["prior_large_code"] = (ordered["lot_size"] > 0.01).astype(int)
    left = result[["timestamp"]].copy()
    close_info = ordered[["close_time", "prior_direction_code", "prior_win_code", "prior_large_code", "pnl"]].rename(
        columns={"close_time": "state_time", "pnl": "previous_realized_pnl"}
    )
    prior_close = pd.merge_asof(
        left, close_info.sort_values("state_time"), left_on="timestamp", right_on="state_time", direction="backward",
        allow_exact_matches=False,
    )
    prior_open = pd.merge_asof(
        left,
        ordered[["open_time", "prior_direction_code"]].rename(columns={"open_time": "last_open_time", "prior_direction_code": "last_open_direction"}).sort_values("last_open_time"),
        left_on="timestamp", right_on="last_open_time", direction="backward", allow_exact_matches=False,
    )
    result["seconds_since_last_exit"] = (result["timestamp"] - prior_close["state_time"]).dt.total_seconds()
    result["seconds_since_last_entry"] = (result["timestamp"] - prior_open["last_open_time"]).dt.total_seconds()
    result["prior_win_code"] = prior_close["prior_win_code"].fillna(-1).astype("int8")
    result["prior_direction_code"] = prior_close["prior_direction_code"].fillna(0).astype("int8")
    result["prior_large_code"] = prior_close["prior_large_code"].fillna(0).astype("int8")
    result["previous_realized_pnl"] = prior_close["previous_realized_pnl"]
    opens = ordered["open_time"].astype("int64").to_numpy()
    closes = ordered["close_time"].astype("int64").to_numpy()
    times = result["timestamp"].astype("int64").to_numpy()
    result["active_positions_before_candidate"] = (
        np.searchsorted(opens, times, side="right") - np.searchsorted(closes, times, side="right")
    ).astype("int16")
    result["eligible_no_active_position"] = result["active_positions_before_candidate"].eq(0).astype("int8")
    # Five observed entry bars occur while one position is already open.  The
    # observed capacity envelope therefore permits zero or one active position;
    # it is an audit constraint, not an asserted original-EA setting.
    observed_capacity = int(result.loc[result["entry"].eq(1), "active_positions_before_candidate"].max())
    result["eligible_observed_capacity"] = result["active_positions_before_candidate"].le(observed_capacity).astype("int8")
    result["cooldown_log_seconds"] = np.log1p(result["seconds_since_last_exit"].clip(lower=0))
    result["cooldown_bin"] = pd.cut(
        result["seconds_since_last_exit"],
        [-np.inf, 5, 15, 30, 60, 120, 300, 600, 1800, np.inf],
        labels=["0-5s", "5-15s", "15-30s", "30-60s", "1-2m", "2-5m", "5-10m", "10-30m", ">30m"],
    ).astype(str)
    result["proxy_state_before_entry"] = np.select(
        [
            result["active_positions_before_candidate"].gt(0),
            result["seconds_since_last_exit"].between(0, 300, inclusive="both"),
            result["event_count"].ge(2),
            result["event_count"].eq(1),
        ],
        ["IN_TRADE", "COOLDOWN", "ARMED_PROXY", "SETUP_PROXY"],
        default="WATCHING_PROXY",
    )
    result["proxy_state"] = result["proxy_state_before_entry"]
    result.loc[result["entry"].eq(1), "proxy_state"] = "TRIGGERED_OBSERVED"
    return result


def baseline_columns(panel: pd.DataFrame) -> list[str]:
    columns = [
        "m1_atr_ratio", "m1_range", "m1_return_5", "m1_ema20_dist", "m1_range_percentile_240",
        "m15_price_ema20", "h1_price_ema20", "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    ]
    return [column for column in columns if column in panel.columns]


def true_event_signature(row: pd.Series, flags: list[str]) -> str:
    names = [flag.removeprefix(EVENT_PREFIX) for flag in flags if int(row.get(flag, 0) or 0) == 1]
    return ", ".join(names) if names else "none of the measured completed-bar events"


def matched_nearmisses(panel: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """For each trade, select one similar prior and subsequent non-trade minute."""
    candidates = panel[panel["eligible_observed_capacity"].eq(1) & panel["entry"].eq(0)].copy()
    candidates["date"] = candidates["timestamp"].dt.floor("D")
    candidates["session"] = candidates["raw_clock_session"].astype(str)
    columns = baseline_columns(panel)
    values = panel[columns].to_numpy(dtype=float)
    median = np.nanmedian(values, axis=0)
    scale = np.nanstd(values, axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 1e-10), scale, 1.0)
    flags = event_flag_columns(panel)
    compare_flags = flags + [column for column in ["boundary_5", "boundary_15", "boundary_30", "boundary_60"] if column in panel]
    lookup = panel.set_index("timestamp", drop=False)
    all_rows: list[dict[str, Any]] = []
    control_rows: list[dict[str, Any]] = []
    ordered = trades.sort_values("open_time")
    for trade in ordered.itertuples(index=False):
        event_time = pd.Timestamp(trade.open_time).floor("min")
        if event_time not in lookup.index:
            continue
        observed = lookup.loc[event_time]
        day = event_time.floor("D")
        session = str(observed["raw_clock_session"])
        target = observed[columns].to_numpy(dtype=float)
        target = np.where(np.isfinite(target), target, median)
        base = candidates[candidates["date"].eq(day) & candidates["session"].eq(session)]
        base = base[(base["timestamp"] - event_time).abs().between(pd.Timedelta(minutes=2), pd.Timedelta(minutes=120))]
        if base.empty:
            base = candidates[candidates["date"].eq(day)]
            base = base[(base["timestamp"] - event_time).abs().between(pd.Timedelta(minutes=2), pd.Timedelta(minutes=240))]
        selected: dict[str, pd.Series | None] = {"before": None, "after": None}
        for role, pool in {
            "before": base[base["timestamp"] < event_time],
            "after": base[base["timestamp"] > event_time],
        }.items():
            if pool.empty:
                continue
            array = pool[columns].to_numpy(dtype=float)
            array = np.where(np.isfinite(array), array, median)
            distance = np.sqrt(np.mean(((array - target) / scale) ** 2, axis=1))
            selected[role] = pool.iloc[int(np.argmin(distance))]
        row: dict[str, Any] = {
            "ticket": str(trade.ticket),
            "observed_timestamp": trade.open_time,
            "observed_entry_minute": event_time,
            "observed_direction": trade.side,
            "observed_price": trade.observed_price,
            "observed_event_signature": true_event_signature(observed, flags),
            "observed_event_count": int(observed["event_count"]),
            "observed_proxy_state": observed["proxy_state"],
        }
        for role, control in selected.items():
            if control is None:
                row[f"{role}_candidate_timestamp"] = pd.NaT
                row[f"{role}_state_similarity"] = np.nan
                row[f"{role}_event_sequence_similarity"] = np.nan
                row[f"{role}_key_differences"] = "no same-day matched M1 control"
                row[f"{role}_candidate_hidden_trigger"] = "unavailable"
                continue
            vector = control[columns].to_numpy(dtype=float)
            vector = np.where(np.isfinite(vector), vector, median)
            distance = float(np.sqrt(np.mean(((vector - target) / scale) ** 2)))
            matches = np.mean([int(observed[flag]) == int(control[flag]) for flag in flags]) if flags else np.nan
            differing_flags = [flag.removeprefix(EVENT_PREFIX) for flag in flags if int(observed[flag]) != int(control[flag])]
            continuous_delta = pd.Series(np.abs((vector - target) / scale), index=columns).sort_values(ascending=False).head(3)
            differences = differing_flags[:4] + [f"{name} Δz={value:.2f}" for name, value in continuous_delta.items() if value > 0.1]
            trade_only = [flag.removeprefix(EVENT_PREFIX) for flag in flags if int(observed[flag]) == 1 and int(control[flag]) == 0]
            row[f"{role}_candidate_timestamp"] = control["timestamp"]
            row[f"{role}_state_similarity"] = distance
            row[f"{role}_event_sequence_similarity"] = matches
            row[f"{role}_key_differences"] = "; ".join(differences[:7]) if differences else "no measured difference"
            row[f"{role}_candidate_hidden_trigger"] = ", ".join(trade_only[:4]) if trade_only else "none isolated"
            control_row = {
                "ticket": str(trade.ticket), "role": role, "observed_timestamp": trade.open_time,
                "observed_entry_minute": event_time, "control_timestamp": control["timestamp"],
                "state_similarity": distance, "event_sequence_similarity": matches,
            }
            for flag in compare_flags:
                control_row[f"observed_{flag}"] = int(observed[flag])
                control_row[f"control_{flag}"] = int(control[flag])
            control_rows.append(control_row)
        all_rows.append(row)
    return pd.DataFrame(all_rows), pd.DataFrame(control_rows)


def matched_feature_tests(controls: pd.DataFrame) -> pd.DataFrame:
    flags = sorted({
        column.removeprefix("observed_") for column in controls.columns
        if (column.startswith("observed_event_") or column.startswith("observed_boundary_"))
        and f"control_{column.removeprefix('observed_')}" in controls.columns
    })
    rng = np.random.default_rng(SEED + 42)
    rows = []
    for flag in flags:
        observed = controls.groupby("ticket")[f"observed_{flag}"].first()
        control = controls.groupby("ticket")[f"control_{flag}"].mean().reindex(observed.index)
        effect = float(observed.mean() - control.mean())
        values = controls.groupby("ticket").agg({f"observed_{flag}": "first", f"control_{flag}": list})
        values = values[values[f"control_{flag}"].map(len).eq(2)]
        matrix = np.asarray(
            [[row[f"observed_{flag}"], *row[f"control_{flag}"]] for _, row in values.iterrows()], dtype=float
        )
        # Under the matched null, any one of the three moments could be the
        # labelled trade.  Vectorizing all draws avoids row-by-row Monte Carlo.
        choices = rng.integers(0, 3, size=(2_000, len(matrix)))
        selected = matrix[np.arange(len(matrix))[None, :], choices]
        simulated = (selected - (matrix.sum(axis=1)[None, :] - selected) / 2).mean(axis=1)
        p_value = float((1 + np.sum(np.abs(simulated) >= abs(effect))) / (len(simulated) + 1))
        rows.append({
            "event_feature": flag, "trade_rate": float(observed.mean()), "matched_control_rate": float(control.mean()),
            "paired_rate_difference": effect, "trade_n": int(len(observed)), "permutation_p": p_value,
        })
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["bh_q"] = bh_qvalues(frame["permutation_p"])
        frame = frame.sort_values(["bh_q", "paired_rate_difference"], ascending=[True, False]).reset_index(drop=True)
    return frame


def clock_analysis(panel: pd.DataFrame, matched_tests: pd.DataFrame) -> pd.DataFrame:
    eligible = panel[panel["eligible_observed_capacity"].eq(1)].copy()
    rows = []
    for column in ["boundary_5", "boundary_15", "boundary_30", "boundary_60"]:
        event = eligible[eligible[column].eq(1)]
        non_event = eligible[eligible[column].eq(0)]
        rate_event = event["entry"].mean()
        rate_non_event = non_event["entry"].mean()
        match = matched_tests[matched_tests["event_feature"].eq(column)]
        rows.append({
            "clock_event": column, "eligible_event_minutes": len(event), "entry_bars_on_event": int(event["entry"].sum()),
            "trade_rate_event": rate_event, "trade_rate_non_event": rate_non_event,
            "rate_ratio_event_vs_non_event": rate_event / rate_non_event if rate_non_event else np.nan,
            "matched_permutation_p": float(match["permutation_p"].iloc[0]) if len(match) else np.nan,
            "matched_bh_q": float(match["bh_q"].iloc[0]) if len(match) else np.nan,
        })
    return pd.DataFrame(rows)


def sparse_tree_fit(train: pd.DataFrame, columns: list[str], seed: int) -> tuple[NumericModel, float]:
    """A bounded depth-3 rule tree with inner chronological threshold selection."""
    split = max(int(len(train) * 0.80), 1)
    fit_part = train.iloc[:split]
    calibration = train.iloc[split:]
    generator = np.random.default_rng(seed)

    def fit(frame: pd.DataFrame) -> NumericModel:
        positive = frame.index[frame["entry"].eq(1)].to_numpy()
        negative = frame.index[frame["entry"].eq(0)].to_numpy()
        chosen_negative = generator.choice(negative, size=min(len(negative), max(50 * len(positive), 1)), replace=False)
        chosen = np.concatenate([positive, chosen_negative])
        work = frame.loc[chosen]
        values = work[columns].to_numpy(dtype=float)
        median = np.nanmedian(values, axis=0)
        median = np.where(np.isfinite(median), median, 0.0)
        values = np.where(np.isfinite(values), values, median)
        estimator = DecisionTreeClassifier(max_depth=3, min_samples_leaf=12, class_weight="balanced", random_state=seed)
        estimator.fit(values, work["entry"])
        return NumericModel(estimator, median, np.zeros(len(columns)), np.ones(len(columns)), False, columns)

    first = fit(fit_part)
    scores = first.probabilities(calibration)
    options = np.unique(np.quantile(scores, np.linspace(0.70, 0.995, 80)))
    candidates = [(f1_score(calibration["entry"], scores >= threshold, zero_division=0), threshold) for threshold in options]
    threshold = float(max(candidates, key=lambda item: item[0])[1]) if candidates else 0.5
    return fit(train), threshold


def event_replication(panel: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    flags = event_flag_columns(panel)
    event_numeric = ["event_count", "event_range_expansion_strength", "event_body_ratio", "event_bar_direction"]
    state = [
        "cooldown_log_seconds", "seconds_since_last_entry", "prior_win_code", "prior_direction_code", "prior_large_code",
        "boundary_5", "boundary_15", "boundary_30", "boundary_60", "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    ]
    location = ["m1_ema20_dist", "m1_vwap_dist", "m1_range_percentile_240", "m15_price_ema20", "h1_price_ema20"]
    specifications = {
        "E1 completed-bar events": (flags + event_numeric, "l1"),
        "E2 events + eligibility state": (flags + event_numeric + state, "l1"),
        "E3 constrained event tree": (flags + event_numeric + state + location, "tree"),
    }
    data = panel[panel["eligible_observed_capacity"].eq(1)].copy().sort_values("timestamp")
    data["seconds_since_last_entry"] = data["seconds_since_last_entry"].clip(lower=0)
    folds = chronological_folds(panel)
    fold_rows: list[dict[str, Any]] = []
    rule_rows: list[dict[str, Any]] = []
    for model_name, (columns, kind) in specifications.items():
        columns = [column for column in columns if column in data.columns]
        for fold, (_, test_start, test_end) in enumerate(folds, start=1):
            train = data[data["timestamp"] < test_start]
            test = data[(data["timestamp"] >= test_start) & (data["timestamp"] < test_end)]
            if train["entry"].sum() < 5 or test["entry"].sum() == 0:
                continue
            model, threshold = sparse_tree_fit(train, columns, SEED + fold) if kind == "tree" else calibrated_fit(train, columns, kind=kind, seed=SEED + fold)
            scores = model.probabilities(test)
            predicted = scores >= threshold
            actual = test["entry"].to_numpy(dtype=int)
            test_trades = trades[(trades["open_time"] >= test_start) & (trades["open_time"] < test_end)]
            errors = nearest_errors(test_trades["open_time"], test.loc[predicted, "timestamp"])
            if test["entry"].sum() >= 4 and train["entry"].sum() >= 4:
                direction_train = train[train["entry"].eq(1)].copy()
                direction_train["direction_target"] = direction_train["direction"].eq(1).astype(int)
                direction_model = fit_numeric_model(direction_train, columns, "direction_target", kind="logit", seed=SEED + 600 + fold)
                predicted_direction = np.where(direction_model.probabilities(test) >= 0.5, 1, -1)
                matched = predicted & (actual == 1)
                direction_accuracy = float(np.mean(predicted_direction[matched] == test.loc[matched, "direction"].to_numpy())) if matched.any() else np.nan
            else:
                direction_accuracy = np.nan
            row = {
                "evaluation": "oos_fold", "model": model_name, "fold": fold,
                "train_entry_bars": int(train["entry"].sum()), "test_entry_bars": int(actual.sum()),
                "candidate_signals": int(predicted.sum()), "tp": int(np.sum(predicted & (actual == 1))),
                "fp": int(np.sum(predicted & (actual == 0))), "fn": int(np.sum(~predicted & (actual == 1))),
                "precision": precision_score(actual, predicted, zero_division=0), "recall": recall_score(actual, predicted, zero_division=0),
                "f1": f1_score(actual, predicted, zero_division=0), "roc_auc": roc_auc_score(actual, scores),
                "pr_auc": average_precision_score(actual, scores), "direction_accuracy_matched": direction_accuracy,
                "entry_match_1s": float(np.mean(errors <= 1)) if len(errors) else np.nan,
                "entry_match_2s": float(np.mean(errors <= 2)) if len(errors) else np.nan,
                "entry_match_5s": float(np.mean(errors <= 5)) if len(errors) else np.nan,
                "entry_match_10s": float(np.mean(errors <= 10)) if len(errors) else np.nan,
                "entry_match_15s": float(np.mean(errors <= 15)) if len(errors) else np.nan,
                "entry_match_30s": float(np.mean(errors <= 30)) if len(errors) else np.nan,
                "entry_match_60s": float(np.mean(errors <= 60)) if len(errors) else np.nan,
                "entry_match_one_m1_bar": float(np.mean(errors <= 119)) if len(errors) else np.nan,
                "threshold": threshold, "feature_count": len(columns), "complexity": "depth-3 tree" if kind == "tree" else "L1 logistic",
            }
            fold_rows.append(row)
            if kind == "tree":
                rule_rows.append({
                    "model": model_name, "fold": fold, "rule_type": "depth-3 tree", "rule_or_feature": export_text(model.estimator, feature_names=columns),
                    "coefficient": np.nan, "threshold": threshold, "oos_f1": row["f1"], "oos_precision": row["precision"],
                })
            else:
                coefficients = model.estimator.coef_.ravel()
                for feature, coefficient in zip(columns, coefficients):
                    if abs(coefficient) > 1e-8:
                        rule_rows.append({
                            "model": model_name, "fold": fold, "rule_type": "L1 logistic feature",
                            "rule_or_feature": feature, "coefficient": float(coefficient), "threshold": threshold,
                            "oos_f1": row["f1"], "oos_precision": row["precision"],
                        })
    folds_frame = pd.DataFrame(fold_rows)
    summaries = []
    for model_name, part in folds_frame.groupby("model"):
        totals = part[["tp", "fp", "fn"]].sum()
        summary = {
            "evaluation": "oos_aggregate", "model": model_name, "fold": "all",
            "train_entry_bars": np.nan, "test_entry_bars": int(totals["tp"] + totals["fn"]),
            "candidate_signals": int(totals["tp"] + totals["fp"]), "tp": int(totals["tp"]), "fp": int(totals["fp"]), "fn": int(totals["fn"]),
            "precision": float(totals["tp"] / max(totals["tp"] + totals["fp"], 1)),
            "recall": float(totals["tp"] / max(totals["tp"] + totals["fn"], 1)),
            "f1": float(part["f1"].mean()), "roc_auc": float(part["roc_auc"].mean()), "pr_auc": float(part["pr_auc"].mean()),
            "direction_accuracy_matched": float(part["direction_accuracy_matched"].mean()),
            "entry_match_1s": float(part["entry_match_1s"].mean()), "entry_match_2s": float(part["entry_match_2s"].mean()),
            "entry_match_5s": float(part["entry_match_5s"].mean()), "entry_match_10s": float(part["entry_match_10s"].mean()),
            "entry_match_15s": float(part["entry_match_15s"].mean()), "entry_match_30s": float(part["entry_match_30s"].mean()),
            "entry_match_60s": float(part["entry_match_60s"].mean()), "entry_match_one_m1_bar": float(part["entry_match_one_m1_bar"].mean()),
            "threshold": np.nan, "feature_count": int(part["feature_count"].max()), "complexity": str(part["complexity"].iloc[0]),
        }
        summaries.append(summary)
    return pd.concat([pd.DataFrame(summaries), folds_frame], ignore_index=True), pd.DataFrame(rule_rows), data


def direction_analysis(panel: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    flags = event_flag_columns(panel)
    features = [column for column in flags + ["event_count", "event_range_expansion_strength", "event_bar_direction", "m1_return_5", "m1_ema20_dist", "m1_vwap_dist", "m15_price_ema20", "h1_price_ema20"] if column in panel]
    entries = panel[panel["entry"].eq(1)].copy().sort_values("timestamp")
    entries["direction_target"] = entries["direction"].eq(1).astype(int)
    rows = []
    for fold, (_, test_start, test_end) in enumerate(chronological_folds(panel), start=1):
        train = entries[entries["timestamp"] < test_start]
        test = entries[(entries["timestamp"] >= test_start) & (entries["timestamp"] < test_end)]
        if train["direction_target"].nunique() < 2 or test.empty:
            continue
        model = fit_numeric_model(train, features, "direction_target", kind="logit", seed=SEED + 900 + fold)
        probability = model.probabilities(test)
        predicted = probability >= 0.5
        actual = test["direction_target"].to_numpy()
        rows.append({
            "fold": fold, "train_n": len(train), "test_n": len(test), "buy_rate_test": float(actual.mean()),
            "direction_accuracy": float(np.mean(predicted == actual)), "roc_auc": roc_auc_score(actual, probability),
            "pr_auc_buy": average_precision_score(actual, probability),
        })
    table = pd.DataFrame(rows)
    summary = "No valid chronological direction folds were available."
    if not table.empty:
        summary = (
            f"Across {len(table)} chronological folds, the event-geometry direction model has mean accuracy "
            f"{table['direction_accuracy'].mean():.3f}, mean ROC AUC {table['roc_auc'].mean():.3f}, and mean Buy PR AUC {table['pr_auc_buy'].mean():.3f}."
        )
    return table, summary


def microstructure_analysis(trades: pd.DataFrame, bars: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    reference = bars.copy()
    reference["timestamp"] = pd.to_datetime(reference["timestamp"])
    reference = reference.set_index("timestamp")
    rows = []
    for trade in trades.itertuples(index=False):
        minute = pd.Timestamp(trade.open_time).floor("min")
        if minute not in reference.index:
            continue
        bar = reference.loc[minute]
        width = float(bar.high - bar.low)
        position = (trade.observed_price - bar.low) / width if width > 0 else np.nan
        rows.append({
            "ticket": str(trade.ticket), "timestamp": trade.open_time, "side": trade.side,
            "observed_price": trade.observed_price, "m1_open": bar.open, "m1_high": bar.high, "m1_low": bar.low,
            "price_position_in_reference_m1_range": position, "price_minus_reference_open": trade.observed_price - bar.open,
            "within_reference_m1_range": bool(bar.low <= trade.observed_price <= bar.high),
        })
    table = pd.DataFrame(rows)
    buy = table.loc[table["side"].eq("Buy"), "price_position_in_reference_m1_range"].dropna()
    sell = table.loc[table["side"].eq("Sell"), "price_position_in_reference_m1_range"].dropna()
    test = stats.mannwhitneyu(buy, sell, alternative="two-sided") if len(buy) and len(sell) else None
    report = (
        f"The bid-only M1 proxy contains {len(table)} aligned entries; {table['within_reference_m1_range'].mean():.3f} have recorded price inside the matching reference-minute range. "
        f"Buy/Sell reference-range position differs by Mann–Whitney p={test.pvalue:.4g} (n={len(buy)}/{len(sell)}) if test else unavailable. "
        "This cannot estimate broker spread, ask price, slippage, or tick sequence."
    )
    return table, report


def markdown_table(frame: pd.DataFrame, max_rows: int | None = None) -> str:
    view = frame.head(max_rows) if max_rows else frame
    if view.empty:
        return "No rows available."
    headers = list(view.columns)
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in view.itertuples(index=False, name=None):
        parts = []
        for value in row:
            if isinstance(value, float):
                parts.append("n.a." if not np.isfinite(value) else f"{value:.5g}")
            else:
                parts.append(str(value).replace("|", "/"))
        lines.append("| " + " | ".join(parts) + " |")
    return "\n".join(lines)


def write_reports(
    panel: pd.DataFrame,
    near: pd.DataFrame,
    controls: pd.DataFrame,
    matched: pd.DataFrame,
    clock: pd.DataFrame,
    replication: pd.DataFrame,
    direction: pd.DataFrame,
    direction_summary: str,
    cooldown: pd.DataFrame,
    proxy_state: pd.DataFrame,
    delay: pd.DataFrame,
    micro_report: str,
) -> None:
    top_matched = matched.head(12)
    top_clock = clock.copy()
    aggregate = replication[replication["evaluation"].eq("oos_aggregate")].sort_values("f1", ascending=False)
    best = aggregate.iloc[0]
    nearmiss_report = f"""# Event near-miss analysis

## Design

Each of the 423 observed trades is paired with the most similar eligible non-entry M1 candidate before and after it on the same raw-clock day/session, normally within ±120 minutes. Similarity uses pre-entry volatility, range, return, location, higher-timeframe proxy state and clock features. The controls are limited to the observed position-capacity envelope (zero or one active recorded position): five actual entry bars occur while one trade is already open. This is a matched descriptive experiment, not proof of the unobserved broker opportunity set.

`event_nearmiss_table.csv` has one row per trade. `event_matched_controls.csv` retains the two control rows used for testing.

## Measured event and clock features that differ after matching

{markdown_table(top_matched[["event_feature", "trade_rate", "matched_control_rate", "paired_rate_difference", "trade_n", "permutation_p", "bh_q"]])}

The matched feature family uses 2,000 within-set label permutations and Benjamini–Hochberg adjustment across the event-feature family. Any association remains a candidate eligibility correlate because unmeasured price path, ask/bid, spread, timer and order-state variables are absent.

## Result

The table demonstrates whether the measured completed-bar events make observed entries less generic than comparable nearby non-trades. It does not establish a unique hidden trigger; a frequent event among controls falsifies a simple deterministic version of that event rule.
"""
    sequence_report = f"""# Event-sequence and temporal reconstruction

## Event construction

All event flags are computed on a completed reference M1 bar and are available only at the next minute boundary. They include rolling/session high-low crossings, VWAP and EMA20 crosses, large-body expansion, compression-to-expansion, false breaks, higher-low/lower-high breaks, pullback continuation and immediate reversal. They are descriptive substitutions for possible geometry, not claims that the original code used EMA or VWAP.

## Delay from M1 event boundary to recorded entry

{markdown_table(delay)}

Entries contain seconds but the proxy is M1. The delay distribution can only test consistency with a completed-minute boundary. It cannot separate first tick after close, a scheduled sub-minute timer, or an intrabar threshold crossing.

## Falsification implication

Even where a completed-bar event is enriched at true entries, the same events occur many times without an order. The event is therefore not a sufficient trigger in the observed M1 proxy.
"""
    state_report = f"""# Stateful eligibility and cooldown analysis

## Observed-proxy states

The following are analytical states created from observed history, not recovered EA states: `IN_TRADE` means an already-open recorded position; `COOLDOWN` means ≤5 minutes after a recorded exit; `SETUP_PROXY`/`ARMED_PROXY` are one or at least two measured completed-bar events; `WATCHING_PROXY` is the remainder. Their candidate and entry rates are:

{markdown_table(proxy_state)}

## Cooldown exposure rates

{markdown_table(cooldown)}

These cooldown exposure denominators use candidate minutes with no recorded active position. They test whether entry likelihood is suppressed immediately after an observed exit, but cannot determine whether a missing trade was due to an internal cooldown, a rejected order, an unrecorded eligibility rule, or absence of a tick-level setup.
"""
    clock_report = f"""# Clock-event analysis

The table compares the observed entry-bar rate at raw-clock boundaries against all other eligible proxy minutes. Matched p-values reuse the nearby-state control design rather than a uniform-minute binomial null.

{markdown_table(top_clock)}

A rate ratio above one is compatible with bar/timer/session timing, but does not identify which of those mechanisms applied or establish broker timezone.
"""
    direction_report = f"""# Direction event analysis

Direction is modeled only among observed entry bars using pre-entry completed-bar event geometry and location variables. {direction_summary}

{markdown_table(direction)}

This asks whether one event family has opposite Buy/Sell polarity under local state. It does not establish two separate direction algorithms.
"""
    microstructure_report = f"""# Microstructure and spread-proxy analysis

{micro_report}

The available source is an external bid-only M1 aggregate. The data cannot distinguish bid from ask, measure live spread, see intrabar jumps, or recover broker execution/slippage. Any remaining selection attributable to those variables is unidentifiable here.
"""
    status_report = f"""# Phase 2 identification status

## LEVEL D — UNIDENTIFIED

Phase 2 adds completed-bar event geometry, matched nearby non-trades, observed-history cooldown state and sparse chronological eligibility models. The best Phase 2 aggregate candidate is **{best['model']}** with OOS precision {best['precision']:.5f}, recall {best['recall']:.5f}, mean F1 {best['f1']:.5f}, mean PR AUC {best['pr_auc']:.5f}, and {int(best['candidate_signals']):,} OOS candidate signals. This does not reproduce the historical event stream with the selectivity required for Level C, B or A.

## Learned

Measured event geometry and raw-clock boundaries can be compared against similar nearby non-trades instead of treating every M1 minute as equally comparable. In this declared matched family, raw-clock 30- and 60-minute boundaries remain enriched after BH adjustment (q≈0.0105); no completed-bar geometry feature survives the same adjustment. The analysis also quantifies how much apparent selection remains after conditioning on observed position capacity and cooldown history.

## Falsified or limited

No tested single completed-bar event, small proxy-state machine or constrained sparse rule explains why the system chose only these specific entries. A generic M1 completed-bar event is not sufficient when similar matched moments commonly receive no trade. The boundary enrichment is consistent with a timer/bar/session layer, but cannot tell these mechanisms apart or establish it as a sufficient trigger.

## Still unknown and data needed

Broker tick bid/ask, spread, server-time metadata, actual order/deal lifecycle, rejected/cancelled orders, stop/target modifications, EA logs and account state would be needed to distinguish an intrabar trigger, timer, microstructure gate, hidden cooldown, execution filter or unobserved strategy state. The M1 proxy cannot resolve those alternatives.
"""
    (OUT / "event_nearmiss_analysis.md").write_text(nearmiss_report, encoding="utf-8")
    (OUT / "event_sequence_analysis.md").write_text(sequence_report, encoding="utf-8")
    (OUT / "state_machine_analysis.md").write_text(state_report, encoding="utf-8")
    (OUT / "clock_event_analysis.md").write_text(clock_report, encoding="utf-8")
    (OUT / "direction_event_analysis.md").write_text(direction_report, encoding="utf-8")
    (OUT / "microstructure_analysis.md").write_text(microstructure_report, encoding="utf-8")
    (OUT / "phase2_status.md").write_text(status_report, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    trades, _ = load_trades(ROOT / "data" / "raw" / "trades_raw.tsv")
    bars = pd.read_csv(ROOT / "data" / "market" / "normalized" / "xauusd_m1.csv")
    bars["timestamp"] = pd.to_datetime(bars["timestamp"])
    panel = pd.read_csv(OUT / "candidate_event_table.csv.gz", low_memory=False)
    panel["timestamp"] = pd.to_datetime(panel["timestamp"])
    events = event_features_from_bars(bars)
    panel = panel.merge(events, on="timestamp", how="left", validate="one_to_one")
    panel = attach_trade_state(panel, trades)
    if panel.loc[panel["entry"].eq(1), "eligible_observed_capacity"].eq(0).any():
        raise AssertionError("An observed entry was incorrectly excluded by the observed capacity envelope")

    near, controls = matched_nearmisses(panel, trades)
    matched = matched_feature_tests(controls)
    clock = clock_analysis(panel, matched)
    replication, sparse_rules, eligible = event_replication(panel, trades)
    direction, direction_summary = direction_analysis(panel, trades)
    micro, micro_report = microstructure_analysis(trades, bars)

    event_times = panel.loc[panel["event_any"].eq(1), "timestamp"]
    last_event = panel["timestamp"].where(panel["event_any"].eq(1)).ffill()
    entry_bars = panel[panel["entry"].eq(1)][["timestamp"]].copy()
    entry_bars["recent_event_time"] = last_event.loc[entry_bars.index].to_numpy()
    entry_bars["minutes_since_measured_event"] = (entry_bars["timestamp"] - entry_bars["recent_event_time"]).dt.total_seconds() / 60
    trade_delay = trades.assign(entry_minute=trades["open_time"].dt.floor("min")).merge(entry_bars, left_on="entry_minute", right_on="timestamp", how="left")
    second_delay = (trade_delay["open_time"] - trade_delay["entry_minute"]).dt.total_seconds()
    delay = pd.DataFrame({
        "tolerance": ["≤1s", "≤2s", "≤5s", "≤10s", "≤15s", "≤30s", "≤60s"],
        "share_of_recorded_entries_after_minute_boundary": [float((second_delay <= x).mean()) for x in [1, 2, 5, 10, 15, 30, 60]],
    })
    delay["median_minutes_since_measured_event"] = float(entry_bars["minutes_since_measured_event"].median())
    delay.to_csv(OUT / "temporal_event_delays.csv", index=False)

    idle = panel[panel["eligible_no_active_position"].eq(1)].copy()
    cooldown = idle.groupby(["cooldown_bin", "prior_win_code"], dropna=False).agg(
        candidate_minutes=("entry", "size"), entry_bars=("entry", "sum")
    ).reset_index()
    cooldown["entry_rate_per_10k_minutes"] = 10_000 * cooldown["entry_bars"] / cooldown["candidate_minutes"]
    cooldown.to_csv(OUT / "cooldown_exposure.csv", index=False)
    proxy_state = panel.groupby("proxy_state_before_entry").agg(candidate_minutes=("entry", "size"), entry_bars=("entry", "sum")).reset_index()
    proxy_state = proxy_state.rename(columns={"proxy_state_before_entry": "proxy_state"})
    proxy_state["entry_rate_per_10k_minutes"] = 10_000 * proxy_state["entry_bars"] / proxy_state["candidate_minutes"]
    proxy_state.to_csv(OUT / "state_machine_exposure.csv", index=False)

    near.to_csv(OUT / "event_nearmiss_table.csv", index=False)
    controls.to_csv(OUT / "event_matched_controls.csv", index=False)
    matched.to_csv(OUT / "event_matched_feature_tests.csv", index=False)
    clock.to_csv(OUT / "clock_event_results.csv", index=False)
    sparse_rules.to_csv(OUT / "sparse_event_rules.csv", index=False)
    replication.to_csv(OUT / "event_replication_results.csv", index=False)
    direction.to_csv(OUT / "direction_event_results.csv", index=False)
    micro.to_csv(OUT / "microstructure_proxy_table.csv", index=False)
    selected = ["timestamp", "entry", "entry_count", "direction", "eligible_no_active_position", "eligible_observed_capacity", "active_positions_before_candidate", "seconds_since_last_exit", "seconds_since_last_entry", "prior_win_code", "prior_direction_code", "event_count", "event_any", "proxy_state_before_entry", "proxy_state"]
    selected += [column for column in panel.columns if column.startswith(EVENT_PREFIX)]
    selected += [column for column in baseline_columns(panel) if column not in selected]
    panel[selected].to_csv(OUT / "phase2_event_panel.csv.gz", index=False, compression="gzip", float_format="%.8g")

    write_reports(panel, near, controls, matched, clock, replication, direction, direction_summary, cooldown, proxy_state, delay, micro_report)
    aggregate = replication[replication["evaluation"].eq("oos_aggregate")].sort_values("f1", ascending=False)
    validation = {
        "status": "ok",
        "level": "D — UNIDENTIFIED",
        "candidate_minutes": int(len(panel)),
        "eligible_observed_capacity_minutes": int(panel["eligible_observed_capacity"].sum()),
        "entry_bars": int(panel["entry"].sum()),
        "trades": int(len(trades)),
        "nearmiss_rows": int(len(near)),
        "matched_control_rows": int(len(controls)),
        "event_features": int(len([column for column in panel if column.startswith(EVENT_PREFIX)])),
        "event_models": int(len(aggregate)),
        "event_flags_complete_bar_shift": "Each source M1 event is timestamped one minute after its source bar begins.",
        "forbidden_current_outcomes_in_entry_features": True,
        "m1_microstructure_limit": "Bid-only aggregated M1 cannot identify ticks, asks, spreads, or intrabar trigger ordering.",
        "best_oos_model": aggregate.iloc[0].to_dict() if not aggregate.empty else {},
        "random_seed": SEED,
    }
    (OUT / "phase2_validation.json").write_text(json.dumps(validation, indent=2, default=jsonable), encoding="utf-8")
    print(json.dumps({"status": "ok", **{k: validation[k] for k in ["candidate_minutes", "entry_bars", "nearmiss_rows", "event_models", "best_oos_model"]}}, indent=2, default=jsonable))


if __name__ == "__main__":
    main()
