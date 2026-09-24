"""End-to-end trade-log forensic analysis.

The pipeline deliberately separates facts observable in the supplied TSV from
claims that require synchronized market, broker, order, or account data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import ruptures as rpt
from hmmlearn.hmm import GaussianHMM
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

from .market import add_market_features, align_entries, calculate_excursions, load_market_bars
from .statistics import (
    benjamini_hochberg,
    cluster_bootstrap_ci,
    cramer_v,
    json_number,
    longest_streak,
    percentile_ci,
    permutation_binary_statistic,
    permutation_test,
    proportion_ci,
    runs_test,
)


SEED = 20260919
FIELD_NAMES = [
    "ticket",
    "side",
    "open_time",
    "close_time",
    "symbol",
    "lot_size",
    "observed_price",
    "pnl",
]
WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
CLOCK_BUCKET_ORDER = ["00:00-07:59", "08:00-12:59", "13:00-16:59", "17:00-21:59", "22:00-23:59"]


def _clock_bucket(hour: int) -> str:
    if hour < 8:
        return "00:00-07:59"
    if hour < 13:
        return "08:00-12:59"
    if hour < 17:
        return "13:00-16:59"
    if hour < 22:
        return "17:00-21:59"
    return "22:00-23:59"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_trades(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = pd.read_csv(path, sep="\t", header=None, dtype=str, keep_default_na=False)
    if raw.shape[1] != 8:
        raise ValueError(f"Expected exactly 8 tab-separated fields, found {raw.shape[1]}")
    raw.columns = FIELD_NAMES
    input_order = raw.copy()
    empty_cells = int((raw == "").sum().sum())
    price_precision = raw["observed_price"].str.extract(r"\.(\d+)$", expand=False).fillna("").str.len()
    pnl_precision = raw["pnl"].str.extract(r"\.(\d+)$", expand=False).fillna("").str.len()

    raw["open_time"] = pd.to_datetime(raw["open_time"], errors="raise")
    raw["close_time"] = pd.to_datetime(raw["close_time"], errors="raise")
    for column in ["lot_size", "observed_price", "pnl"]:
        raw[column] = pd.to_numeric(raw[column], errors="raise")
    if not raw["side"].isin(["Buy", "Sell"]).all():
        raise ValueError("Direction column contains values other than Buy/Sell")

    reverse_open_inversions = int(
        (
            input_order["open_time"].iloc[1:].reset_index(drop=True)
            > input_order["open_time"].iloc[:-1].reset_index(drop=True)
        ).sum()
    )
    reverse_close_inversions = int(
        (
            input_order["close_time"].iloc[1:].reset_index(drop=True)
            > input_order["close_time"].iloc[:-1].reset_index(drop=True)
        ).sum()
    )
    trades = raw.sort_values(["open_time", "close_time", "ticket"], kind="mergesort").reset_index(drop=True)
    trades["duration_seconds"] = (trades["close_time"] - trades["open_time"]).dt.total_seconds()
    trades["duration_minutes"] = trades["duration_seconds"] / 60.0
    trades["win"] = trades["pnl"] > 0
    trades["pnl_per_0_01_lot"] = trades["pnl"] / (trades["lot_size"] / 0.01)
    trades["side_code"] = (trades["side"] == "Buy").astype(int)
    trades["open_date"] = trades["open_time"].dt.date
    trades["hour"] = trades["open_time"].dt.hour
    trades["minute"] = trades["open_time"].dt.minute
    trades["minute_5"] = (trades["minute"] // 5) * 5
    trades["weekday"] = pd.Categorical(trades["open_time"].dt.day_name(), categories=WEEKDAY_ORDER, ordered=True)
    trades["month"] = trades["open_time"].dt.to_period("M").astype(str)
    trades["quarter"] = trades["open_time"].dt.to_period("Q").astype(str)
    trades["clock_bucket"] = pd.Categorical(
        trades["hour"].map(_clock_bucket), categories=CLOCK_BUCKET_ORDER, ordered=True
    )
    trades["gap_from_previous_entry_minutes"] = trades["open_time"].diff().dt.total_seconds() / 60.0
    trades["gap_from_previous_close_minutes"] = (
        trades["open_time"] - trades["close_time"].shift(1)
    ).dt.total_seconds() / 60.0
    trades["previous_pnl"] = trades["pnl"].shift(1)
    trades["previous_win"] = trades["win"].shift(1)
    trades["cumulative_pnl_before"] = trades["pnl"].cumsum().shift(1).fillna(0.0)
    trades["same_direction_as_previous"] = trades["side"].eq(trades["side"].shift(1))

    active_before: list[int] = []
    for row in trades.itertuples(index=False):
        active_before.append(
            int(((trades["open_time"] < row.open_time) & (trades["close_time"] > row.open_time)).sum())
        )
    trades["active_positions_before_entry"] = active_before
    trades["entry_while_position_active"] = trades["active_positions_before_entry"] > 0

    events: list[tuple[pd.Timestamp, int, int]] = []
    for row in trades.itertuples(index=False):
        events.append((row.open_time, 1, 1))
        events.append((row.close_time, 0, -1))
    concurrency = current = 0
    for _, _, delta in sorted(events):
        current += delta
        concurrency = max(concurrency, current)

    quality = {
        "sha256": sha256(path),
        "physical_rows": int(len(raw)),
        "columns": int(raw.shape[1]),
        "empty_cells": empty_cells,
        "duplicate_full_rows": int(raw.duplicated().sum()),
        "duplicate_ticket_values": int(raw["ticket"].duplicated().sum()),
        "leading_zero_ticket_count": int(raw["ticket"].str.match(r"^0\d+$").sum()),
        "non_positive_duration_count": int((trades["duration_seconds"] <= 0).sum()),
        "reverse_chronological_open_time_inversions": reverse_open_inversions,
        "reverse_chronological_close_time_inversions": reverse_close_inversions,
        "input_is_strictly_close_time_descending": bool(reverse_close_inversions == 0),
        "duplicate_open_timestamps": int(raw["open_time"].duplicated().sum()),
        "duplicate_close_timestamps": int(raw["close_time"].duplicated().sum()),
        "same_calendar_day_open_close_count": int((raw["open_time"].dt.date == raw["close_time"].dt.date).sum()),
        "weekend_open_count": int((raw["open_time"].dt.dayofweek >= 5).sum()),
        "price_display_decimal_counts": {str(int(k)): int(v) for k, v in price_precision.value_counts().sort_index().items()},
        "pnl_display_decimal_counts": {str(int(k)): int(v) for k, v in pnl_precision.value_counts().sort_index().items()},
        "maximum_concurrency": concurrency,
        "leading_zero_ticket_review": {
            "observed": raw.loc[raw["ticket"].str.match(r"^0\d+$"), "ticket"].tolist(),
            "warning": "Do not coerce or repair. The leading-zero value is a ticket-format anomaly requiring the original statement.",
        },
    }
    return trades, quality


def _equity_metrics(pnl: pd.Series) -> dict[str, float]:
    cumulative = pnl.cumsum().to_numpy(dtype=float)
    equity = np.concatenate([[0.0], cumulative])
    peaks = np.maximum.accumulate(equity)
    drawdown = equity - peaks
    trough_index = int(np.argmin(drawdown))
    peak_index = int(np.argmax(equity[: trough_index + 1])) if trough_index else 0
    return {
        "terminal_pnl": float(cumulative[-1]),
        "maximum_closed_trade_drawdown": float(-drawdown[trough_index]),
        "drawdown_peak_trade_index": peak_index,
        "drawdown_trough_trade_index": trough_index,
    }


def dataset_summary(trades: pd.DataFrame, quality: dict[str, Any]) -> dict[str, Any]:
    start = trades["open_time"].min()
    end = trades["open_time"].max()
    positive = trades.loc[trades["pnl"] > 0, "pnl"]
    negative = trades.loc[trades["pnl"] < 0, "pnl"]
    mean_ci = percentile_ci(trades["pnl"], np.mean)
    day_cluster_mean_ci = cluster_bootstrap_ci(
        trades["pnl"], trades["open_date"], np.mean, seed=SEED + 101
    )
    day_cluster_win_ci = cluster_bootstrap_ci(
        trades["win"].astype(float), trades["open_date"], np.mean, seed=SEED + 102
    )
    win_ci = proportion_ci(int(trades["win"].sum()), len(trades))
    active_day_counts = trades.groupby("open_date").size()
    daily_pnl = trades.groupby("open_date")["pnl"].sum()
    result = {
        "observations": int(len(trades)),
        "symbols": {str(k): int(v) for k, v in trades["symbol"].value_counts().items()},
        "start_open": start.isoformat(),
        "end_open": end.isoformat(),
        "calendar_span_days_inclusive": int((end.date() - start.date()).days + 1),
        "distinct_open_dates": int(trades["open_date"].nunique()),
        "mean_trades_per_active_date": float(active_day_counts.mean()),
        "active_date_trade_count_distribution": {
            str(int(k)): int(v) for k, v in active_day_counts.value_counts().sort_index().items()
        },
        "positive_active_dates": int((daily_pnl > 0).sum()),
        "negative_active_dates": int((daily_pnl < 0).sum()),
        "zero_active_dates": int((daily_pnl == 0).sum()),
        "buy_count": int((trades["side"] == "Buy").sum()),
        "sell_count": int((trades["side"] == "Sell").sum()),
        "positive_count": int((trades["pnl"] > 0).sum()),
        "negative_count": int((trades["pnl"] < 0).sum()),
        "zero_count": int((trades["pnl"] == 0).sum()),
        "win_rate": float(trades["win"].mean()),
        "win_rate_ci_95": list(win_ci),
        "win_rate_day_cluster_bootstrap_ci_95": list(day_cluster_win_ci),
        "total_pnl": float(trades["pnl"].sum()),
        "mean_pnl": float(trades["pnl"].mean()),
        "mean_pnl_ci_95": list(mean_ci),
        "mean_pnl_day_cluster_bootstrap_ci_95": list(day_cluster_mean_ci),
        "median_pnl": float(trades["pnl"].median()),
        "median_duration_minutes": float(trades["duration_minutes"].median()),
        "mean_duration_minutes": float(trades["duration_minutes"].mean()),
        "maximum_duration_minutes": float(trades["duration_minutes"].max()),
        "lot_size_counts": {str(k): int(v) for k, v in trades["lot_size"].value_counts().sort_index().items()},
        "gross_profit": float(positive.sum()),
        "gross_loss": float(negative.sum()),
        "profit_factor": float(positive.sum() / abs(negative.sum())),
        "maximum_concurrency": quality["maximum_concurrency"],
        "entries_while_active": int(trades["entry_while_position_active"].sum()),
    }
    result.update(_equity_metrics(trades["pnl"]))
    return result


def direction_analysis(trades: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, list[dict[str, Any]]]:
    labels = trades["side_code"].to_numpy(dtype=int)
    transitions = np.zeros((2, 2), dtype=int)
    for current, following in zip(labels[:-1], labels[1:], strict=True):
        transitions[current, following] += 1
    # Matrix presentation order Buy, Sell.
    presentation = np.array(
        [[transitions[1, 1], transitions[1, 0]], [transitions[0, 1], transitions[0, 0]]], dtype=int
    )
    transition_table = pd.DataFrame(presentation, index=["Buy", "Sell"], columns=["Buy", "Sell"])
    row_probabilities = presentation / presentation.sum(axis=1, keepdims=True)

    buy_probability = labels.mean()
    next_labels = labels[1:]
    iid_probability = next_labels.mean()
    ll_iid = float(
        np.sum(next_labels * np.log(iid_probability) + (1 - next_labels) * np.log(1 - iid_probability))
    )
    ll_first = 0.0
    for row in transitions:
        total = row.sum()
        probabilities = row / total
        ll_first += float(np.sum(row[row > 0] * np.log(probabilities[row > 0])))

    contexts: dict[tuple[int, int], list[int]] = {(a, b): [] for a in [0, 1] for b in [0, 1]}
    for first, second, following in zip(labels[:-2], labels[1:-1], labels[2:], strict=True):
        contexts[(first, second)].append(int(following))
    ll_second = 0.0
    for observations in contexts.values():
        if observations:
            probability = np.mean(observations)
            if probability in [0.0, 1.0]:
                continue
            array = np.asarray(observations)
            ll_second += float(np.sum(array * np.log(probability) + (1 - array) * np.log(1 - probability)))

    restricted_transitions = np.zeros((2, 2), dtype=int)
    for current, following in zip(labels[1:-1], labels[2:], strict=True):
        restricted_transitions[current, following] += 1
    ll_first_restricted = 0.0
    for row in restricted_transitions:
        total = row.sum()
        probabilities = row / total
        ll_first_restricted += float(np.sum(row[row > 0] * np.log(probabilities[row > 0])))

    lr_iid_markov = max(0.0, 2.0 * (ll_first - ll_iid))
    lr_p = float(stats.chi2.sf(lr_iid_markov, 1))
    markov_order_lr = max(0.0, 2.0 * (ll_second - ll_first_restricted))
    markov_order_p = float(stats.chi2.sf(markov_order_lr, 2))
    permutation = permutation_binary_statistic(
        labels, lambda x: float(np.mean(x[1:] == x[:-1])), repetitions=10_000, seed=SEED
    )
    runs = runs_test(labels)
    buy_exact_p = float(stats.binomtest(int(labels.sum()), len(labels), 0.5).pvalue)
    entropy_bits = float(stats.entropy([buy_probability, 1.0 - buy_probability], base=2))
    autocorrelation: dict[str, float | None] = {}
    for lag in range(1, 11):
        autocorrelation[str(lag)] = json_number(np.corrcoef(labels[:-lag], labels[lag:])[0, 1])

    direction = {
        "buy_proportion": float(buy_probability),
        "buy_proportion_ci_95": list(proportion_ci(int(labels.sum()), len(labels))),
        "binomial_vs_50_50_p_value": buy_exact_p,
        "transition_counts": transition_table.to_dict(orient="index"),
        "transition_probabilities": {
            "Buy": {"Buy": float(row_probabilities[0, 0]), "Sell": float(row_probabilities[0, 1])},
            "Sell": {"Buy": float(row_probabilities[1, 0]), "Sell": float(row_probabilities[1, 1])},
        },
        "same_direction_rate": float(np.mean(labels[1:] == labels[:-1])),
        "same_direction_permutation": permutation,
        "runs_test": runs,
        "entropy_bits": entropy_bits,
        "autocorrelation_lags_1_to_10": autocorrelation,
        "iid_log_likelihood": ll_iid,
        "first_order_log_likelihood": ll_first,
        "second_order_log_likelihood": ll_second,
        "iid_vs_first_order_lr": lr_iid_markov,
        "iid_vs_first_order_p_value": lr_p,
        "first_vs_second_order_lr": markov_order_lr,
        "first_vs_second_order_p_value": markov_order_p,
        "model_selection": {
            "iid": {"parameters": 1, "aic": 2 - 2 * ll_iid, "bic": math.log(len(labels) - 1) - 2 * ll_iid},
            "markov_order_1": {
                "parameters": 2,
                "aic": 4 - 2 * ll_first,
                "bic": 2 * math.log(len(labels) - 1) - 2 * ll_first,
            },
            "markov_order_2": {
                "parameters": 4,
                "aic": 8 - 2 * ll_second,
                "bic": 4 * math.log(len(labels) - 2) - 2 * ll_second,
            },
        },
    }
    tests = [
        {
            "test_id": "DIR-01",
            "family": "direction",
            "test": "Exact binomial Buy proportion versus 0.50",
            "effect": float(buy_probability - 0.5),
            "p_value": buy_exact_p,
        },
        {
            "test_id": "DIR-02",
            "family": "direction",
            "test": "Permutation test of adjacent same-direction rate",
            "effect": float(permutation["observed"] - permutation["null_mean"]),
            "p_value": float(permutation["p_value"]),
        },
        {
            "test_id": "DIR-03",
            "family": "direction",
            "test": "Wald-Wolfowitz runs test",
            "effect": float(runs["runs"] - runs["expected"]),
            "p_value": float(runs["p_value"]),
        },
        {
            "test_id": "DIR-04",
            "family": "direction",
            "test": "Likelihood-ratio IID versus first-order Markov",
            "effect": lr_iid_markov,
            "p_value": lr_p,
        },
        {
            "test_id": "DIR-05",
            "family": "direction",
            "test": "Likelihood-ratio first- versus second-order Markov",
            "effect": markov_order_lr,
            "p_value": markov_order_p,
        },
    ]
    return direction, transition_table, tests


def profit_analysis(trades: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pnl = trades["pnl"]
    winners = pnl[pnl > 0]
    losers = pnl[pnl < 0]
    buy = trades.loc[trades["side"] == "Buy", "pnl"]
    sell = trades.loc[trades["side"] == "Sell", "pnl"]
    buy_win = trades.loc[trades["side"] == "Buy", "win"]
    sell_win = trades.loc[trades["side"] == "Sell", "win"]
    mean_perm = permutation_test(buy, sell, repetitions=10_000, seed=SEED)
    median_perm = permutation_test(buy, sell, statistic=np.median, repetitions=10_000, seed=SEED + 1)
    mann = stats.mannwhitneyu(buy, sell, alternative="two-sided")
    welch = stats.ttest_ind(buy, sell, equal_var=False)
    win_table = pd.crosstab(trades["side"], trades["win"]).reindex(index=["Buy", "Sell"], columns=[False, True], fill_value=0)
    win_chi = stats.chi2_contingency(win_table, correction=False)
    normalized = trades["pnl_per_0_01_lot"]
    normalized_buy = trades.loc[trades["side"] == "Buy", "pnl_per_0_01_lot"]
    normalized_sell = trades.loc[trades["side"] == "Sell", "pnl_per_0_01_lot"]
    normalized_perm = permutation_test(normalized_buy, normalized_sell, repetitions=10_000, seed=SEED + 103)
    outcomes = trades["win"].astype(int).to_numpy()
    outcome_transitions = np.zeros((2, 2), dtype=int)
    for current, following in zip(outcomes[:-1], outcomes[1:], strict=True):
        outcome_transitions[current, following] += 1
    win_after_loss = outcome_transitions[0, 1] / outcome_transitions[0].sum()
    win_after_win = outcome_transitions[1, 1] / outcome_transitions[1].sum()
    observed_outcome_effect = float(win_after_loss - win_after_win)
    rng = np.random.default_rng(SEED + 108)
    null_effect = np.empty(20_000, dtype=float)
    for index in range(len(null_effect)):
        shuffled = rng.permutation(outcomes)
        table = np.zeros((2, 2), dtype=int)
        for current, following in zip(shuffled[:-1], shuffled[1:], strict=True):
            table[current, following] += 1
        null_effect[index] = table[0, 1] / table[0].sum() - table[1, 1] / table[1].sum()
    outcome_p = float(
        (np.count_nonzero(np.abs(null_effect) >= abs(observed_outcome_effect)) + 1) / (len(null_effect) + 1)
    )
    quantile_levels = [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
    pnl_modes = pnl.value_counts().head(10)
    result = {
        "mean": float(pnl.mean()),
        "median": float(pnl.median()),
        "standard_deviation": float(pnl.std(ddof=1)),
        "variance": float(pnl.var(ddof=1)),
        "skewness": float(stats.skew(pnl, bias=False)),
        "excess_kurtosis": float(stats.kurtosis(pnl, fisher=True, bias=False)),
        "minimum": float(pnl.min()),
        "maximum": float(pnl.max()),
        "quantiles": {str(level): float(pnl.quantile(level)) for level in quantile_levels},
        "most_frequent_exact_values": {str(float(k)): int(v) for k, v in pnl_modes.items()},
        "largest_exact_value_count": int(pnl_modes.iloc[0]),
        "average_winner": float(winners.mean()),
        "average_loser": float(losers.mean()),
        "payoff_ratio": float(winners.mean() / abs(losers.mean())),
        "profit_factor": float(winners.sum() / abs(losers.sum())),
        "longest_win_streak": longest_streak(trades["win"], True),
        "longest_loss_streak": longest_streak(trades["win"], False),
        "buy": {
            "n": int(len(buy)),
            "mean_pnl": float(buy.mean()),
            "median_pnl": float(buy.median()),
            "win_rate": float(buy_win.mean()),
            "win_rate_ci_95": list(proportion_ci(int(buy_win.sum()), len(buy_win))),
        },
        "sell": {
            "n": int(len(sell)),
            "mean_pnl": float(sell.mean()),
            "median_pnl": float(sell.median()),
            "win_rate": float(sell_win.mean()),
            "win_rate_ci_95": list(proportion_ci(int(sell_win.sum()), len(sell_win))),
        },
        "buy_sell_mean_permutation": mean_perm,
        "buy_sell_median_permutation": median_perm,
        "buy_sell_mann_whitney": {"u": float(mann.statistic), "p_value": float(mann.pvalue)},
        "buy_sell_welch_t": {"t": float(welch.statistic), "p_value": float(welch.pvalue)},
        "side_win_chi_square": {"chi_square": float(win_chi.statistic), "p_value": float(win_chi.pvalue)},
        "pnl_mean_ci_95": list(percentile_ci(pnl, np.mean)),
        "pnl_median_ci_95": list(percentile_ci(pnl, np.median, seed=SEED + 2)),
        "normalized_to_0_01_lot": {
            "mean": float(normalized.mean()),
            "median": float(normalized.median()),
            "minimum": float(normalized.min()),
            "maximum": float(normalized.max()),
            "buy_mean": float(normalized_buy.mean()),
            "sell_mean": float(normalized_sell.mean()),
            "buy_sell_mean_permutation": normalized_perm,
        },
        "outcome_transition_counts": {
            "Loss": {"Loss": int(outcome_transitions[0, 0]), "Win": int(outcome_transitions[0, 1])},
            "Win": {"Loss": int(outcome_transitions[1, 0]), "Win": int(outcome_transitions[1, 1])},
        },
        "win_after_loss": float(win_after_loss),
        "win_after_win": float(win_after_win),
        "win_after_loss_minus_after_win": observed_outcome_effect,
        "outcome_transition_permutation_p_value": outcome_p,
    }
    tests = [
        {
            "test_id": "PNL-01",
            "family": "profit",
            "test": "Buy minus Sell mean P&L permutation",
            "effect": mean_perm["difference"],
            "p_value": mean_perm["p_value"],
        },
        {
            "test_id": "PNL-02",
            "family": "profit",
            "test": "Buy versus Sell P&L Mann-Whitney",
            "effect": float(buy.median() - sell.median()),
            "p_value": float(mann.pvalue),
        },
        {
            "test_id": "PNL-03",
            "family": "profit",
            "test": "Side versus win/loss chi-square",
            "effect": float(buy_win.mean() - sell_win.mean()),
            "p_value": float(win_chi.pvalue),
        },
        {
            "test_id": "PNL-04",
            "family": "profit",
            "test": "Buy minus Sell mean P&L normalized to 0.01 size permutation",
            "effect": normalized_perm["difference"],
            "p_value": normalized_perm["p_value"],
        },
        {
            "test_id": "PNL-05",
            "family": "profit",
            "test": "Win-after-loss minus win-after-win transition permutation",
            "effect": observed_outcome_effect,
            "p_value": outcome_p,
        },
    ]
    return result, tests


def duration_analysis(trades: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, Any]], pd.DataFrame]:
    duration = trades["duration_minutes"].to_numpy(dtype=float)
    buy = trades.loc[trades["side"] == "Buy", "duration_minutes"]
    sell = trades.loc[trades["side"] == "Sell", "duration_minutes"]
    mean_perm = permutation_test(buy, sell, repetitions=10_000, seed=SEED + 3)
    median_perm = permutation_test(buy, sell, statistic=np.median, repetitions=10_000, seed=SEED + 4)
    mann = stats.mannwhitneyu(buy, sell, alternative="two-sided")
    fits: list[dict[str, Any]] = []
    distributions = {
        "exponential": (stats.expon, 1),
        "lognormal": (stats.lognorm, 2),
        "gamma": (stats.gamma, 2),
        "weibull": (stats.weibull_min, 2),
    }
    for name, (distribution, free_parameters) in distributions.items():
        try:
            parameters = distribution.fit(duration, floc=0)
            log_likelihood = float(np.sum(distribution.logpdf(duration, *parameters)))
            k = free_parameters
            fits.append(
                {
                    "distribution": name,
                    "log_likelihood": log_likelihood,
                    "parameters": json.dumps([float(value) for value in parameters]),
                    "aic": 2 * k - 2 * log_likelihood,
                    "bic": k * math.log(len(duration)) - 2 * log_likelihood,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive for numerical edge cases
            fits.append(
                {
                    "distribution": name,
                    "log_likelihood": np.nan,
                    "parameters": f"fit failed: {exc}",
                    "aic": np.nan,
                    "bic": np.nan,
                }
            )
    fit_table = pd.DataFrame(fits).sort_values("bic", na_position="last")
    rounded_modes = trades["duration_minutes"].round().value_counts().head(10)
    duration_pnl_spearman = stats.spearmanr(trades["duration_minutes"], trades["pnl"])
    duration_normalized_pnl_spearman = stats.spearmanr(
        trades["duration_minutes"], trades["pnl_per_0_01_lot"]
    )
    winner_duration = trades.loc[trades["win"], "duration_minutes"]
    loser_duration = trades.loc[~trades["win"], "duration_minutes"]
    winner_loser_log = permutation_test(
        np.log(winner_duration), np.log(loser_duration), repetitions=20_000, seed=SEED + 104
    )
    winner_loser_median = permutation_test(
        winner_duration, loser_duration, statistic=np.median, repetitions=20_000, seed=SEED + 105
    )
    winner_loser_mann = stats.mannwhitneyu(winner_duration, loser_duration, alternative="two-sided")

    def uniform_second_test(seconds: pd.Series, seed: int) -> dict[str, float]:
        counts = seconds.value_counts().reindex(range(60), fill_value=0).to_numpy(dtype=float)
        expected = len(seconds) / 60.0
        observed = float(np.sum((counts - expected) ** 2 / expected))
        rng = np.random.default_rng(seed)
        null = rng.multinomial(len(seconds), np.repeat(1 / 60, 60), size=20_000)
        null_statistics = np.sum((null - expected) ** 2 / expected, axis=1)
        return {
            "chi_square": observed,
            "monte_carlo_p_value": float((np.count_nonzero(null_statistics >= observed) + 1) / (len(null_statistics) + 1)),
        }

    open_seconds_test = uniform_second_test(trades["open_time"].dt.second, SEED + 106)
    close_seconds_test = uniform_second_test(trades["close_time"].dt.second, SEED + 107)
    whole_minute_count = int(np.count_nonzero(trades["duration_seconds"].to_numpy(dtype=int) % 60 == 0))
    whole_minute_p = float(stats.binomtest(whole_minute_count, len(trades), 1 / 60).pvalue)
    exact_second_modes = trades["duration_seconds"].value_counts().head(10)
    result = {
        "mean_minutes": float(np.mean(duration)),
        "median_minutes": float(np.median(duration)),
        "standard_deviation_minutes": float(np.std(duration, ddof=1)),
        "minimum_minutes": float(np.min(duration)),
        "maximum_minutes": float(np.max(duration)),
        "quantiles_minutes": {
            str(level): float(np.quantile(duration, level))
            for level in [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
        },
        "share_closed_within_minutes": {
            str(limit): float(np.mean(duration <= limit)) for limit in [1, 2, 5, 10, 15, 30, 60]
        },
        "rounded_minute_modes": {str(int(k)): int(v) for k, v in rounded_modes.items()},
        "mean_ci_95": list(percentile_ci(duration, np.mean, seed=SEED + 5)),
        "median_ci_95": list(percentile_ci(duration, np.median, seed=SEED + 6)),
        "buy_mean_minutes": float(buy.mean()),
        "sell_mean_minutes": float(sell.mean()),
        "buy_median_minutes": float(buy.median()),
        "sell_median_minutes": float(sell.median()),
        "buy_sell_mean_permutation": mean_perm,
        "buy_sell_median_permutation": median_perm,
        "buy_sell_mann_whitney_p_value": float(mann.pvalue),
        "duration_pnl_spearman_rho": float(duration_pnl_spearman.statistic),
        "duration_pnl_spearman_p_value": float(duration_pnl_spearman.pvalue),
        "duration_normalized_pnl_spearman_rho": float(duration_normalized_pnl_spearman.statistic),
        "duration_normalized_pnl_spearman_p_value": float(duration_normalized_pnl_spearman.pvalue),
        "candidate_distribution_by_bic": fit_table.to_dict(orient="records"),
        "winner_mean_minutes": float(winner_duration.mean()),
        "loser_mean_minutes": float(loser_duration.mean()),
        "winner_median_minutes": float(winner_duration.median()),
        "loser_median_minutes": float(loser_duration.median()),
        "winner_loser_log_duration_permutation": winner_loser_log,
        "winner_loser_geometric_mean_ratio": float(math.exp(winner_loser_log["difference"])),
        "winner_loser_median_permutation": winner_loser_median,
        "winner_loser_mann_whitney_p_value": float(winner_loser_mann.pvalue),
        "open_second_uniformity": open_seconds_test,
        "close_second_uniformity": close_seconds_test,
        "whole_minute_duration_count": whole_minute_count,
        "whole_minute_duration_expected": float(len(trades) / 60),
        "whole_minute_duration_binomial_p_value": whole_minute_p,
        "most_frequent_exact_duration_seconds": {
            str(int(k)): int(v) for k, v in exact_second_modes.items()
        },
        "largest_exact_duration_count": int(exact_second_modes.iloc[0]),
    }
    tests = [
        {
            "test_id": "DUR-01",
            "family": "duration",
            "test": "Buy minus Sell mean duration permutation",
            "effect": mean_perm["difference"],
            "p_value": mean_perm["p_value"],
        },
        {
            "test_id": "DUR-02",
            "family": "duration",
            "test": "Buy versus Sell duration Mann-Whitney",
            "effect": float(buy.median() - sell.median()),
            "p_value": float(mann.pvalue),
        },
        {
            "test_id": "DUR-03",
            "family": "duration",
            "test": "Duration versus P&L Spearman correlation",
            "effect": float(duration_pnl_spearman.statistic),
            "p_value": float(duration_pnl_spearman.pvalue),
        },
        {
            "test_id": "DUR-04",
            "family": "duration",
            "test": "Duration versus size-normalized P&L Spearman correlation",
            "effect": float(duration_normalized_pnl_spearman.statistic),
            "p_value": float(duration_normalized_pnl_spearman.pvalue),
        },
        {
            "test_id": "DUR-05",
            "family": "duration",
            "test": "Winner minus loser mean log duration permutation",
            "effect": winner_loser_log["difference"],
            "p_value": winner_loser_log["p_value"],
        },
        {
            "test_id": "DUR-06",
            "family": "duration",
            "test": "Winner minus loser median duration permutation",
            "effect": winner_loser_median["difference"],
            "p_value": winner_loser_median["p_value"],
        },
        {
            "test_id": "DUR-07",
            "family": "duration",
            "test": "Whole-minute duration count versus random-second reference",
            "effect": float(whole_minute_count - len(trades) / 60),
            "p_value": whole_minute_p,
        },
    ]
    return result, tests, fit_table


def temporal_analysis(trades: pd.DataFrame) -> tuple[dict[str, Any], dict[str, pd.DataFrame], list[dict[str, Any]]]:
    hourly = (
        trades.groupby("hour", observed=False)
        .agg(trades=("ticket", "size"), buy_rate=("side_code", "mean"), win_rate=("win", "mean"), mean_pnl=("pnl", "mean"), median_duration=("duration_minutes", "median"))
        .reindex(range(24), fill_value=0)
        .reset_index()
    )
    weekday = (
        trades.groupby("weekday", observed=False)
        .agg(trades=("ticket", "size"), buy_rate=("side_code", "mean"), win_rate=("win", "mean"), mean_pnl=("pnl", "mean"), median_duration=("duration_minutes", "median"))
        .reset_index()
    )
    monthly = (
        trades.groupby("month", observed=False)
        .agg(trades=("ticket", "size"), buy_rate=("side_code", "mean"), win_rate=("win", "mean"), mean_pnl=("pnl", "mean"), total_pnl=("pnl", "sum"), median_duration=("duration_minutes", "median"), mean_lot=("lot_size", "mean"))
        .reset_index()
    )
    five_minute = trades["minute_5"].value_counts().sort_index().reindex(range(0, 60, 5), fill_value=0)
    raw_bucket = (
        trades.groupby("clock_bucket", observed=False)
        .agg(trades=("ticket", "size"), buy_rate=("side_code", "mean"), win_rate=("win", "mean"), mean_pnl=("pnl", "mean"))
        .reset_index()
    )

    hour_chi = stats.chisquare(hourly["trades"].to_numpy())
    minute_chi = stats.chisquare(five_minute.to_numpy())
    observed_weekdays = weekday.loc[weekday["weekday"].isin(WEEKDAY_ORDER[:5]), "trades"].to_numpy(dtype=float)
    weekday_chi = stats.chisquare(observed_weekdays)
    side_bucket_table = pd.crosstab(trades["clock_bucket"], trades["side"]).reindex(
        index=CLOCK_BUCKET_ORDER, columns=["Buy", "Sell"], fill_value=0
    )
    side_bucket_chi = stats.chi2_contingency(side_bucket_table, correction=False)
    effect = cramer_v(side_bucket_table.to_numpy())

    bucket_codes = trades["clock_bucket"].cat.codes.to_numpy()
    labels = trades["side_code"].to_numpy()
    rng = np.random.default_rng(SEED + 7)
    null = np.empty(5_000, dtype=float)
    for index in range(null.size):
        shuffled = rng.permutation(labels)
        table = np.bincount(bucket_codes * 2 + shuffled, minlength=len(CLOCK_BUCKET_ORDER) * 2).reshape(-1, 2)
        null[index] = cramer_v(table)
    side_bucket_perm_p = float((np.count_nonzero(null >= effect) + 1) / (len(null) + 1))

    busiest_hour_row = hourly.loc[hourly["trades"].idxmax()]
    busiest_weekday_row = weekday.loc[weekday["trades"].idxmax()]
    result = {
        "busiest_raw_hour": int(busiest_hour_row["hour"]),
        "busiest_raw_hour_trades": int(busiest_hour_row["trades"]),
        "busiest_weekday": str(busiest_weekday_row["weekday"]),
        "busiest_weekday_trades": int(busiest_weekday_row["trades"]),
        "five_minute_counts": {str(int(k)): int(v) for k, v in five_minute.items()},
        "raw_clock_bucket_counts": {str(row.clock_bucket): int(row.trades) for row in raw_bucket.itertuples()},
        "uniform_hour_chi_square": float(hour_chi.statistic),
        "uniform_hour_p_value": float(hour_chi.pvalue),
        "uniform_minute_bin_chi_square": float(minute_chi.statistic),
        "uniform_minute_bin_p_value": float(minute_chi.pvalue),
        "uniform_weekday_chi_square": float(weekday_chi.statistic),
        "uniform_weekday_p_value": float(weekday_chi.pvalue),
        "side_clock_bucket_cramer_v": effect,
        "side_clock_bucket_chi_square_p_value": float(side_bucket_chi.pvalue),
        "side_clock_bucket_permutation_p_value": side_bucket_perm_p,
        "timezone_warning": "Timestamps are naive broker/export clock values. Clock buckets are not named market sessions.",
        "exposure_warning": "Counts estimate P(time | observed trade), not P(trade | time), because no-trade opportunities are absent.",
    }
    tests = [
        {
            "test_id": "TIME-01",
            "family": "timing",
            "test": "Observed hour counts versus 24-bin uniform reference",
            "effect": float(hour_chi.statistic),
            "p_value": float(hour_chi.pvalue),
        },
        {
            "test_id": "TIME-02",
            "family": "timing",
            "test": "Minute-of-hour 5-minute bins versus uniform reference",
            "effect": float(minute_chi.statistic),
            "p_value": float(minute_chi.pvalue),
        },
        {
            "test_id": "TIME-03",
            "family": "timing",
            "test": "Raw weekday counts versus five-bin uniform reference",
            "effect": float(weekday_chi.statistic),
            "p_value": float(weekday_chi.pvalue),
        },
        {
            "test_id": "TIME-04",
            "family": "timing",
            "test": "Direction versus raw-clock bucket permutation",
            "effect": effect,
            "p_value": side_bucket_perm_p,
        },
    ]
    tables = {
        "hourly": hourly,
        "weekday": weekday,
        "monthly": monthly,
        "clock_bucket": raw_bucket,
        "minute_5": five_minute.rename_axis("minute_start").rename("trades").reset_index(),
    }
    return result, tables, tests


def sizing_analysis(trades: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, Any]], pd.DataFrame]:
    data = trades.copy()
    data["size_above_base"] = data["lot_size"] > 0.01
    size_counts = (
        data.groupby("lot_size")
        .agg(trades=("ticket", "size"), buy_rate=("side_code", "mean"), win_rate=("win", "mean"), mean_pnl=("pnl", "mean"), median_duration=("duration_minutes", "median"))
        .reset_index()
    )
    side_table = pd.crosstab(data["side"], data["size_above_base"]).reindex(
        index=["Buy", "Sell"], columns=[False, True], fill_value=0
    )
    fisher_odds, fisher_p = stats.fisher_exact(side_table)
    rank_time = stats.spearmanr(np.arange(len(data)), data["lot_size"])
    rank_price = stats.spearmanr(data["observed_price"], data["lot_size"])
    available = data.dropna(subset=["previous_pnl"])
    prior_large = available.loc[available["size_above_base"], "previous_pnl"]
    prior_base = available.loc[~available["size_above_base"], "previous_pnl"]
    prior_perm = permutation_test(prior_large, prior_base, repetitions=10_000, seed=SEED + 8)
    recent_pnl = data["pnl"].shift(1).rolling(5, min_periods=1).sum()
    large_recent = recent_pnl[data["size_above_base"]].dropna()
    base_recent = recent_pnl[~data["size_above_base"]].dropna()
    recent_perm = permutation_test(large_recent, base_recent, repetitions=10_000, seed=SEED + 9)
    normalized_large = data.loc[data["size_above_base"], "pnl_per_0_01_lot"]
    normalized_base = data.loc[~data["size_above_base"], "pnl_per_0_01_lot"]
    normalized_size_perm = permutation_test(
        normalized_large, normalized_base, repetitions=20_000, seed=SEED + 109
    )
    large_wins = int(data.loc[data["size_above_base"], "win"].sum())
    all_large_win_probability = float(
        stats.hypergeom.pmf(
            large_wins,
            len(data),
            int(data["win"].sum()),
            int(data["size_above_base"].sum()),
        )
    )
    result = {
        "base_lot": 0.01,
        "size_counts": {str(k): int(v) for k, v in data["lot_size"].value_counts().sort_index().items()},
        "above_base_count": int(data["size_above_base"].sum()),
        "above_base_share": float(data["size_above_base"].mean()),
        "first_above_base_time": data.loc[data["size_above_base"], "open_time"].min().isoformat(),
        "last_above_base_time": data.loc[data["size_above_base"], "open_time"].max().isoformat(),
        "side_size_fisher_odds_ratio": json_number(fisher_odds),
        "side_size_fisher_p_value": float(fisher_p),
        "size_time_spearman_rho": float(rank_time.statistic),
        "size_time_spearman_p_value": float(rank_time.pvalue),
        "size_price_spearman_rho": float(rank_price.statistic),
        "size_price_spearman_p_value": float(rank_price.pvalue),
        "previous_pnl_large_minus_base_permutation": prior_perm,
        "previous_five_trade_pnl_large_minus_base_permutation": recent_perm,
        "normalized_pnl_large_minus_base_permutation": normalized_size_perm,
        "above_base_win_count": large_wins,
        "all_above_base_win_hypergeometric_probability": all_large_win_probability,
        "equity_limitation": "Account balance/equity is absent, so equity-based sizing cannot be tested directly.",
    }
    tests = [
        {
            "test_id": "SIZE-01",
            "family": "sizing",
            "test": "Direction versus above-base size Fisher exact",
            "effect": json_number(fisher_odds),
            "p_value": float(fisher_p),
        },
        {
            "test_id": "SIZE-02",
            "family": "sizing",
            "test": "Lot size versus chronological index Spearman",
            "effect": float(rank_time.statistic),
            "p_value": float(rank_time.pvalue),
        },
        {
            "test_id": "SIZE-03",
            "family": "sizing",
            "test": "Lot size versus observed price Spearman",
            "effect": float(rank_price.statistic),
            "p_value": float(rank_price.pvalue),
        },
        {
            "test_id": "SIZE-04",
            "family": "sizing",
            "test": "Previous-trade P&L before large versus base size permutation",
            "effect": prior_perm["difference"],
            "p_value": prior_perm["p_value"],
        },
        {
            "test_id": "SIZE-05",
            "family": "sizing",
            "test": "Previous-five-trade P&L before large versus base size permutation",
            "effect": recent_perm["difference"],
            "p_value": recent_perm["p_value"],
        },
        {
            "test_id": "SIZE-06",
            "family": "sizing",
            "test": "Size-normalized P&L large minus base size permutation",
            "effect": normalized_size_perm["difference"],
            "p_value": normalized_size_perm["p_value"],
        },
        {
            "test_id": "SIZE-07",
            "family": "sizing",
            "test": "All above-base observations positive under exchangeable outcomes",
            "effect": float(large_wins),
            "p_value": all_large_win_probability,
        },
    ]
    return result, tests, size_counts


def clustering_analysis(trades: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, Any]], pd.DataFrame]:
    gaps = trades["gap_from_previous_close_minutes"].dropna()
    non_overlap = gaps[gaps >= 0]
    overlap_records: list[dict[str, Any]] = []
    for new_index, new_trade in trades.iterrows():
        active = trades.loc[
            (trades.index < new_index)
            & (trades["open_time"] < new_trade["open_time"])
            & (trades["close_time"] > new_trade["open_time"])
        ]
        for prior in active.itertuples():
            overlap_records.append(
                {
                    "prior_ticket": prior.ticket,
                    "new_ticket": new_trade["ticket"],
                    "prior_side": prior.side,
                    "new_side": new_trade["side"],
                    "same_direction": prior.side == new_trade["side"],
                    "prior_open_time": prior.open_time,
                    "new_open_time": new_trade["open_time"],
                    "entry_delta_seconds": float((new_trade["open_time"] - prior.open_time).total_seconds()),
                    "prior_close_time": prior.close_time,
                    "new_close_time": new_trade["close_time"],
                    "common_overlap_seconds": float(
                        (min(prior.close_time, new_trade["close_time"]) - new_trade["open_time"]).total_seconds()
                    ),
                    "prior_lot_size": prior.lot_size,
                    "new_lot_size": new_trade["lot_size"],
                    "prior_observed_price": prior.observed_price,
                    "new_observed_price": new_trade["observed_price"],
                }
            )
    overlap_rows = pd.DataFrame(overlap_records)
    reentry: dict[str, Any] = {}
    for threshold in [1, 5, 15, 30, 60, 240]:
        mask = trades["gap_from_previous_close_minutes"].between(0, threshold, inclusive="both")
        reentry[str(threshold)] = {
            "count": int(mask.sum()),
            "same_direction_count": int((mask & trades["same_direction_as_previous"]).sum()),
            "same_direction_rate": float(trades.loc[mask, "same_direction_as_previous"].mean()) if mask.any() else None,
        }

    within_day_gaps: list[float] = []
    daily_sizes: list[int] = []
    for _, group in trades.groupby("open_date"):
        daily_sizes.append(len(group))
        minutes = (
            group["open_time"].dt.hour * 60
            + group["open_time"].dt.minute
            + group["open_time"].dt.second / 60.0
        ).sort_values()
        within_day_gaps.extend(np.diff(minutes).tolist())
    observed_bursts = int(np.count_nonzero(np.asarray(within_day_gaps) <= 30.0))
    rng = np.random.default_rng(SEED + 10)
    simulated = np.empty(5_000, dtype=int)
    empirical_minutes = (
        trades["open_time"].dt.hour * 60
        + trades["open_time"].dt.minute
        + trades["open_time"].dt.second / 60.0
    ).to_numpy(dtype=float)
    for simulation in range(len(simulated)):
        count = 0
        for n in daily_sizes:
            if n > 1:
                times = np.sort((rng.choice(empirical_minutes, size=n, replace=True) + rng.uniform(-2.5, 2.5, size=n)) % (24 * 60))
                count += int(np.count_nonzero(np.diff(times) <= 30.0))
        simulated[simulation] = count
    burst_p = float((np.count_nonzero(simulated >= observed_bursts) + 1) / (len(simulated) + 1))
    result = {
        "maximum_concurrency": int(1 + trades["active_positions_before_entry"].max()),
        "entries_while_active": int(trades["entry_while_position_active"].sum()),
        "same_direction_overlap_pairs": int(overlap_rows["same_direction"].sum()) if not overlap_rows.empty else 0,
        "opposite_direction_overlap_pairs": int((~overlap_rows["same_direction"]).sum()) if not overlap_rows.empty else 0,
        "median_non_overlap_gap_minutes": float(non_overlap.median()),
        "gap_quantiles_minutes": {
            str(level): float(non_overlap.quantile(level)) for level in [0.05, 0.25, 0.50, 0.75, 0.90, 0.95]
        },
        "reentry_after_previous_close": reentry,
        "same_day_gaps_le_30_minutes": observed_bursts,
        "empirical_clock_iid_null_mean": float(simulated.mean()),
        "empirical_clock_iid_null_p_value": burst_p,
        "null_warning": "The null preserves daily trade counts and the global raw-clock distribution but still lacks true market opportunity exposure.",
    }
    tests = [
        {
            "test_id": "CLUST-01",
            "family": "clustering",
            "test": "Same-day gaps <=30 minutes versus empirical-clock IID null",
            "effect": float(observed_bursts - simulated.mean()),
            "p_value": burst_p,
        }
    ]
    return result, tests, overlap_rows


def _model_feature_matrix(trades: pd.DataFrame, *, latent_only: bool = False) -> tuple[np.ndarray, list[str]]:
    gap = trades["gap_from_previous_entry_minutes"].copy()
    gap = gap.fillna(gap.median()).clip(lower=0)
    hour_angle = 2.0 * np.pi * (trades["hour"] + trades["minute"] / 60.0) / 24.0
    base = {
        "hour_sin": np.sin(hour_angle),
        "hour_cos": np.cos(hour_angle),
        "log_duration": np.log1p(trades["duration_minutes"]),
        "size_normalized_pnl": trades["pnl_per_0_01_lot"],
        "log_entry_gap": np.log1p(gap),
    }
    if not latent_only:
        base = {
            "side_buy": trades["side_code"].astype(float),
            **base,
            "lot_size": trades["lot_size"],
        }
    feature_frame = pd.DataFrame(base)
    scaled = StandardScaler().fit_transform(feature_frame)
    return scaled, feature_frame.columns.tolist()


def latent_model_analysis(
    trades: pd.DataFrame,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    features, feature_names = _model_feature_matrix(trades, latent_only=True)
    gmm_rows: list[dict[str, Any]] = []
    labels_by_k: dict[int, np.ndarray] = {}
    models: dict[int, GaussianMixture] = {}
    maximum_components = 6
    for components in range(1, maximum_components + 1):
        model = GaussianMixture(
            n_components=components,
            covariance_type="diag",
            n_init=20,
            random_state=SEED,
            reg_covar=1e-3,
        ).fit(features)
        labels = model.predict(features)
        component_counts = np.bincount(labels, minlength=components)
        models[components] = model
        labels_by_k[components] = labels
        silhouette = silhouette_score(features, labels) if components > 1 and len(np.unique(labels)) > 1 else np.nan
        gmm_rows.append(
            {
                "model": "Gaussian mixture",
                "components": components,
                "aic": float(model.aic(features)),
                "bic": float(model.bic(features)),
                "silhouette": json_number(silhouette),
                "log_likelihood": float(model.score(features) * len(features)),
                "minimum_component_size": int(component_counts.min()),
                "maximum_component_share": float(component_counts.max() / len(features)),
            }
        )
    gmm_table = pd.DataFrame(gmm_rows)
    best_components = int(gmm_table.loc[gmm_table["bic"].idxmin(), "components"])
    best_labels = labels_by_k[best_components]
    stability_scores: list[float] = []
    for seed in [7, 19, 43, 101, 509]:
        alternative = GaussianMixture(
            n_components=best_components,
            covariance_type="diag",
            n_init=10,
            random_state=seed,
            reg_covar=1e-3,
        ).fit(features)
        stability_scores.append(adjusted_rand_score(best_labels, alternative.predict(features)))
    cluster_source = trades.copy()
    cluster_source["component"] = best_labels
    profiles = (
        cluster_source.groupby("component")
        .agg(
            trades=("ticket", "size"),
            buy_rate=("side_code", "mean"),
            win_rate=("win", "mean"),
            mean_pnl=("pnl", "mean"),
            median_duration=("duration_minutes", "median"),
            mean_lot=("lot_size", "mean"),
            median_hour=("hour", "median"),
            median_gap=("gap_from_previous_entry_minutes", "median"),
        )
        .reset_index()
    )

    hmm_rows: list[dict[str, Any]] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        maximum_states = 6
        for states in range(1, maximum_states + 1):
            try:
                model = GaussianHMM(
                    n_components=states,
                    covariance_type="diag",
                    n_iter=500,
                    tol=1e-4,
                    random_state=SEED,
                    min_covar=1e-4,
                ).fit(features)
                log_likelihood = float(model.score(features))
                state_counts = np.bincount(model.predict(features), minlength=states)
                dimension = features.shape[1]
                parameters = (states - 1) + states * (states - 1) + states * dimension * 2
                hmm_rows.append(
                    {
                        "states": states,
                        "parameters": parameters,
                        "log_likelihood": log_likelihood,
                        "aic": 2 * parameters - 2 * log_likelihood,
                        "bic": parameters * math.log(len(features)) - 2 * log_likelihood,
                        "converged": bool(model.monitor_.converged),
                        "minimum_state_size": int(state_counts.min()),
                        "maximum_state_share": float(state_counts.max() / len(features)),
                    }
                )
            except Exception as exc:
                hmm_rows.append(
                    {
                        "states": states,
                        "parameters": np.nan,
                        "log_likelihood": np.nan,
                        "aic": np.nan,
                        "bic": np.nan,
                        "converged": False,
                        "error": str(exc),
                    }
                )
    hmm_table = pd.DataFrame(hmm_rows)
    valid_hmm = hmm_table.dropna(subset=["bic"])
    best_hmm_states = int(valid_hmm.loc[valid_hmm["bic"].idxmin(), "states"]) if not valid_hmm.empty else None
    gmm_bic_one = float(gmm_table.loc[gmm_table["components"] == 1, "bic"].iloc[0])
    gmm_bic_best = float(gmm_table["bic"].min())
    result = {
        "feature_names": feature_names,
        "gmm_best_components_by_bic": best_components,
        "gmm_bic_improvement_over_one_component": gmm_bic_one - gmm_bic_best,
        "gmm_seed_stability_adjusted_rand_mean": float(np.mean(stability_scores)),
        "gmm_seed_stability_adjusted_rand_min": float(np.min(stability_scores)),
        "gmm_best_at_search_boundary": bool(best_components == maximum_components),
        "hmm_best_states_by_bic": best_hmm_states,
        "hmm_best_at_search_boundary": bool(best_hmm_states == maximum_states),
        "interpretation_warning": "Components/states are statistical summaries of observed trade attributes, not proof of separate source algorithms or market regimes.",
    }
    return result, gmm_table, profiles, hmm_table


def _max_split_gain(values: np.ndarray, minimum_segment: int) -> tuple[float, int]:
    x = np.asarray(values, dtype=float)
    n = len(x)
    cumulative = np.concatenate([[0.0], np.cumsum(x)])
    cumulative_squared = np.concatenate([[0.0], np.cumsum(x * x)])

    def sse(start: int, end: int) -> float:
        count = end - start
        total = cumulative[end] - cumulative[start]
        total_squared = cumulative_squared[end] - cumulative_squared[start]
        return float(total_squared - total * total / count)

    total_sse = sse(0, n)
    best_gain = -np.inf
    best_split = minimum_segment
    for split in range(minimum_segment, n - minimum_segment + 1):
        gain = total_sse - sse(0, split) - sse(split, n)
        if gain > best_gain:
            best_gain = gain
            best_split = split
    return float(best_gain), int(best_split)


def _max_mean_shift_t(values: np.ndarray, minimum_segment: int = 20) -> tuple[float, int]:
    x = np.asarray(values, dtype=float)
    n = len(x)
    splits = np.arange(minimum_segment, n - minimum_segment + 1)
    if splits.size == 0:
        return math.nan, -1
    cumulative = np.cumsum(x)
    left_mean = cumulative[splits - 1] / splits
    right_mean = (cumulative[-1] - cumulative[splits - 1]) / (n - splits)
    scale = np.std(x, ddof=1)
    if scale == 0:
        return 0.0, int(splits[0])
    statistic = np.abs(left_mean - right_mean) / (scale * np.sqrt(1 / splits + 1 / (n - splits)))
    location = int(np.argmax(statistic))
    return float(statistic[location]), int(splits[location])


def _mean_shift_permutation_p(
    values: np.ndarray,
    observed: float,
    *,
    repetitions: int,
    seed: int,
    minimum_segment: int = 20,
) -> float:
    rng = np.random.default_rng(seed)
    extreme = 0
    for _ in range(repetitions):
        statistic, _ = _max_mean_shift_t(rng.permutation(values), minimum_segment)
        extreme += statistic >= observed
    return float((extreme + 1) / (repetitions + 1))


def holding_regime_analysis(trades: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Recursive, multiplicity-sensitive scan for log-holding-time mean shifts."""

    log_seconds = np.log(trades["duration_seconds"].to_numpy(dtype=float))
    scans: list[dict[str, Any]] = []

    def scan(lo: int, hi: int, depth: int) -> None:
        segment = log_seconds[lo:hi]
        if len(segment) < 40:
            return
        statistic, relative_split = _max_mean_shift_t(segment, 20)
        if relative_split < 0:
            return
        split = lo + relative_split
        p_value = _mean_shift_permutation_p(
            segment,
            statistic,
            repetitions=20_000,
            seed=20260922 + lo * 17 + hi * 31 + depth,
            minimum_segment=20,
        )
        scans.append(
            {
                "segment_start_index": lo,
                "segment_end_index_exclusive": hi,
                "depth": depth,
                "split_index": split,
                "left_last_open_time": trades.iloc[split - 1]["open_time"].isoformat(),
                "right_first_open_time": trades.iloc[split]["open_time"].isoformat(),
                "max_studentized_mean_shift": statistic,
                "permutation_p_value": p_value,
            }
        )
        if p_value < 0.01 and depth < 2:
            scan(lo, split, depth + 1)
            scan(split, hi, depth + 1)

    scan(0, len(trades), 0)
    scan_table = pd.DataFrame(scans).sort_values(["split_index", "depth"]).reset_index(drop=True)
    primary_boundaries = sorted(
        scan_table.loc[scan_table["permutation_p_value"] <= 0.002, "split_index"].astype(int).unique().tolist()
    )
    boundaries = [0, *primary_boundaries, len(trades)]
    phases: list[dict[str, Any]] = []
    for phase, (lo, hi) in enumerate(zip(boundaries[:-1], boundaries[1:], strict=True), start=1):
        segment = trades.iloc[lo:hi]
        winners = segment.loc[segment["win"], "duration_minutes"]
        losers = segment.loc[~segment["win"], "duration_minutes"]
        phases.append(
            {
                "phase": phase,
                "start_index": lo,
                "end_index_exclusive": hi,
                "start_open_time": segment["open_time"].iloc[0].isoformat(),
                "end_open_time": segment["open_time"].iloc[-1].isoformat(),
                "trades": len(segment),
                "mean_duration_minutes": float(segment["duration_minutes"].mean()),
                "median_duration_minutes": float(segment["duration_minutes"].median()),
                "geometric_mean_duration_minutes": float(np.exp(np.log(segment["duration_minutes"]).mean())),
                "winner_median_duration_minutes": float(winners.median()),
                "loser_median_duration_minutes": float(losers.median()),
                "winner_minus_loser_mean_log_duration": float(np.log(winners).mean() - np.log(losers).mean()),
            }
        )
    phase_table = pd.DataFrame(phases)
    total_rss = float(np.sum((log_seconds - log_seconds.mean()) ** 2))
    segmented_rss = 0.0
    for lo, hi in zip(boundaries[:-1], boundaries[1:], strict=True):
        segment = log_seconds[lo:hi]
        segmented_rss += float(np.sum((segment - segment.mean()) ** 2))
    n = len(log_seconds)
    single_bic = n * math.log(total_rss / n) + 2 * math.log(n)
    segmented_parameters = len(phases) + 1 + len(primary_boundaries)
    segmented_bic = n * math.log(segmented_rss / n) + segmented_parameters * math.log(n)
    result = {
        "primary_boundary_indices": primary_boundaries,
        "primary_boundary_times": [trades.iloc[index]["open_time"].isoformat() for index in primary_boundaries],
        "primary_phase_count": len(phases),
        "log_duration_rss_reduction": float(1 - segmented_rss / total_rss),
        "single_mean_bic": single_bic,
        "segmented_mean_bic": segmented_bic,
        "segmented_minus_single_bic": segmented_bic - single_bic,
        "winner_longer_in_every_primary_phase": bool(
            (phase_table["winner_minus_loser_mean_log_duration"] > 0).all()
        ),
        "warning": "Recursive p-values are exploratory and not fully family-wise corrected. Market-volatility changes can create the same holding-time phases under one fixed rule.",
    }
    return result, scan_table, phase_table


def _block_permutation(values: np.ndarray, rng: np.random.Generator, block_size: int = 10) -> np.ndarray:
    blocks = [values[start : start + block_size] for start in range(0, len(values), block_size)]
    order = rng.permutation(len(blocks))
    return np.concatenate([blocks[index] for index in order])


def change_point_analysis(trades: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, list[dict[str, Any]]]:
    series = {
        "buy_indicator": trades["side_code"].to_numpy(dtype=float),
        "win_indicator": trades["win"].to_numpy(dtype=float),
        "log_duration": np.log1p(trades["duration_minutes"].to_numpy(dtype=float)),
        "pnl": trades["pnl"].to_numpy(dtype=float),
        "pnl_per_0_01_lot": trades["pnl_per_0_01_lot"].to_numpy(dtype=float),
        "lot_size": trades["lot_size"].to_numpy(dtype=float),
        "raw_hour_sine": np.sin(2 * np.pi * (trades["hour"] + trades["minute"] / 60.0) / 24.0),
        "raw_hour_cosine": np.cos(2 * np.pi * (trades["hour"] + trades["minute"] / 60.0) / 24.0),
    }
    rng = np.random.default_rng(SEED + 11)
    rows: list[dict[str, Any]] = []
    for name, values in series.items():
        standardized = (values - np.mean(values)) / (np.std(values, ddof=1) or 1.0)
        observed_gain, split = _max_split_gain(standardized, 50)
        null = np.empty(2_000, dtype=float)
        block_null = np.empty(2_000, dtype=float)
        for index in range(len(null)):
            null[index], _ = _max_split_gain(rng.permutation(standardized), 50)
            block_null[index], _ = _max_split_gain(_block_permutation(standardized, rng), 50)
        iid_p_value = float((np.count_nonzero(null >= observed_gain) + 1) / (len(null) + 1))
        block_p_value = float((np.count_nonzero(block_null >= observed_gain) + 1) / (len(block_null) + 1))
        rows.append(
            {
                "feature": name,
                "split_trade_index": split,
                "split_open_time": trades.iloc[split]["open_time"].isoformat(),
                "mean_before": float(np.mean(values[:split])),
                "mean_after": float(np.mean(values[split:])),
                "standardized_sse_gain": observed_gain,
                "iid_permutation_p_value": iid_p_value,
                "block_permutation_p_value": block_p_value,
                "minimum_segment": 50,
            }
        )
    table = pd.DataFrame(rows)
    table["fdr_q_value"] = benjamini_hochberg(table["block_permutation_p_value"])
    table["fdr_5pct_significant"] = table["fdr_q_value"] <= 0.05

    feature_frame = pd.DataFrame(series)
    standardized_frame = StandardScaler().fit_transform(feature_frame)
    penalty = math.log(len(trades)) * standardized_frame.shape[1]
    pelt_breaks = rpt.Pelt(model="rbf", min_size=30, jump=1).fit(standardized_frame).predict(pen=penalty)
    pelt_breaks = [point for point in pelt_breaks if point < len(trades)]
    sensitivity: dict[str, list[str]] = {}
    for multiplier in [0.5, 1.0, 2.0, 4.0]:
        breaks = rpt.Pelt(model="rbf", min_size=30, jump=1).fit(standardized_frame).predict(pen=penalty * multiplier)
        sensitivity[str(multiplier)] = [trades.iloc[p]["open_time"].isoformat() for p in breaks if p < len(trades)]
    result = {
        "pelt_penalty": penalty,
        "pelt_break_indices": pelt_breaks,
        "pelt_break_times": [trades.iloc[point]["open_time"].isoformat() for point in pelt_breaks],
        "pelt_penalty_sensitivity": sensitivity,
        "univariate_fdr_significant_features": table.loc[table["fdr_5pct_significant"], "feature"].tolist(),
        "warning": "Trade-derived change points show behavioral shifts, not their market cause and not automatically separate algorithms.",
    }
    tests = [
        {
            "test_id": f"CP-{index + 1:02d}",
            "family": "change_point",
            "test": f"Maximum one-change scan: {row.feature}",
            "effect": float(row.standardized_sse_gain),
            "p_value": float(row.block_permutation_p_value),
        }
        for index, row in enumerate(table.itertuples())
    ]
    return result, table, tests


def anomaly_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    features, _ = _model_feature_matrix(trades)
    model = IsolationForest(n_estimators=500, contamination=0.03, random_state=SEED).fit(features)
    scores = -model.score_samples(features)
    result = trades[
        ["ticket", "side", "open_time", "close_time", "lot_size", "observed_price", "pnl", "duration_minutes"]
    ].copy()
    result["anomaly_score"] = scores
    result["anomaly_rank"] = result["anomaly_score"].rank(ascending=False, method="first").astype(int)
    result["interpretation"] = "Statistically inconsistent with the dominant observed trade-attribute pattern; cause unknown."
    return result.sort_values("anomaly_rank").head(15)


def walk_forward_behavior(trades: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    months = sorted(trades["month"].unique())
    rows: list[dict[str, Any]] = []
    for index in range(3, len(months)):
        train_months = months[:index]
        test_month = months[index]
        train = trades[trades["month"].isin(train_months)]
        test = trades[trades["month"] == test_month]
        rows.append(
            {
                "test_month": test_month,
                "train_start": train_months[0],
                "train_end": train_months[-1],
                "train_trades": len(train),
                "test_trades": len(test),
                "predicted_buy_rate": train["side_code"].mean(),
                "observed_buy_rate": test["side_code"].mean(),
                "absolute_buy_rate_error": abs(train["side_code"].mean() - test["side_code"].mean()),
                "predicted_win_rate": train["win"].mean(),
                "observed_win_rate": test["win"].mean(),
                "absolute_win_rate_error": abs(train["win"].mean() - test["win"].mean()),
                "predicted_mean_pnl": train["pnl"].mean(),
                "observed_mean_pnl": test["pnl"].mean(),
                "absolute_mean_pnl_error": abs(train["pnl"].mean() - test["pnl"].mean()),
                "predicted_median_duration": train["duration_minutes"].median(),
                "observed_median_duration": test["duration_minutes"].median(),
                "absolute_median_duration_error": abs(
                    train["duration_minutes"].median() - test["duration_minutes"].median()
                ),
            }
        )
    table = pd.DataFrame(rows)
    result = {
        "folds": int(len(table)),
        "mean_absolute_buy_rate_error": float(table["absolute_buy_rate_error"].mean()),
        "mean_absolute_win_rate_error": float(table["absolute_win_rate_error"].mean()),
        "mean_absolute_mean_pnl_error": float(table["absolute_mean_pnl_error"].mean()),
        "mean_absolute_median_duration_error": float(table["absolute_median_duration_error"].mean()),
        "scope_warning": "This is expanding-window stability of observed behavior, not strategy replay or out-of-sample entry/exit reconstruction.",
    }
    return result, table


def apply_multiple_testing(tests: list[dict[str, Any]]) -> pd.DataFrame:
    table = pd.DataFrame(tests)
    table["p_value"] = pd.to_numeric(table["p_value"], errors="coerce")
    table["fdr_q_value_all_tests"] = benjamini_hochberg(table["p_value"])
    table["fdr_5pct_significant"] = table["fdr_q_value_all_tests"] <= 0.05
    table["bonferroni_5pct_significant"] = table["p_value"] <= 0.05 / table["p_value"].notna().sum()
    return table


def make_tracking_tables(metrics: dict[str, Any], tests: pd.DataFrame) -> dict[str, pd.DataFrame]:
    significant = set(tests.loc[tests["fdr_5pct_significant"], "test_id"])
    experiments = pd.DataFrame(
        [
            ["H01", "Direction sequence is IID", "Ordered Buy/Sell sequence", "Runs, LR and permutation tests", "See DIR-02 to DIR-05", metrics["direction"]["iid_vs_first_order_p_value"], "Expanding-month direction stability only", "Supported" if "DIR-04" not in significant else "Rejected"],
            ["H02", "Buy and Sell outcomes differ", "P&L, win rate and duration by side", "Permutation, Mann-Whitney, chi-square", "See PNL/DUR tests", metrics["profit"]["buy_sell_mean_permutation"]["p_value"], "No market-state OOS test", "Evidence-dependent"],
            ["H03", "Timing is non-uniform in raw clock", "Open timestamps", "Chi-square reference tests", "See TIME-01 to TIME-03", metrics["temporal"]["uniform_hour_p_value"], "Timezone and exposure unavailable", "Descriptive support"],
            ["H04", "Direction varies by raw-clock bucket", "Side and timestamp", "Permutation Cramer's V", "See TIME-04", metrics["temporal"]["side_clock_bucket_permutation_p_value"], "No session mapping without timezone", "Evidence-dependent"],
            ["H05", "Large sizes follow recent performance", "Lot and prior P&L", "Label permutation", "See SIZE-04 and SIZE-05", metrics["sizing"]["previous_five_trade_pnl_large_minus_base_permutation"]["p_value"], "Equity unavailable", "Evidence-dependent"],
            ["H06", "Trades form short-gap bursts", "Within-day entry gaps", "Empirical-clock IID simulation", "See CLUST-01", metrics["clustering"]["empirical_clock_iid_null_p_value"], "Exact opportunity window unavailable", "Evidence-dependent"],
            ["H07", "Multiple observed trade-attribute components exist", "Side/time/duration/P&L/lot/gap", "GMM BIC and seed stability", f"Best GMM components: {metrics['latent_models']['gmm_best_components_by_bic']}", np.nan, "No market-state labels", "Exploratory"],
            ["H08", "Behavior has structural change points", "Ordered trade features", "PELT and permutation scans with FDR", f"PELT breaks: {len(metrics['change_points']['pelt_break_indices'])}", np.nan, "Penalty sensitivity reported", "Evidence-dependent"],
            ["H09", "Entries are indicator/rule driven", "Requires synchronized OHLC/ticks and no-trade rows", "Time-aware classification and rule discovery", "Not testable from TSV", np.nan, "Blocked", "Unsupported with current data"],
            ["H10", "Exits use fixed/trailing/volatility rules", "Requires exit price and within-trade path", "MFE/MAE, exit-distance clusters, replay", "Not testable from TSV", np.nan, "Blocked", "Unsupported with current data"],
        ],
        columns=["ID", "Hypothesis", "Evidence", "Method", "Result", "p_value", "OOS_Result", "Status"],
    )

    proof_log = pd.DataFrame(
        [
            ["The file contains 423 complete eight-field rows.", "Physical row/field validation; no empty cells.", "Exact counts and uniqueness checks.", "The supplied file is the complete intended export.", "Rows may omit other broker fields or open/pending orders.", "Strong"],
            ["The observed record is XAUUSD.f only.", "All 423 symbol fields are identical.", "Exact categorical count.", "Symbol text was exported without transformation.", "The suffix may represent a broker-specific derivative/contract.", "Strong for label; weak for exact contract"],
            ["Most observed positions use 0.01 size.", "401 of 423 rows are 0.01.", "Exact categorical count with Wilson interval for exceptions.", "Field 6 is position size/lots as it appears.", "Field may use broker-specific units.", "Strong descriptively"],
            ["The sequence has a high observed win fraction.", f"{metrics['summary']['positive_count']} positive and {metrics['summary']['negative_count']} negative rows.", "Exact count and Wilson interval.", "Field 8 is comparable realized P&L and zero rows were not filtered.", "Export selection or omitted fees may inflate the rate.", "Strong descriptively"],
            ["Exact entry logic is not identified.", "No synchronized market states or rejected/no-trade opportunities.", "Identifiability argument and missing counterfactual class.", "Different rules can generate the same finite trades.", "Broker/source code could resolve the ambiguity.", "Strong"],
            ["Anomalous rows do not prove manual intervention.", "Isolation Forest ranks multivariate outliers only.", "Unsupervised anomaly score.", "Dominant observed pattern is an appropriate reference.", "Regime adaptation, data issues, and execution effects can also create outliers.", "Strong limitation"],
        ],
        columns=["Claim", "Evidence", "Mathematical_test", "Assumptions", "Alternative_explanation", "Confidence"],
    )

    candidate_ranking = pd.DataFrame(
        [
            ["Short-horizon, mostly fixed-size trading process", "High descriptive fit to duration/size", "Behavioral stability only", "Low", "Report sensitivity tables", "Supported as behavior, not entry family"],
            ["Raw-clock/session filter", "Timing concentration can be measured", "Cannot map to sessions without timezone", "Low", "Clock bucket stability", "Plausible only"],
            ["One adaptive strategy", "Compare BIC/HMM/changepoints", "No market-state replication", "Moderate", "Mixture seed and penalty sensitivity", "Unresolved"],
            ["Multiple independent strategies", "Compare BIC/HMM/changepoints", "No source labels or market replay", "Moderate", "Mixture seed and penalty sensitivity", "Unresolved"],
            ["Trend or momentum entry", "No direct fit possible", "Blocked", "Unknown", "Requires OHLC/ticks", "Unsupported"],
            ["Mean-reversion entry", "No direct fit possible", "Blocked", "Unknown", "Requires OHLC/ticks", "Unsupported"],
            ["Breakout/price-action entry", "No direct fit possible", "Blocked", "Unknown", "Requires OHLC/ticks", "Unsupported"],
            ["Fixed TP/SL, trailing, signal or volatility exit", "No direct fit possible", "Blocked", "Unknown", "Requires exit price and path", "Unsupported"],
        ],
        columns=["Candidate", "In_sample_fit", "Out_of_sample_fit", "Complexity", "Stability", "Evidence"],
    )

    confidence = pd.DataFrame(
        [
            ["Direction logic", "Near-balanced observed Buy/Sell sequence; exact rule unknown", "Weak"],
            ["Entry", "Not reconstructable without synchronized market/no-trade data", "Unsupported"],
            ["Exit", "Short observed holds; exit mechanism unknown", "Weak"],
            ["Position size", "0.01 base with 22 larger observations; causal rule unknown", "Moderate descriptively"],
            ["Session filter", "Raw-clock concentration only; timezone unknown", "Weak"],
            ["Risk control", "Trade-level P&L visible; equity, SL/TP and account risk absent", "Unsupported"],
            ["Re-entry", "Can quantify close-to-next-open gaps and direction", "Moderate descriptively"],
            ["One versus multiple systems", "Trade-attribute mixture/state evidence only", "Weak"],
        ],
        columns=["Component", "Reconstruction", "Confidence"],
    )
    return {
        "experiment_tracker": experiments,
        "proof_log": proof_log,
        "candidate_ranking": candidate_ranking,
        "confidence_table": confidence,
    }


def field_dictionary() -> pd.DataFrame:
    return pd.DataFrame(
        [
            [1, "ticket", "Text identifier", "Observed", "Order/deal/position/ticket semantics unknown; preserve leading zero."],
            [2, "side", "Buy or Sell", "Observed", "Direction label."],
            [3, "open_time", "Interval start / apparent open", "Structurally inferred", "Naive second-resolution timestamp; timezone unknown."],
            [4, "close_time", "Interval end / apparent close", "Structurally inferred", "Always later than field 3; timezone unknown."],
            [5, "symbol", "XAUUSD.f", "Observed", "Exact broker contract and suffix semantics unknown."],
            [6, "lot_size", "Size-like decimal", "Apparent", "Likely lots; broker unit/contract value unknown."],
            [7, "observed_price", "Price-like decimal", "Unknown semantics", "Could be entry, exit, average, or another price."],
            [8, "pnl", "Signed result", "Apparent", "Currency and inclusion of commission/swap/fees unknown."],
        ],
        columns=["Position", "Working_name", "Observed_structure", "Certainty", "Limitation"],
    )


def specification_coverage(market_data_used: bool) -> pd.DataFrame:
    trade_only_done = {
        1, 2, 4, 5, 6, 7, 8, 9, 10, 20, 21, 26, 29, 31, 32, 33, 34, 39, 40, 41, 42, 43, 44, 47, 48, 49, 50, 51
    }
    market_required = {11, 12, 13, 15, 16, 17, 18, 22, 23, 24, 25, 27, 28, 30, 35, 36, 37, 38}
    rows = []
    titles = {
        0: "Mission", 1: "Data forensics", 2: "Dataset facts", 3: "Instrument", 4: "Temporal structure",
        5: "One versus multiple", 6: "Directional sequence", 7: "Profit distribution", 8: "Holding time",
        9: "Position sizing", 10: "Trade clustering", 11: "Market data", 12: "Market state", 13: "Entry decision",
        14: "Research and candidate search", 15: "Candidate families", 16: "Incremental indicator power",
        17: "Supervised classification", 18: "Symbolic rule discovery", 19: "MDL/model selection", 20: "Hidden states",
        21: "Change points", 22: "Exit algorithm", 23: "MFE/MAE", 24: "SL/TP", 25: "Market regimes",
        26: "Selection bias", 27: "No-trade dataset", 28: "Reproduction", 29: "Walk-forward", 30: "OOS score",
        31: "Null models", 32: "Bootstrap", 33: "Multiple testing", 34: "Overfitting defense",
        35: "Exact reconstruction", 36: "Parameter estimation", 37: "Sensitivity", 38: "Feed mismatch",
        39: "Execution separation", 40: "Human-intervention anomalies", 41: "Fingerprint", 42: "Candidate ranking",
        43: "Identification level", 44: "Identifiability", 45: "Research requirement", 46: "Similar projects",
        47: "Experiment tracker", 48: "Proof log", 49: "Final report A-T", 50: "Additional data", 51: "Final principle",
    }
    for section in range(52):
        if section in market_required and not market_data_used:
            status = "Blocked by missing synchronized market/broker data"
        elif section in trade_only_done:
            status = "Completed or completed within trade-only scope"
        elif section in {3, 14, 19, 45, 46}:
            status = "Completed with explicit contract/data limitations"
        else:
            status = "Partially completed; current-data ceiling documented"
        rows.append([section, titles.get(section, ""), status])
    return pd.DataFrame(rows, columns=["Section", "Requirement", "Status"])


def save_plots(trades: pd.DataFrame, tables: dict[str, pd.DataFrame], figures_dir: Path, change_table: pd.DataFrame) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")
    blue = "#1F4E78"
    orange = "#D97706"
    red = "#B91C1C"
    green = "#2E7D32"

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    trades["side"].value_counts().reindex(["Buy", "Sell"]).plot.bar(ax=axes[0, 0], color=[blue, orange])
    axes[0, 0].set_title("Observed direction counts")
    axes[0, 0].set_xlabel("")
    axes[0, 0].set_ylabel("Trades")
    axes[0, 0].tick_params(axis="x", rotation=0)
    axes[0, 1].hist(trades["pnl"], bins=40, color=blue, edgecolor="white")
    axes[0, 1].axvline(0, color=red, linewidth=1)
    axes[0, 1].set_title("P&L distribution")
    axes[0, 1].set_xlabel("Observed P&L units")
    axes[1, 0].hist(trades["duration_minutes"], bins=50, color=orange, edgecolor="white")
    axes[1, 0].set_title("Holding time distribution")
    axes[1, 0].set_xlabel("Minutes")
    axes[1, 0].set_yscale("log")
    cumulative = trades["pnl"].cumsum()
    axes[1, 1].plot(trades["close_time"], cumulative, color=green, linewidth=1.5)
    axes[1, 1].set_title("Closed-trade cumulative P&L")
    axes[1, 1].set_ylabel("Observed P&L units")
    axes[1, 1].xaxis.set_major_locator(mdates.AutoDateLocator())
    axes[1, 1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(axes[1, 1].xaxis.get_major_locator()))
    fig.savefig(figures_dir / "overview.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(3, 1, figsize=(12, 10), constrained_layout=True)
    axes[0].bar(tables["hourly"]["hour"], tables["hourly"]["trades"], color=blue)
    axes[0].set_title("Entries by raw-clock hour")
    axes[0].set_xticks(range(24))
    axes[0].set_ylabel("Trades")
    weekday = tables["weekday"]
    axes[1].bar(weekday["weekday"].astype(str), weekday["trades"], color=orange)
    axes[1].set_title("Entries by raw weekday")
    axes[1].tick_params(axis="x", rotation=30)
    monthly = tables["monthly"]
    axes[2].bar(monthly["month"], monthly["trades"], color=green)
    axes[2].set_title("Entries by month")
    axes[2].tick_params(axis="x", rotation=45)
    axes[2].set_ylabel("Trades")
    fig.text(0.5, 0.005, "Timestamps have no timezone; these are export-clock distributions.", ha="center", fontsize=9)
    fig.savefig(figures_dir / "temporal_patterns.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6), constrained_layout=True)
    for side, color in [("Buy", blue), ("Sell", orange)]:
        subset = trades[trades["side"] == side]
        ax.scatter(subset["duration_minutes"], subset["pnl"], alpha=0.65, s=20 + subset["lot_size"] * 1000, label=side, color=color)
    ax.axhline(0, color=red, linewidth=1)
    ax.set_xscale("log")
    ax.set_title("P&L versus holding time")
    ax.set_xlabel("Holding time (minutes, log scale)")
    ax.set_ylabel("Observed P&L units")
    ax.legend()
    fig.savefig(figures_dir / "pnl_vs_duration.png", dpi=180)
    plt.close(fig)

    direction_counts = pd.crosstab(trades["side"].shift(1), trades["side"]).reindex(
        index=["Buy", "Sell"], columns=["Buy", "Sell"], fill_value=0
    )
    fig, ax = plt.subplots(figsize=(6, 5), constrained_layout=True)
    image = ax.imshow(direction_counts.to_numpy(), cmap="Blues")
    ax.set_xticks([0, 1], ["Next Buy", "Next Sell"])
    ax.set_yticks([0, 1], ["Current Buy", "Current Sell"])
    ax.set_title("Direction transition counts")
    for i in range(2):
        for j in range(2):
            ax.text(j, i, str(direction_counts.iloc[i, j]), ha="center", va="center", color="black")
    fig.colorbar(image, ax=ax, shrink=0.8)
    fig.savefig(figures_dir / "direction_transitions.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), constrained_layout=True)
    axes[0].step(trades["open_time"], trades["lot_size"], where="mid", color=blue)
    axes[0].set_title("Observed position size over time")
    axes[0].set_ylabel("Size-like units")
    axes[0].xaxis.set_major_formatter(mdates.ConciseDateFormatter(axes[0].xaxis.get_major_locator()))
    rolling = trades.set_index("open_time").rolling("60D").agg({"side_code": "mean", "win": "mean", "pnl": "mean", "duration_minutes": "median"})
    axes[1].plot(rolling.index, rolling["side_code"], label="Buy rate", color=blue)
    axes[1].plot(rolling.index, rolling["win"], label="Win rate", color=green)
    for timestamp in pd.to_datetime(change_table.loc[change_table["fdr_5pct_significant"], "split_open_time"]):
        axes[1].axvline(timestamp, color=red, alpha=0.25)
    axes[1].set_ylim(0, 1)
    axes[1].set_title("Rolling 60-day observed rates")
    axes[1].legend(loc="best")
    axes[1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(axes[1].xaxis.get_major_locator()))
    fig.savefig(figures_dir / "size_and_rolling_behavior.png", dpi=180)
    plt.close(fig)

    gaps = trades["gap_from_previous_close_minutes"].dropna()
    gaps = gaps[gaps >= 0]
    fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
    ax.hist(np.log1p(gaps), bins=45, color=blue, edgecolor="white")
    ax.set_title("Gap from previous close to next entry")
    ax.set_xlabel("log(1 + gap minutes)")
    ax.set_ylabel("Count")
    fig.savefig(figures_dir / "reentry_gaps.png", dpi=180)
    plt.close(fig)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def run_pipeline(input_path: Path, output_root: Path, market_data_path: Path | None = None) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    tables_dir = output_root / "tables"
    figures_dir = output_root / "figures"
    tables_dir.mkdir(exist_ok=True)
    figures_dir.mkdir(exist_ok=True)

    trades, quality = load_trades(input_path)
    summary = dataset_summary(trades, quality)
    direction, transition_table, direction_tests = direction_analysis(trades)
    profit, profit_tests = profit_analysis(trades)
    duration, duration_tests, duration_fits = duration_analysis(trades)
    temporal, temporal_tables, temporal_tests = temporal_analysis(trades)
    sizing, sizing_tests, size_table = sizing_analysis(trades)
    clustering, clustering_tests, overlaps = clustering_analysis(trades)
    latent_models, gmm_table, cluster_profiles, hmm_table = latent_model_analysis(trades)
    change_points, change_table, change_tests = change_point_analysis(trades)
    holding_regimes, holding_scan_table, holding_phase_table = holding_regime_analysis(trades)
    anomalies = anomaly_analysis(trades)
    walk_forward, walk_forward_table = walk_forward_behavior(trades)
    all_tests = apply_multiple_testing(
        direction_tests + profit_tests + duration_tests + temporal_tests + sizing_tests + clustering_tests + change_tests
    )

    market = {
        "status": "not_run",
        "reason": "No synchronized broker-specific market-data file was supplied.",
        "required_schema": ["timestamp", "open", "high", "low", "close", "volume (optional)"],
    }
    market_data_used = False
    if market_data_path is not None:
        bars = add_market_features(load_market_bars(market_data_path))
        aligned = align_entries(trades, bars)
        excursions = calculate_excursions(trades, bars)
        aligned.to_csv(tables_dir / "trade_market_features.csv", index=False)
        excursions.to_csv(tables_dir / "mfe_mae_price_units.csv", index=False)
        match_rate = float(aligned["timestamp"].notna().mean())
        market = {
            "status": "completed_feature_alignment",
            "source_path": str(market_data_path),
            "matched_trade_share": match_rate,
            "warning": "Feed identity, timezone and contract comparability still require independent verification.",
        }
        market_data_used = True

    metrics = {
        "analysis_version": "0.1.0",
        "random_seed": SEED,
        "input": {"path": str(input_path), "sha256": quality["sha256"]},
        "data_quality": quality,
        "summary": summary,
        "direction": direction,
        "profit": profit,
        "duration": duration,
        "temporal": temporal,
        "sizing": sizing,
        "clustering": clustering,
        "latent_models": latent_models,
        "change_points": change_points,
        "holding_regimes": holding_regimes,
        "walk_forward_behavior": walk_forward,
        "market_data": market,
        "identification_ceiling": "Level 1 behavioral fingerprint; cautious trade-derived subgroup evidence only. Entry/exit rule reconstruction is not identified.",
    }
    tracking = make_tracking_tables(metrics, all_tests)

    trades.to_csv(output_root.parent.parent / "data" / "processed" / "trades_enriched.csv", index=False)
    transition_table.to_csv(tables_dir / "direction_transition_matrix.csv")
    duration_fits.to_csv(tables_dir / "duration_distribution_fits.csv", index=False)
    size_table.to_csv(tables_dir / "position_size_summary.csv", index=False)
    overlaps.to_csv(tables_dir / "overlapping_entries.csv", index=False)
    gmm_table.to_csv(tables_dir / "gmm_model_comparison.csv", index=False)
    cluster_profiles.to_csv(tables_dir / "gmm_component_profiles.csv", index=False)
    hmm_table.to_csv(tables_dir / "hmm_model_comparison.csv", index=False)
    change_table.to_csv(tables_dir / "change_point_tests.csv", index=False)
    holding_scan_table.to_csv(tables_dir / "holding_time_recursive_scans.csv", index=False)
    holding_phase_table.to_csv(tables_dir / "holding_time_phases.csv", index=False)
    anomalies.to_csv(tables_dir / "anomaly_review.csv", index=False)
    walk_forward_table.to_csv(tables_dir / "walk_forward_behavior.csv", index=False)
    all_tests.to_csv(tables_dir / "statistical_tests.csv", index=False)
    field_dictionary().to_csv(tables_dir / "field_dictionary.csv", index=False)
    specification_coverage(market_data_used).to_csv(tables_dir / "specification_coverage.csv", index=False)
    for name, table in temporal_tables.items():
        table.to_csv(tables_dir / f"temporal_{name}.csv", index=False)
    for name, table in tracking.items():
        table.to_csv(tables_dir / f"{name}.csv", index=False)

    save_plots(trades, temporal_tables, figures_dir, change_table)
    with (output_root / "analysis_metrics.json").open("w", encoding="utf-8") as handle:
        json.dump(_json_safe(metrics), handle, indent=2, ensure_ascii=False)
    return metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Headerless 8-field trade TSV")
    parser.add_argument("--output", type=Path, required=True, help="Output directory")
    parser.add_argument("--market-data", type=Path, default=None, help="Optional synchronized OHLC CSV")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    metrics = run_pipeline(args.input.resolve(), args.output.resolve(), args.market_data.resolve() if args.market_data else None)
    print(json.dumps({"status": "ok", "observations": metrics["summary"]["observations"], "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
