"""Registered symbolic grammar and nested chronological memoryless search (P-Q)."""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .io import write_json
from .stage_o import _prepare


SEARCH_FEATURES = ["hour_utc", "day_of_week", "ret_5s", "ret_30s", "range_30s", "realized_vol_30s", "spread_now", "tick_rate_30s"]


def stage_p(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    grammar = {
        "tiers": {
            "P0": "single strict threshold feature > c or feature < c",
            "P1": "conjunction of two P0 predicates selected inside training only",
            "P2": "registered UTC time windows",
        },
        "features": SEARCH_FEATURES,
        "thresholds_per_feature": 11,
        "operators": [">", "<"],
        "max_conjunction_children": 2,
        "complexity_bits": {"threshold": 64, "conjunction": 144, "time_window": 72},
        "excluded_at_this_stage": {
            "crossing_and_persistence": "sampled controls do not preserve every immediately preceding quote",
            "candidate_state": "requires autonomous full-stream replay in R/U",
            "direction_size_exit": "handled in S/T after entry mechanism cohort",
        },
        "selection": "initial 160-epoch training prefix, two inner expanding folds; outer folds untouched",
        "unknown": "excluded from supported domain, never relabelled as no-action",
    }
    write_json(output / "program_grammar.json", grammar)
    summary = {"status": "passed", "tiers": 3, "features": len(SEARCH_FEATURES)}
    write_json(output / "stage_status.json", summary)
    return summary


def _mask(frame: pd.DataFrame, rule: dict[str, Any]) -> np.ndarray:
    if rule["type"] == "threshold":
        values = frame[rule["feature"]].to_numpy(float)
        return values > rule["threshold"] if rule["operator"] == ">" else values < rule["threshold"]
    if rule["type"] == "and":
        return _mask(frame, rule["children"][0]) & _mask(frame, rule["children"][1])
    if rule["type"] == "time_window":
        hour = frame.hour_utc.to_numpy(float)
        dow = frame.day_of_week.to_numpy(int)
        return (hour >= rule["start_hour"]) & (hour < rule["end_hour"]) & np.isin(dow, rule["days_of_week"])
    raise ValueError(f"Unknown rule: {rule}")


def _probabilities(train: pd.DataFrame, train_mask: np.ndarray, test_mask: np.ndarray) -> np.ndarray:
    y = train.is_trade_entry.to_numpy(float)
    w = train.population_weight.to_numpy(float)
    probabilities = []
    for region in (False, True):
        selected = train_mask == region
        events = float(np.sum(w[selected] * y[selected]))
        exposure = float(np.sum(w[selected]))
        probabilities.append((events + 0.5) / (exposure + 1.0) if exposure else 1e-15)
    return np.where(test_mask, probabilities[1], probabilities[0])


def _ll(test: pd.DataFrame, probability: np.ndarray) -> float:
    y = test.is_trade_entry.to_numpy(float)
    w = test.population_weight.to_numpy(float)
    p = np.clip(probability, 1e-15, 1 - 1e-15)
    return float(np.sum(w * (y * np.log(p) + (1 - y) * np.log(1 - p))))


def _bits(rule: dict[str, Any]) -> int:
    return 144 if rule["type"] == "and" else 72 if rule["type"] == "time_window" else 64


def _inner_boundaries(initial: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    cases = initial.loc[initial.is_trade_entry.eq(1), "decision_time_utc"].sort_values().drop_duplicates().tolist()
    if len(cases) < 60:
        raise ValueError("Initial training prefix has too few supported cases for inner search")
    first, second = len(cases) // 2, (3 * len(cases)) // 4
    return [
        (cases[first - 1], cases[first], cases[second - 1]),
        (cases[second - 1], cases[second], cases[-1]),
    ]


def _score_inner(frame: pd.DataFrame, boundaries: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]], rule: dict[str, Any]) -> tuple[float, float]:
    fold_bits = []
    for train_end, test_start, test_end in boundaries:
        train = frame.loc[frame.decision_time_utc <= train_end]
        test = frame.loc[frame.decision_time_utc.between(test_start, test_end, inclusive="both")]
        train_mask = _mask(train, rule)
        test_mask = _mask(test, rule)
        probability = _probabilities(train, train_mask, test_mask)
        candidate_ll = _ll(test, probability)
        base = _probabilities(train, np.zeros(len(train), dtype=bool), np.zeros(len(test), dtype=bool))
        baseline_ll = _ll(test, base)
        events = int(test.is_trade_entry.sum())
        fold_bits.append((candidate_ll - baseline_ll) / (events * np.log(2.0)))
    mean = float(np.mean(fold_bits))
    objective = mean - _bits(rule) / max(1, int(frame.is_trade_entry.sum()))
    return mean, objective


def _threshold_rules(initial: pd.DataFrame) -> list[dict[str, Any]]:
    rules = []
    for feature in SEARCH_FEATURES:
        values = initial[feature].to_numpy(float)
        thresholds = np.unique(np.quantile(values, np.linspace(0.05, 0.95, 11)))
        for threshold in thresholds:
            for operator in (">", "<"):
                rules.append({"type": "threshold", "feature": feature, "operator": operator, "threshold": float(threshold)})
    for start, end in ((0, 8), (8, 13), (13, 17), (17, 22), (22, 24), (8, 17), (13, 22)):
        rules.append({"type": "time_window", "start_hour": start, "end_hour": end, "days_of_week": [0, 1, 2, 3, 4]})
    return rules


def run_stage_q(risk_set_path: Path, splits_path: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    frame, audit = _prepare(risk_set_path)
    splits = json.loads(splits_path.read_text(encoding="utf-8"))
    initial_end = pd.Timestamp(splits[0]["train_end"])
    initial = frame.loc[frame.decision_time_utc <= initial_end].copy()
    boundaries = _inner_boundaries(initial)
    singles = _threshold_rules(initial)
    single_scores = []
    for rule in singles:
        mean, objective = _score_inner(initial, boundaries, rule)
        single_scores.append({"rule": rule, "inner_bits_per_event": mean, "mdl_adjusted_score": objective})
    ranked_singles = sorted(single_scores, key=lambda row: row["mdl_adjusted_score"], reverse=True)
    seeds = [row["rule"] for row in ranked_singles[:12]]
    conjunctions = [{"type": "and", "children": [left, right]} for left, right in combinations(seeds, 2)]
    conjunction_scores = []
    for rule in conjunctions:
        mean, objective = _score_inner(initial, boundaries, rule)
        conjunction_scores.append({"rule": rule, "inner_bits_per_event": mean, "mdl_adjusted_score": objective})
    ranked = sorted(single_scores + conjunction_scores, key=lambda row: row["mdl_adjusted_score"], reverse=True)
    cohort = ranked[:20]
    registry_rows = []
    for index, item in enumerate(cohort):
        registry_rows.append({
            "candidate_id": f"Q-{index:03d}", "rule_json": json.dumps(item["rule"], sort_keys=True),
            "inner_bits_per_event": item["inner_bits_per_event"], "mdl_adjusted_score": item["mdl_adjusted_score"],
            "complexity_bits": _bits(item["rule"]),
        })
    pd.DataFrame(registry_rows).to_csv(output / "candidate_registry.csv", index=False)
    outer_rows = []
    for fold in splits:
        train_end, test_start, test_end = pd.Timestamp(fold["train_end"]), pd.Timestamp(fold["test_start"]), pd.Timestamp(fold["test_end"])
        train = frame.loc[frame.decision_time_utc <= train_end]
        test = frame.loc[frame.decision_time_utc.between(test_start, test_end, inclusive="both")]
        for index, item in enumerate(cohort):
            rule = item["rule"]
            probability = _probabilities(train, _mask(train, rule), _mask(test, rule))
            candidate_ll = _ll(test, probability)
            base = _probabilities(train, np.zeros(len(train), bool), np.zeros(len(test), bool))
            baseline_ll = _ll(test, base)
            events = int(test.is_trade_entry.sum())
            outer_rows.append({
                "fold_id": fold["fold_id"], "candidate_id": f"Q-{index:03d}", "test_events": events,
                "test_bits_per_event_vs_B0": (candidate_ll - baseline_ll) / (events * np.log(2.0)),
            })
    outer = pd.DataFrame(outer_rows)
    outer["test_information_gain_bits"] = outer.test_bits_per_event_vs_B0 * outer.test_events
    outer.to_csv(output / "outer_fold_scores.csv", index=False)
    aggregate = outer.groupby("candidate_id", as_index=False).agg(
        mean_outer_bits_per_event=("test_bits_per_event_vs_B0", "mean"),
        minimum_outer_bits_per_event=("test_bits_per_event_vs_B0", "min"),
        positive_outer_folds=("test_bits_per_event_vs_B0", lambda values: int((values > 0).sum())),
        total_outer_information_gain_bits=("test_information_gain_bits", "sum"),
    ).sort_values("mean_outer_bits_per_event", ascending=False)
    complexity = pd.DataFrame(registry_rows)[["candidate_id", "complexity_bits"]]
    aggregate = aggregate.merge(complexity, on="candidate_id", how="left")
    aggregate["outer_mdl_net_bits"] = aggregate.total_outer_information_gain_bits - aggregate.complexity_bits
    aggregate = aggregate.sort_values("mean_outer_bits_per_event", ascending=False)
    aggregate.to_csv(output / "aggregate_candidate_scores.csv", index=False)
    best = aggregate.iloc[0]
    summary = {
        "status": "passed_search_completed",
        "supported_cases": int(frame.is_trade_entry.sum()), "supported_controls": int(frame.is_trade_entry.eq(0).sum()),
        "single_rules_scored": len(singles), "guided_conjunctions_scored": len(conjunctions), "fixed_outer_cohort": len(cohort),
        "best_candidate_id": str(best.candidate_id),
        "best_mean_outer_bits_per_event_vs_B0": float(best.mean_outer_bits_per_event),
        "best_minimum_outer_bits_per_event_vs_B0": float(best.minimum_outer_bits_per_event),
        "best_positive_outer_folds": int(best.positive_outer_folds),
        "best_total_outer_information_gain_bits": float(best.total_outer_information_gain_bits),
        "best_complexity_bits": int(best.complexity_bits),
        "best_outer_mdl_net_bits": float(best.outer_mdl_net_bits),
        "any_candidate_outer_mdl_positive": bool(aggregate.outer_mdl_net_bits.gt(0).any()),
        "candidate_selection_used_outer_test": False,
        "search_claim": "diagnostic memoryless quote-clock preference only; not autonomous strategy recovery",
        **audit,
    }
    write_json(output / "stage_status.json", summary)
    return summary
