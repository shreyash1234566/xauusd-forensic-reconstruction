"""Stage R: bounded interaction and stateful search on a minute trajectory.

This stage is deliberately separate from the quote-sampled Stage Q model.  It
collapses the independently sampled public quote clock to one causal row per
observed provider minute, so lagged predicates have an ordered trajectory.
Gaps reset history; they are never silently treated as continuous exposure.
"""

from __future__ import annotations

import json
import math
from itertools import combinations, product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .io import write_json
from .stage_pq import SEARCH_FEATURES


def build_minute_trajectory(risk_set_path: Path) -> pd.DataFrame:
    raw = pd.read_csv(risk_set_path, low_memory=False)
    raw["decision_time_utc"] = pd.to_datetime(raw["decision_time_utc"], utc=True, format="mixed")
    raw["source_quote_time_utc"] = pd.to_datetime(raw["source_quote_time_utc"], utc=True, format="mixed")
    raw = raw.loc[raw.feature_status.eq("observed")].copy()
    raw["minute_utc"] = raw.source_quote_time_utc.dt.floor("min")
    raw["is_case"] = raw.row_role.eq("case").astype(int)

    # A control exists by construction for each observed provider minute.  Use
    # its feature row where available, then attach the independently observed
    # case count.  This avoids duplicating exposure when a case shares a minute.
    controls = raw.loc[raw.row_role.eq("control"), ["minute_utc", *SEARCH_FEATURES]].copy()
    controls = controls.sort_values("minute_utc", kind="mergesort").drop_duplicates("minute_utc")
    cases = raw.loc[raw.row_role.eq("case")].groupby("minute_utc").size().rename("case_count")
    panel = controls.set_index("minute_utc").join(cases, how="outer")
    missing = panel[SEARCH_FEATURES].isna().all(axis=1)
    if missing.any():
        fallback = (
            raw.loc[raw.row_role.eq("case"), ["minute_utc", *SEARCH_FEATURES]]
            .sort_values("minute_utc", kind="mergesort").drop_duplicates("minute_utc")
            .set_index("minute_utc")
        )
        panel.loc[missing, SEARCH_FEATURES] = fallback.reindex(panel.index).loc[missing, SEARCH_FEATURES]
    panel["case_count"] = panel.case_count.fillna(0).astype(int)
    panel["is_trade_entry"] = panel.case_count.gt(0).astype(int)
    panel = panel.reset_index().sort_values("minute_utc", kind="mergesort").reset_index(drop=True)
    panel["adjacent_previous_minute"] = panel.minute_utc.diff().le(pd.Timedelta(minutes=1)).fillna(False)
    return panel


def _predicate_mask(frame: pd.DataFrame, predicate: dict[str, Any]) -> np.ndarray:
    values = frame[predicate["feature"]].to_numpy(float)
    return values > predicate["threshold"] if predicate["operator"] == ">" else values < predicate["threshold"]


def _mask(frame: pd.DataFrame, rule: dict[str, Any]) -> np.ndarray:
    kind = rule["type"]
    if kind == "threshold":
        return _predicate_mask(frame, rule)
    if kind == "and":
        return _predicate_mask(frame, rule["left"]) & _predicate_mask(frame, rule["right"])
    base = _predicate_mask(frame, rule["predicate"])
    adjacent = frame.adjacent_previous_minute.to_numpy(bool)
    if kind == "crossing":
        previous = np.r_[False, base[:-1]]
        return base & ~previous & adjacent
    if kind == "persistence":
        periods = int(rule["periods"])
        result = base.copy()
        for lag in range(1, periods):
            result &= np.r_[np.zeros(lag, dtype=bool), base[:-lag]]
            for step in range(lag):
                result &= np.r_[np.zeros(step, dtype=bool), adjacent[: len(adjacent) - step]]
        return result
    if kind == "armed":
        signal = base
        reset = _predicate_mask(frame, rule["reset"])
        cooldown = int(rule["cooldown_minutes"])
        result = np.zeros(len(frame), dtype=bool)
        armed = False
        blocked_until = -1
        for index in range(len(frame)):
            if index and not adjacent[index]:
                armed = False
            if reset[index]:
                armed = True
            if armed and signal[index] and index >= blocked_until:
                result[index] = True
                armed = False
                blocked_until = index + cooldown + 1
        return result
    raise ValueError(f"Unknown Stage R rule: {kind}")


def _fit_region_rates(train_y: np.ndarray, train_mask: np.ndarray, test_mask: np.ndarray) -> np.ndarray:
    rates: list[float] = []
    for region in (False, True):
        selected = train_mask == region
        events = int(train_y[selected].sum())
        exposure = int(selected.sum())
        rates.append((events + 0.5) / (exposure + 1.0) if exposure else 1e-15)
    return np.where(test_mask, rates[1], rates[0])


def _log_likelihood(y: np.ndarray, probability: np.ndarray) -> float:
    p = np.clip(probability, 1e-15, 1 - 1e-15)
    return float(np.sum(y * np.log(p) + (1 - y) * np.log1p(-p)))


def _score(train: pd.DataFrame, test: pd.DataFrame, rule: dict[str, Any]) -> float:
    train_y = train.is_trade_entry.to_numpy(int)
    test_y = test.is_trade_entry.to_numpy(int)
    candidate = _fit_region_rates(train_y, _mask(train, rule), _mask(test, rule))
    baseline = np.full(len(test), (train_y.sum() + 0.5) / (len(train_y) + 1.0))
    events = max(1, int(test_y.sum()))
    return (_log_likelihood(test_y, candidate) - _log_likelihood(test_y, baseline)) / (events * math.log(2.0))


def _predicates(initial: pd.DataFrame) -> list[dict[str, Any]]:
    predicates: list[dict[str, Any]] = []
    for feature in SEARCH_FEATURES:
        values = initial[feature].dropna().to_numpy(float)
        if not len(values):
            continue
        for threshold in np.unique(np.quantile(values, [0.25, 0.5, 0.75])):
            for operator in (">", "<"):
                predicates.append({"type": "threshold", "feature": feature, "operator": operator, "threshold": float(threshold)})
    return predicates


def _candidate_rules(initial: pd.DataFrame) -> list[dict[str, Any]]:
    predicates = _predicates(initial)
    median = predicates[2::6] + predicates[3::6]
    # Explicit coverage is more important here than marginal pre-screening:
    # every feature participates in crossing/persistence and median interactions.
    rules: list[dict[str, Any]] = []
    for predicate in predicates:
        rules.append({"type": "crossing", "predicate": predicate})
        for periods in (2, 3):
            rules.append({"type": "persistence", "predicate": predicate, "periods": periods})
    for left, right in combinations(median, 2):
        if left["feature"] != right["feature"]:
            rules.append({"type": "and", "left": left, "right": right})
    for signal, reset, cooldown in product(median, median, (0, 5, 30)):
        if signal["feature"] != reset["feature"]:
            rules.append({"type": "armed", "predicate": signal, "reset": reset, "cooldown_minutes": cooldown})
    return rules


def _complexity_bits(rule: dict[str, Any], family_count: int, observations: int) -> float:
    # A transparent two-part prefix code: family choice + registered candidate
    # index.  It is computed from the actually searched registry, not assigned
    # as a convenient pass/fail constant.
    family_cost = math.log2(4)
    # The candidate has two Bernoulli region rates whereas B0 has one.  BIC's
    # Laplace approximation charges 0.5*log2(n) for that additional fitted
    # continuous parameter.  Omitting it systematically favors partitions.
    parameter_cost = 0.5 * math.log2(max(2, observations))
    return family_cost + math.log2(max(1, family_count)) + parameter_cost


def run_stage_r(risk_set_path: Path, splits_path: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    panel = build_minute_trajectory(risk_set_path)
    panel.to_csv(output / "minute_trajectory_panel.csv", index=False)
    splits = json.loads(splits_path.read_text(encoding="utf-8"))
    initial_end = pd.Timestamp(splits[0]["train_end"])
    initial = panel.loc[panel.minute_utc <= initial_end].copy()
    event_times = initial.loc[initial.is_trade_entry.eq(1), "minute_utc"].tolist()
    if len(event_times) < 8:
        raise ValueError("Too few initial minute-level events for Stage R")
    cut1, cut2 = len(event_times) // 2, (3 * len(event_times)) // 4
    inner = [(event_times[cut1 - 1], event_times[cut1], event_times[cut2 - 1]),
             (event_times[cut2 - 1], event_times[cut2], event_times[-1])]
    rules = _candidate_rules(initial)
    family_counts: dict[str, int] = {}
    for rule in rules:
        family_counts[rule["type"]] = family_counts.get(rule["type"], 0) + 1

    ranked: list[dict[str, Any]] = []
    for rule in rules:
        fold_scores = []
        for train_end, test_start, test_end in inner:
            train = initial.loc[initial.minute_utc <= train_end]
            test = initial.loc[initial.minute_utc.between(test_start, test_end, inclusive="both")]
            fold_scores.append(_score(train, test, rule))
        cost = _complexity_bits(rule, family_counts[rule["type"]], len(initial))
        ranked.append({"rule": rule, "inner_bits_per_event": float(np.mean(fold_scores)), "complexity_bits": cost})

    # Freeze a diverse cohort using only inner data.  Outer results never alter
    # membership or parameters.
    cohort: list[dict[str, Any]] = []
    for family in ("and", "crossing", "persistence", "armed"):
        members = sorted((row for row in ranked if row["rule"]["type"] == family), key=lambda row: row["inner_bits_per_event"], reverse=True)
        cohort.extend(members[:5])
    registry = []
    for index, item in enumerate(cohort):
        registry.append({"candidate_id": f"R-{index:03d}", "family": item["rule"]["type"],
                         "rule_json": json.dumps(item["rule"], sort_keys=True),
                         "inner_bits_per_event": item["inner_bits_per_event"],
                         "complexity_bits": item["complexity_bits"]})
    pd.DataFrame(registry).to_csv(output / "candidate_registry.csv", index=False)

    outer_rows: list[dict[str, Any]] = []
    for fold in splits:
        train_end, test_start, test_end = map(pd.Timestamp, (fold["train_end"], fold["test_start"], fold["test_end"]))
        train = panel.loc[panel.minute_utc <= train_end]
        test = panel.loc[panel.minute_utc.between(test_start, test_end, inclusive="both")]
        for index, item in enumerate(cohort):
            score = _score(train, test, item["rule"])
            events = int(test.is_trade_entry.sum())
            outer_rows.append({"fold_id": fold["fold_id"], "candidate_id": f"R-{index:03d}",
                               "test_events": events, "test_bits_per_event_vs_B0": score,
                               "test_information_gain_bits": score * events})
    outer = pd.DataFrame(outer_rows)
    outer.to_csv(output / "outer_fold_scores.csv", index=False)
    aggregate = outer.groupby("candidate_id", as_index=False).agg(
        mean_outer_bits_per_event=("test_bits_per_event_vs_B0", "mean"),
        minimum_outer_bits_per_event=("test_bits_per_event_vs_B0", "min"),
        positive_outer_folds=("test_bits_per_event_vs_B0", lambda value: int((value > 0).sum())),
        total_outer_information_gain_bits=("test_information_gain_bits", "sum"),
    ).merge(pd.DataFrame(registry)[["candidate_id", "family", "complexity_bits"]], on="candidate_id")
    aggregate["outer_mdl_net_bits"] = aggregate.total_outer_information_gain_bits - aggregate.complexity_bits
    aggregate = aggregate.sort_values(["outer_mdl_net_bits", "mean_outer_bits_per_event"], ascending=False)
    aggregate.to_csv(output / "aggregate_candidate_scores.csv", index=False)
    best = aggregate.iloc[0]
    accepted = aggregate.loc[(aggregate.outer_mdl_net_bits > 0) & (aggregate.positive_outer_folds == len(splits))]
    summary = {
        "stage": "R_stateful_mechanisms", "status": "passed_bounded_search_complete",
        "minute_rows": len(panel), "minute_event_rows": int(panel.is_trade_entry.sum()),
        "registered_candidates": len(rules), "frozen_outer_cohort": len(cohort),
        "families_searched": family_counts, "best_candidate_id": str(best.candidate_id),
        "best_family": str(best.family), "best_mean_outer_bits_per_event": float(best.mean_outer_bits_per_event),
        "best_outer_mdl_net_bits": float(best.outer_mdl_net_bits),
        "accepted_candidate_ids": accepted.candidate_id.tolist(),
        "any_candidate_accepted": bool(len(accepted)),
        "candidate_selection_used_outer_test": False,
        "scope": "bounded minute-clock interaction/state search; not a universal algorithm search or account-uptime model",
        "gaps_reset_state": True, "canonical_artifacts_modified": False,
    }
    write_json(output / "stage_status.json", summary)
    return summary
