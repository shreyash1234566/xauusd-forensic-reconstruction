"""Bounded symbolic diagnostics using only Phase 13 survivor features.

The Phase 10/11 lockbox was already consumed to choose the survivor features.
Consequently its scores here are retrospective diagnostics and can never be
labelled a second confirmatory test.
"""

from __future__ import annotations

import json
import math
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

from phase13_clock_offset_analysis import (
    OUT, DISCOVERY, LOCKBOX, ROOT, clock_design, conditional_log_likelihood,
    fit_single_feature,
)


def _offset(frame: pd.DataFrame, freeze: dict) -> np.ndarray:
    X, names = clock_design(frame.hour, frame.minute, frame.dow)
    coefficients = np.asarray([freeze["coefficients"][name] for name in names])
    return float(freeze["intercept"]) + X @ coefficients


def _predicate(frame: pd.DataFrame, predicate: dict) -> np.ndarray:
    values = frame[predicate["feature"]].to_numpy(float)
    return values > predicate["threshold"] if predicate["operator"] == ">" else values < predicate["threshold"]


def _rule_mask(frame: pd.DataFrame, rule: dict) -> np.ndarray:
    if rule["type"] == "threshold":
        return _predicate(frame, rule)
    return _predicate(frame, rule["left"]) & _predicate(frame, rule["right"])


def _delta(frame: pd.DataFrame, offset: np.ndarray, beta: float, indicator: np.ndarray) -> float:
    candidate, _ = conditional_log_likelihood(frame, offset, beta, indicator.astype(float))
    baseline, _ = conditional_log_likelihood(frame, offset, 0.0, indicator.astype(float))
    return candidate - baseline


def _fast_structure(frame: pd.DataFrame, offset: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    groups = frame.group.to_numpy()
    if np.any(groups[1:] < groups[:-1]):
        raise ValueError("Symbolic frames must be ordered by group")
    starts = np.r_[0, np.flatnonzero(groups[1:] != groups[:-1]) + 1]
    counts = np.diff(np.r_[starts, len(frame)])
    y = frame.y.to_numpy(int)
    if not np.all(np.add.reduceat(y, starts) == 1):
        raise ValueError("Every symbolic stratum must contain one case")
    return y, starts, counts, offset


def _fast_ll(structure: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray], beta: float, indicator: np.ndarray) -> float:
    y, starts, counts, offset = structure
    eta = offset + beta * indicator.astype(float)
    maxima = np.maximum.reduceat(eta, starts)
    centered = eta - np.repeat(maxima, counts)
    denominators = maxima + np.log(np.add.reduceat(np.exp(centered), starts))
    return float(eta[y == 1].sum() - denominators.sum())


def _fast_fit(structure: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray], indicator: np.ndarray) -> float:
    result = minimize_scalar(lambda beta: -_fast_ll(structure, float(beta), indicator), bounds=(-8.0, 8.0), method="bounded")
    if not result.success:
        raise RuntimeError(result.message)
    return float(result.x)


def run() -> dict:
    gate = json.loads((OUT / "symbolic_search_gate.json").read_text(encoding="utf-8"))
    survivors = gate["eligible_market_features"]
    if not survivors:
        summary = {"status": "blocked", "reason": "No individual market feature cleared Phase 13"}
        (OUT / "symbolic_search_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    freeze = json.loads((OUT / "clock_intensity_freeze.json").read_text(encoding="utf-8"))
    dev = pd.read_parquet(DISCOVERY, columns=[*survivors, "utc_hour", "utc_minute", "day_of_week", "y", "groups"])
    dev = dev.rename(columns={"groups": "group", "utc_hour": "hour", "utc_minute": "minute", "day_of_week": "dow"})
    dev_case_hours = dev.loc[dev.y.eq(1)].set_index("group").hour
    dev = dev.loc[dev.group.isin(dev_case_hours.loc[dev_case_hours.between(5, 16)].index)].copy()
    raw_columns = [f"feat_raw_{feature}" for feature in survivors]
    lock = pd.read_parquet(LOCKBOX, columns=["epoch_id", "is_case", "timestamp_utc", *raw_columns])
    lock["timestamp_utc"] = pd.to_datetime(lock.timestamp_utc, utc=True, format="mixed")
    lock["hour"] = lock.timestamp_utc.dt.hour
    lock["minute"] = lock.timestamp_utc.dt.minute
    lock["dow"] = lock.timestamp_utc.dt.dayofweek
    lock["group"] = lock.epoch_id
    lock["y"] = lock.is_case.astype(int)
    lock = lock.rename(columns={f"feat_raw_{feature}": feature for feature in survivors})
    lock_case_hours = lock.loc[lock.y.eq(1)].set_index("group").hour
    lock = lock.loc[lock.group.isin(lock_case_hours.loc[lock_case_hours.between(5, 16)].index)].copy()
    dev_offset, lock_offset = _offset(dev, freeze), _offset(lock, freeze)

    groups = np.sort(dev.group.unique())
    split = groups[int(len(groups) * 0.70)]
    train = dev.loc[dev.group < split].copy()
    validation = dev.loc[dev.group >= split].copy()
    train_offset = dev_offset[dev.group.to_numpy() < split]
    validation_offset = dev_offset[dev.group.to_numpy() >= split]
    train_structure = _fast_structure(train, train_offset)
    validation_structure = _fast_structure(validation, validation_offset)
    dev_structure = _fast_structure(dev, dev_offset)
    lock_structure = _fast_structure(lock, lock_offset)

    predicates = []
    for feature in survivors:
        for threshold in np.unique(np.quantile(train[feature], np.linspace(0.1, 0.9, 9))):
            for operator in (">", "<"):
                predicates.append({"type": "threshold", "feature": feature, "operator": operator, "threshold": float(threshold)})
    rules = list(predicates)
    by_feature = {feature: [p for p in predicates if p["feature"] == feature] for feature in survivors}
    if len(survivors) >= 2:
        for left, right in product(by_feature[survivors[0]], by_feature[survivors[1]]):
            rules.append({"type": "and", "left": left, "right": right})

    registry_cost = math.log2(max(1, len(rules)))
    parameter_cost = 0.5 * math.log2(max(2, len(train)))
    scored = []
    for index, rule in enumerate(rules):
        train_mask = _rule_mask(train, rule)
        beta = _fast_fit(train_structure, train_mask)
        validation_mask = _rule_mask(validation, rule)
        validation_gain = _fast_ll(validation_structure, beta, validation_mask) - _fast_ll(validation_structure, 0.0, validation_mask)
        n_events = int(validation.y.sum())
        scored.append({
            "candidate_id": f"P13-{index:04d}", "rule": rule, "inner_beta": beta,
            "validation_information_bits": validation_gain / math.log(2.0),
            "validation_bits_per_event": validation_gain / (max(1, n_events) * math.log(2.0)),
            "description_length_bits": registry_cost + parameter_cost,
        })
    cohort = sorted(scored, key=lambda row: row["validation_bits_per_event"], reverse=True)[:20]
    rows = []
    for item in cohort:
        rule = item["rule"]
        full_mask = _rule_mask(dev, rule)
        beta = _fast_fit(dev_structure, full_mask)
        lock_mask = _rule_mask(lock, rule)
        lock_gain = _fast_ll(lock_structure, beta, lock_mask) - _fast_ll(lock_structure, 0.0, lock_mask)
        rows.append({
            "candidate_id": item["candidate_id"], "rule_json": json.dumps(rule, sort_keys=True),
            "frozen_beta": beta, "inner_validation_bits_per_event": item["validation_bits_per_event"],
            "lockbox_reuse_bits_per_event_vs_clock": lock_gain / (lock.group.nunique() * math.log(2.0)),
            "description_length_bits": item["description_length_bits"],
            "lockbox_reuse_net_mdl_bits": lock_gain / math.log(2.0) - item["description_length_bits"],
            "confirmatory_acceptance_permitted": False,
        })
    result = pd.DataFrame(rows).sort_values("lockbox_reuse_bits_per_event_vs_clock", ascending=False)
    result.to_csv(OUT / "symbolic_survivor_candidates.csv", index=False)
    best = result.iloc[0].to_dict()
    audit = {
        "phase12_exact_match_resolution_seconds": 0,
        "phase12_complete_ledger_f1": 0.1047,
        "phase12_complete_ledger_recall": 0.1190,
        "phase12_complete_ledger_precision": 0.0935,
        "assessment": "Phase 12 used exact timestamp identity, stricter than an execution-noise tolerance. Its failure cannot be attributed to an overly generous matching tolerance. Phase 13 does not reuse its 13-feature M3 rule.",
    }
    (OUT / "phase12_matching_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    summary = {
        "status": "retrospective_symbolic_diagnostics_complete",
        "features_used": survivors,
        "candidate_count": len(rules), "frozen_cohort_count": len(cohort),
        "best_candidate": best,
        "confirmatory_policy_identified": False,
        "reason": "The same lockbox selected the survivor features; reuse cannot provide an independent acceptance test.",
        "direction_constraint": gate["direction_constraint"],
    }
    (OUT / "symbolic_search_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
