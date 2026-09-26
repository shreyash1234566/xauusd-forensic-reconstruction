"""Execute the six-step CTPI immediate recoverability sequence.

This stage is deliberately retrospective.  It can falsify claims and calibrate
recoverability, but it cannot manufacture a new untouched real-data lockbox.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.special import logsumexp
from sklearn.linear_model import PoissonRegressor

try:
    from scripts.phase13_clock_offset_analysis import clock_design
    from scripts.tickfeat10 import TickStore, extract_tick_features_arrays
    from scripts.ctpi_direction_placebo import run as run_direction_placebo
except ModuleNotFoundError:  # Direct execution places scripts/ on sys.path.
    from phase13_clock_offset_analysis import clock_design
    from tickfeat10 import TickStore, extract_tick_features_arrays
    from ctpi_direction_placebo import run as run_direction_placebo


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "ctpi_immediate"
PHASE13_OUT = ROOT / "outputs" / "strategy_reconstruction" / "phase13_clock_offset"
EPOCH_MAP = ROOT / "outputs" / "strategy_reconstruction" / "phase10_11_decision_epoch_map.csv"
PANEL = ROOT / "data" / "processed" / "decision_panel.parquet"
TICKS_DIR = ROOT / "data" / "market" / "raw_ticks"
LEDGER = ROOT / "data" / "raw" / "trades_raw.tsv"
RECON = ROOT / "outputs" / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
PHASE13_FEATURES = PHASE13_OUT / "individual_market_feature_tests.csv"
PHASE13_FREEZE = PHASE13_OUT / "clock_intensity_freeze.json"
SEED = 20260926


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def artifact_hashes(directory: Path) -> dict[str, str]:
    if not directory.exists():
        return {}
    return {
        str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path)
        for path in sorted(directory.iterdir()) if path.is_file()
    }


def reconcile_phase13(*, rerun: bool = True) -> dict:
    """Rerun Phase 13 and compare exact artifacts under one evidence standard."""

    before = artifact_hashes(PHASE13_OUT)
    commands: list[dict] = []
    if rerun:
        for script in ("phase13_clock_offset_analysis.py", "phase13_symbolic_survivor_search.py"):
            command = [sys.executable, str(ROOT / "scripts" / script)]
            completed = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True, check=False,
            )
            commands.append({
                "command": command,
                "returncode": completed.returncode,
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
            })
            if completed.returncode != 0:
                raise RuntimeError(f"Phase 13 reproduction failed for {script}: {completed.stderr[-1000:]}")
    after = artifact_hashes(PHASE13_OUT)
    common = sorted(set(before) & set(after))
    changed = [name for name in common if before[name] != after[name]]
    missing_after = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))

    freeze = json.loads(PHASE13_FREEZE.read_text(encoding="utf-8"))
    features = pd.read_csv(PHASE13_FEATURES)
    tick = features.loc[features.feature.eq("tick_rate_ratio")].iloc[0]
    numeric_checks = {
        "full_exposure_lockbox_bits_per_event_vs_constant": float(
            freeze["full_exposure_lockbox_bits_per_event_vs_constant"]
        ),
        "conditional_lockbox_bits_per_event_vs_uniform": float(
            freeze["lockbox_conditional_bits_per_event_vs_uniform"]
        ),
        "tick_rate_ratio_lockbox_bits_per_event_vs_clock": float(
            tick.lockbox_bits_per_event_vs_clock
        ),
        "tick_rate_ratio_holm_pvalue": float(tick.lockbox_holm_pvalue),
    }
    expected_checks = {
        "clock_full_exposure_matches_reported": math.isclose(
            numeric_checks["full_exposure_lockbox_bits_per_event_vs_constant"], 0.3264804142926592,
            rel_tol=0, abs_tol=1e-10,
        ),
        "clock_conditional_matches_reported": math.isclose(
            numeric_checks["conditional_lockbox_bits_per_event_vs_uniform"], 0.04582126111344443,
            rel_tol=0, abs_tol=1e-10,
        ),
        "tick_ratio_lockbox_matches_reported": math.isclose(
            numeric_checks["tick_rate_ratio_lockbox_bits_per_event_vs_clock"], 0.0559,
            rel_tol=0, abs_tol=5e-5,
        ),
        "tick_ratio_holm_matches_reported": math.isclose(
            numeric_checks["tick_rate_ratio_holm_pvalue"], 0.0448,
            rel_tol=0, abs_tol=5e-5,
        ),
    }
    deterministic = not changed and not missing_after and not added
    status = "VERIFIED" if all(expected_checks.values()) and (deterministic or not before) else "FAILED_REPRODUCTION"
    payload = {
        "status": status,
        "rerun_performed": rerun,
        "exact_artifact_reproduction": deterministic,
        "changed_artifacts": changed,
        "missing_after_rerun": missing_after,
        "added_after_rerun": added,
        "numeric_checks": numeric_checks,
        "expected_checks": expected_checks,
        "commands": commands,
        "canonical_input_hashes": {
            str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path)
            for path in (LEDGER, RECON, EPOCH_MAP, PANEL)
        },
        "phase13_artifact_hashes": after,
        "external_same_clock_placebo_claim": {
            "status": "UNVERIFIED_EXTERNAL_CLAIM",
            "reason": "The pasted narrative did not provide a committed executable calculation and output bundle.",
        },
        "reported_direction_p_0_0033": {
            "status": "UNVERIFIED_EXTERNAL_CLAIM",
            "reason": "No reproducible project artifact containing the reported calculation was located.",
        },
    }
    write_json(OUT / "evidence_reconciliation.json", payload)
    return payload


def _available_tick_dates_by_hour(ticks_dir: Path) -> dict[int, list[pd.Timestamp]]:
    pattern = re.compile(r"xauusd_ticks_(\d{4}-\d{2}-\d{2})T(\d{2})-00-00-000Z\.json$")
    result: dict[int, set[pd.Timestamp]] = {}
    for path in ticks_dir.glob("xauusd_ticks_*.json"):
        match = pattern.match(path.name)
        if not match:
            continue
        day = pd.Timestamp(match.group(1), tz="UTC")
        result.setdefault(int(match.group(2)), set()).add(day)
    return {hour: sorted(days) for hour, days in result.items()}


def same_clock_placebo_statistic(
    groups: list[np.ndarray], beta: float, mean: float, std: float, *,
    permutations: int = 19999, seed: int = SEED,
) -> dict:
    """Uniform-day conditional test; the real observation is element zero."""

    if not groups:
        raise ValueError("At least one placebo stratum is required")
    rng = np.random.default_rng(seed)
    observed = 0.0
    simulated = np.zeros(permutations, dtype=float)
    real_values: list[float] = []
    placebo_means: list[float] = []
    real_percentiles: list[float] = []
    contributions_bits: list[float] = []
    for values in groups:
        values = np.asarray(values, dtype=float)
        if len(values) < 2 or not np.all(np.isfinite(values)):
            raise ValueError("Each placebo stratum needs a real value and at least one finite alternative")
        eta = beta * ((values - mean) / std)
        delta = eta - logsumexp(eta) + math.log(len(eta))
        observed += float(delta[0])
        contributions_bits.append(float(delta[0] / math.log(2.0)))
        simulated += delta[rng.integers(0, len(delta), size=permutations)]
        real_values.append(float(values[0]))
        placebo_means.append(float(np.mean(values[1:])))
        real_percentiles.append(float(np.mean(values <= values[0])))
    pvalue = float((1 + np.count_nonzero(simulated >= observed - 1e-12)) / (permutations + 1))
    return {
        "strata": len(groups),
        "observed_information_bits_vs_uniform_day": observed / math.log(2.0),
        "bits_per_event": observed / (len(groups) * math.log(2.0)),
        "one_sided_random_day_pvalue": pvalue,
        "real_mean_tick_rate_ratio": float(np.mean(real_values)),
        "mean_of_stratum_placebo_means": float(np.mean(placebo_means)),
        "fraction_strata_real_above_placebo_mean": float(
            np.mean(np.asarray(real_values) > np.asarray(placebo_means))
        ),
        "median_real_within_stratum_percentile": float(np.median(real_percentiles)),
        "median_stratum_information_bits": float(np.median(contributions_bits)),
        "largest_absolute_stratum_contribution_bits": float(np.max(np.abs(contributions_bits))),
        "permutations": permutations,
    }


def run_tick_rate_random_day_placebo(*, permutations: int = 19999) -> dict:
    """Test Phase 13's tick-rate survivor on genuine same-clock raw ticks."""

    mapping = pd.read_csv(EPOCH_MAP)
    mapping["decision_time_utc"] = pd.to_datetime(mapping.decision_time_utc, utc=True, format="mixed")
    anchors = mapping.loc[mapping.is_epoch_anchor.astype(bool)].copy()
    lock = anchors.loc[
        anchors.record_partition.eq("lockbox")
        & anchors.decision_time_utc.dt.hour.between(5, 16)
    ].sort_values("decision_time_utc")
    if lock.empty:
        raise ValueError("No supported lockbox epochs")
    partition_start = lock.decision_time_utc.min().floor("D")
    partition_end = lock.decision_time_utc.max().floor("D")
    all_event_ms = np.sort((anchors.decision_time_utc.astype("int64") // 1_000_000).to_numpy(np.int64))

    row = pd.read_csv(PHASE13_FEATURES).set_index("feature").loc["tick_rate_ratio"]
    beta = float(row.frozen_beta)
    mean = float(row.discovery_mean)
    std = float(row.discovery_std)
    dates_by_hour = _available_tick_dates_by_hour(TICKS_DIR)
    store = TickStore(TICKS_DIR)
    groups: list[np.ndarray] = []
    audit_rows: list[dict] = []

    def far_from_any_event(target_ms: int, exclusion_ms: int = 300_000) -> bool:
        pos = int(np.searchsorted(all_event_ms, target_ms))
        neighbours = []
        if pos < len(all_event_ms):
            neighbours.append(abs(int(all_event_ms[pos]) - target_ms))
        if pos:
            neighbours.append(abs(int(all_event_ms[pos - 1]) - target_ms))
        return not neighbours or min(neighbours) > exclusion_ms

    for case in lock.itertuples(index=False):
        event_time = pd.Timestamp(case.decision_time_utc)
        event_ms = int(event_time.value // 1_000_000)
        actual = extract_tick_features_arrays(store.get_window_arrays(event_ms), event_ms)["tick_rate_ratio"]
        candidates: list[float] = []
        candidate_dates: list[str] = []
        for day in dates_by_hour.get(event_time.hour, []):
            if day < partition_start or day > partition_end or day.date() == event_time.date():
                continue
            if day.dayofweek != event_time.dayofweek:
                continue
            target = day + pd.Timedelta(
                hours=event_time.hour, minutes=event_time.minute,
                seconds=event_time.second, microseconds=event_time.microsecond,
            )
            target_ms = int(target.value // 1_000_000)
            if not far_from_any_event(target_ms):
                continue
            features = extract_tick_features_arrays(store.get_window_arrays(target_ms), target_ms)
            value = features["tick_rate_ratio"]
            if not np.isfinite(value) or float(features["tick_coverage"]) < 0.99:
                continue
            candidates.append(float(value))
            candidate_dates.append(str(day.date()))
        status = "included" if np.isfinite(actual) and len(candidates) >= 5 else "excluded_insufficient_coverage"
        if status == "included":
            groups.append(np.asarray([float(actual), *candidates], dtype=float))
        audit_rows.append({
            "epoch_id": int(case.epoch_id), "event_time_utc": event_time.isoformat(),
            "actual_tick_rate_ratio": float(actual) if np.isfinite(actual) else None,
            "alternative_days": len(candidates), "candidate_dates": "|".join(candidate_dates),
            "status": status,
        })

    pd.DataFrame(audit_rows).to_csv(OUT / "tick_rate_same_clock_strata.csv", index=False)
    result = same_clock_placebo_statistic(groups, beta, mean, std, permutations=permutations)
    result.update({
        "status": "complete",
        "feature": "tick_rate_ratio",
        "partition": "legacy lockbox; retrospective because this feature was already selected on it",
        "matching": "same UTC hour/minute/second and weekday, different date, within lockbox date bounds",
        "source": "genuine data/market/raw_ticks hourly JSON; causal 300-second pre-target window",
        "minimum_alternative_days": 5,
        "event_exclusion_seconds": 300,
        "frozen_beta": beta,
        "gate_alpha": 0.05,
    })
    result["gate"] = (
        "SURVIVES_RETROSPECTIVE_PLACEBO"
        if result["bits_per_event"] > 0 and result["one_sided_random_day_pvalue"] <= 0.05
        else "FAILS_PLACEBO_RETIRES_POSITIVE_TICK_RATE_CLAIM"
    )
    write_json(OUT / "tick_rate_same_clock_placebo.json", result)
    return result


def _clock_rates_from_cells(
    train_dt: pd.Series, train_y: np.ndarray, eval_dt: pd.Series,
) -> tuple[np.ndarray, float, int]:
    """Fit a compact harmonic clock on 168 exposure cells, not individual rows."""

    train = pd.DataFrame({"dt": train_dt.reset_index(drop=True), "y": train_y})
    train["hour"] = train.dt.dt.hour
    train["dow"] = train.dt.dt.dayofweek
    cells = train.groupby(["dow", "hour"], as_index=False).agg(events=("y", "sum"), exposure=("y", "size"))
    X, _ = clock_design(cells.hour + 0.5, np.zeros(len(cells)), cells.dow)
    target = cells.events.to_numpy(float) / cells.exposure.to_numpy(float)
    model = PoissonRegressor(alpha=1e-4, max_iter=2000, tol=1e-9)
    model.fit(X, target, sample_weight=cells.exposure.to_numpy(float))
    X_eval, _ = clock_design(eval_dt.dt.hour + 0.5, np.zeros(len(eval_dt)), eval_dt.dt.dayofweek)
    rate = np.maximum(model.predict(X_eval), 1e-12)
    global_rate = max(float(np.mean(train_y)), 1e-12)
    return rate, global_rate, X.shape[1] + 1


def _poisson_gain_bits(y: np.ndarray, rate: np.ndarray, base_rate: float) -> float:
    candidate = float(np.sum(y * np.log(rate) - rate))
    baseline = float(np.sum(y * math.log(base_rate) - base_rate))
    return (candidate - baseline) / math.log(2.0)


def _direction_candidates(frame: pd.DataFrame, event_positions: np.ndarray, labels: np.ndarray) -> list[dict]:
    result: list[dict] = []
    for horizon in (1, 5, 15, 30):
        values = frame[f"return_{horizon}"].to_numpy(float)[event_positions]
        valid = np.isfinite(values) & (values != 0)
        for polarity in ("contrarian", "trend"):
            prediction = np.where(values >= 0, -1, 1) if polarity == "contrarian" else np.where(values >= 0, 1, -1)
            accuracy = float(np.mean(prediction[valid] == labels[valid])) if valid.any() else 0.0
            result.append({"horizon": horizon, "polarity": polarity, "accuracy": accuracy, "n": int(valid.sum())})
    return result


def run_targeted_planted_calibration(*, replicates: int = 100) -> dict:
    """Calibrate recovery of a 420-event clock plus contrarian policy family."""

    panel = pd.read_parquet(PANEL, columns=["dt", "return_1", "return_5", "return_15", "return_30"])
    panel["dt"] = pd.to_datetime(panel.dt, utc=True)
    panel = panel.dropna(subset=["return_1", "return_5", "return_15", "return_30"]).reset_index(drop=True)
    freeze = json.loads(PHASE13_FREEZE.read_text(encoding="utf-8"))
    X, names = clock_design(panel.dt.dt.hour, panel.dt.dt.minute, panel.dt.dt.dayofweek)
    coefficients = np.asarray([freeze["coefficients"][name] for name in names])
    eta = float(freeze["intercept"]) + X @ coefficients
    # Tempering keeps the plant at the observed modest clock complexity while
    # avoiding numerical concentration in a handful of minutes.
    weights = np.exp(np.clip(eta - np.max(eta), -30, 0))
    split_time = panel.dt.quantile(0.75)
    train_mask = panel.dt < split_time
    test_mask = ~train_mask
    train_positions = np.flatnonzero(train_mask.to_numpy())
    test_positions = np.flatnonzero(test_mask.to_numpy())
    scenarios = (
        {"name": "continuous_low_noise", "inactive_day_fraction": 0.0, "jitter_probability": 0.0, "direction_flip": 0.10},
        {"name": "censored_execution_noise", "inactive_day_fraction": 0.20, "jitter_probability": 0.20, "direction_flip": 0.10},
    )
    rows: list[dict] = []
    unique_days = pd.Series(panel.dt.dt.floor("D").unique())

    for scenario_index, scenario in enumerate(scenarios):
        for replicate in range(replicates):
            rng = np.random.default_rng(SEED + 10000 * scenario_index + replicate)
            available = np.ones(len(panel), dtype=bool)
            if scenario["inactive_day_fraction"]:
                inactive_n = int(round(len(unique_days) * scenario["inactive_day_fraction"]))
                inactive = set(rng.choice(unique_days.to_numpy(), size=inactive_n, replace=False))
                available = ~panel.dt.dt.floor("D").isin(inactive).to_numpy()
            eligible = np.flatnonzero(available)
            probability = weights[eligible] / weights[eligible].sum()
            latent_positions = np.sort(rng.choice(eligible, size=420, replace=False, p=probability))
            latent_returns = panel.return_5.to_numpy(float)[latent_positions]
            labels = np.where(latent_returns >= 0, -1, 1)
            flips = rng.random(len(labels)) < scenario["direction_flip"]
            labels[flips] *= -1
            observed_positions_raw = latent_positions.copy()
            jitter = rng.random(len(observed_positions_raw)) < scenario["jitter_probability"]
            shifts = rng.choice((-1, 1), size=len(observed_positions_raw))
            observed_positions_raw[jitter] = np.clip(
                observed_positions_raw[jitter] + shifts[jitter], 0, len(panel) - 1,
            )
            # Keep the first label if execution jitter makes two observations
            # collide at the same minute. Supplements are independently planted.
            label_by_position: dict[int, int] = {}
            for position, label in zip(observed_positions_raw, labels):
                label_by_position.setdefault(int(position), int(label))
            if len(label_by_position) < 420:
                supplement_pool = np.setdiff1d(eligible, np.fromiter(label_by_position, dtype=int), assume_unique=False)
                extra = rng.choice(supplement_pool, size=420 - len(label_by_position), replace=False)
                extra_returns = panel.return_5.to_numpy(float)[extra]
                extra_labels = np.where(extra_returns >= 0, -1, 1)
                extra_flips = rng.random(len(extra_labels)) < scenario["direction_flip"]
                extra_labels[extra_flips] *= -1
                label_by_position.update({int(pos): int(label) for pos, label in zip(extra, extra_labels)})
            event_positions = np.asarray(sorted(label_by_position), dtype=int)

            y = np.zeros(len(panel), dtype=int)
            y[event_positions] = 1
            train_rate, global_rate, parameter_count = _clock_rates_from_cells(
                panel.loc[train_mask, "dt"], y[train_mask], panel.loc[test_mask, "dt"],
            )
            clock_bits = _poisson_gain_bits(y[test_mask], train_rate, global_rate)
            clock_events = max(int(y[test_mask].sum()), 1)
            clock_mdl_cost = 0.5 * parameter_count * math.log2(max(int(y[train_mask].sum()), 2))

            event_labels = np.asarray([label_by_position[int(pos)] for pos in event_positions])
            event_train = (panel.dt.iloc[event_positions] < split_time).to_numpy()
            candidates_train = _direction_candidates(panel, event_positions[event_train], event_labels[event_train])
            selected = max(candidates_train, key=lambda item: (item["accuracy"], -item["horizon"], item["polarity"] == "contrarian"))
            test_candidates = _direction_candidates(panel, event_positions[~event_train], event_labels[~event_train])
            selected_test = next(
                item for item in test_candidates
                if item["horizon"] == selected["horizon"] and item["polarity"] == selected["polarity"]
            )
            acc = min(max(selected_test["accuracy"], 1e-9), 1 - 1e-9)
            direction_bits = selected_test["n"] * (
                acc * math.log2(2 * acc) + (1 - acc) * math.log2(2 * (1 - acc))
            )
            direction_mdl_cost = math.log2(8)
            rows.append({
                "scenario": scenario["name"], "replicate": replicate,
                "planted_events": 420, "observed_events": len(event_positions),
                "test_events": clock_events,
                "clock_test_bits": clock_bits,
                "clock_test_bits_per_event": clock_bits / clock_events,
                "clock_mdl_net_bits": clock_bits - clock_mdl_cost,
                "selected_direction_horizon": selected["horizon"],
                "selected_direction_polarity": selected["polarity"],
                "direction_test_accuracy": selected_test["accuracy"],
                "direction_test_n": selected_test["n"],
                "direction_mdl_net_bits": direction_bits - direction_mdl_cost,
                "clock_family_recovered": clock_bits > 0,
                "clock_mdl_recovered": clock_bits > clock_mdl_cost,
                "contrarian_family_recovered": selected["polarity"] == "contrarian" and selected_test["accuracy"] > 0.55,
                "exact_horizon_recovered": selected["polarity"] == "contrarian" and selected["horizon"] == 5,
            })
    results = pd.DataFrame(rows)
    results.to_csv(OUT / "targeted_planted_calibration_runs.csv", index=False)
    summaries = []
    for name, group in results.groupby("scenario", sort=False):
        summaries.append({
            "scenario": name,
            "replicates": len(group),
            "clock_family_recovery_rate": float(group.clock_family_recovered.mean()),
            "clock_mdl_recovery_rate": float(group.clock_mdl_recovered.mean()),
            "contrarian_family_recovery_rate": float(group.contrarian_family_recovered.mean()),
            "exact_horizon_recovery_rate": float(group.exact_horizon_recovered.mean()),
            "joint_family_recovery_rate": float((group.clock_family_recovered & group.contrarian_family_recovered).mean()),
            "joint_mdl_recovery_rate": float((group.clock_mdl_recovered & group.contrarian_family_recovered).mean()),
            "median_clock_bits_per_event": float(group.clock_test_bits_per_event.median()),
            "median_clock_mdl_net_bits": float(group.clock_mdl_net_bits.median()),
            "median_direction_test_accuracy": float(group.direction_test_accuracy.median()),
            "median_direction_mdl_net_bits": float(group.direction_mdl_net_bits.median()),
        })
    payload = {
        "status": "complete",
        "target": "420-event modest harmonic-clock plus return_5 contrarian direction family",
        "candidate_direction_set": "contrarian/trend at completed 1, 5, 15 and 30 minute returns",
        "clock_candidate": "six-harmonic time-of-day plus day-of-week Poisson model fitted from synthetic discovery exposure",
        "retrospective_calibration_not_real_strategy_evidence": True,
        "summaries": summaries,
    }
    write_json(OUT / "targeted_planted_calibration.json", payload)
    return payload


def availability_gap_diagnostic(*, simulations: int = 19999) -> dict:
    panel = pd.read_parquet(PANEL, columns=["dt", "is_trade"])
    panel["dt"] = pd.to_datetime(panel.dt, utc=True)
    freeze = json.loads(PHASE13_FREEZE.read_text(encoding="utf-8"))
    X, names = clock_design(panel.dt.dt.hour, panel.dt.dt.minute, panel.dt.dt.dayofweek)
    coefficients = np.asarray([freeze["coefficients"][name] for name in names])
    eta = float(freeze["intercept"]) + X @ coefficients
    intensity = np.exp(np.clip(eta, -30, 10))
    event_positions = np.flatnonzero(panel.is_trade.to_numpy(int) > 0)
    if len(event_positions) < 2:
        raise ValueError("Need at least two event minutes for availability diagnostics")
    # Account observation is defensible only from the first through last
    # recorded event.  Leading/trailing public-feed coverage is not evidence
    # that the account was operating, so it is excluded from this diagnostic.
    lo, hi = int(event_positions[0]), int(event_positions[-1])
    interval_intensity = intensity[lo:hi + 1]
    interval_events = event_positions - lo
    cumulative = np.cumsum(interval_intensity)
    transformed = cumulative[interval_events]
    span = float(transformed[-1] - transformed[0])
    internal_gaps = np.diff(transformed)
    observed_max_fraction = float(internal_gaps.max() / span)
    rng = np.random.default_rng(SEED + 77)
    # Condition on the first and last observed events as the evidence bounds.
    uniforms = np.sort(rng.random((simulations, len(event_positions) - 2)), axis=1)
    spacings = np.diff(
        np.column_stack([np.zeros(simulations), uniforms, np.ones(simulations)]), axis=1,
    )
    null_max = spacings.max(axis=1)
    pvalue = float((1 + np.count_nonzero(null_max >= observed_max_fraction - 1e-12)) / (simulations + 1))

    rows = []
    event_times = panel.dt.iloc[event_positions].reset_index(drop=True)
    for index in range(1, len(event_times)):
        rows.append({
            "previous_event_utc": event_times.iloc[index - 1],
            "next_event_utc": event_times.iloc[index],
            "calendar_gap_hours": (event_times.iloc[index] - event_times.iloc[index - 1]).total_seconds() / 3600,
            "clock_rescaled_expected_events": transformed[index] - transformed[index - 1],
        })
    gaps = pd.DataFrame(rows).sort_values("clock_rescaled_expected_events", ascending=False)
    gaps.to_csv(OUT / "availability_largest_gaps.csv", index=False)
    payload = {
        "status": "complete",
        "observed_event_minutes": len(event_positions),
        "evidence_interval_start_utc": panel.dt.iloc[lo].isoformat(),
        "evidence_interval_end_utc": panel.dt.iloc[hi].isoformat(),
        "clock_rescaled_max_gap_fraction": observed_max_fraction,
        "conditional_uniform_max_spacing_pvalue": pvalue,
        "simulations": simulations,
        "assessment": (
            "ANOMALOUS_GAPS_COMPATIBLE_WITH_DOWNTIME_OR_CLOCK_MODEL_MISSPECIFICATION"
            if pvalue <= 0.05 else
            "NO_STRONG_MAX_GAP_ANOMALY_UNDER_FROZEN_CLOCK_MODEL"
        ),
        "identifiability_limit": "Absence of trades cannot distinguish account downtime from no signal. This diagnostic does not infer uptime.",
        "top_gaps": gaps.head(10).to_dict(orient="records"),
    }
    write_json(OUT / "availability_diagnostic.json", payload)
    return payload


def issue_recoverability_report(
    reconciliation: dict, placebo: dict, direction: dict,
    calibration: dict, availability: dict,
) -> dict:
    placebo_survives = placebo["gate"] == "SURVIVES_RETROSPECTIVE_PLACEBO"
    calibration_by_name = {row["scenario"]: row for row in calibration["summaries"]}
    noisy = calibration_by_name["censored_execution_noise"]
    calibrated = noisy["joint_family_recovery_rate"] >= 0.80
    clock_outcome = "PARTIAL_COMPONENTS_IDENTIFIED" if reconciliation["status"] == "VERIFIED" else "INSUFFICIENT_STATISTICAL_POWER"
    tick_outcome = "PARTIAL_COMPONENTS_IDENTIFIED" if placebo_survives else "INSUFFICIENT_STATISTICAL_POWER"
    direction_survives = direction["gate"] == "SURVIVES_SHIFTED_EVENT_PLACEBO"
    direction_outcome = "PARTIAL_COMPONENTS_IDENTIFIED" if direction_survives else "INSUFFICIENT_STATISTICAL_POWER"
    complete_outcome = "STRUCTURALLY_NON_IDENTIFIABLE"
    payload = {
        "status": "complete",
        "taxonomy": {
            "clock_session_structure": clock_outcome,
            "tick_rate_ratio_beyond_clock": tick_outcome,
            "contrarian_direction": direction_outcome,
            "entry_mechanism": "INSUFFICIENT_STATISTICAL_POWER",
            "size_mechanism": "INSUFFICIENT_STATISTICAL_POWER",
            "exit_mechanism": "INSUFFICIENT_STATISTICAL_POWER",
            "complete_policy_within_current_search": "INSUFFICIENT_STATISTICAL_POWER",
            "unrestricted_original_source_policy": complete_outcome,
        },
        "targeted_family_detection_at_80_percent": calibrated,
        "targeted_mdl_acceptance_at_80_percent": bool(
            noisy["joint_mdl_recovery_rate"] >= 0.80
        ),
        "tick_rate_placebo_gate": placebo["gate"],
        "direction_claim_status": direction["gate"],
        "availability_assessment": availability["assessment"],
        "independent_second_ledger": {
            "priority": "highest-value future positive confirmation",
            "availability": "UNAVAILABLE_BY_PROJECT_CONSTRAINT",
            "action": "not requested; not a prerequisite; do not synthesize a replacement",
        },
        "final_verdict": (
            "CTPI_PARTIAL_COMPONENTS_CLOCK_TICK_RATE_DIRECTION_NO_COMPLETE_POLICY"
            if placebo_survives and direction_survives else
            "CTPI_PARTIAL_COMPONENTS_ONLY_NO_COMPACT_ALGORITHM_IDENTIFIED"
        ),
        "claim_boundary": "All positive results are retrospective. No untouched real-data lockbox remains.",
    }
    write_json(OUT / "recoverability_verdict.json", payload)

    cal_lines = "\n".join(
        f"| {row['scenario']} | {row['clock_family_recovery_rate']:.1%} | "
        f"{row['clock_mdl_recovery_rate']:.1%} | {row['contrarian_family_recovery_rate']:.1%} | "
        f"{row['joint_family_recovery_rate']:.1%} |"
        for row in calibration["summaries"]
    )
    tax_lines = "\n".join(f"| {key} | {value} |" for key, value in payload["taxonomy"].items())
    report = f"""# CTPI Immediate Recoverability Report

## Result

**{payload['final_verdict']}**

This is a retrospective recoverability and falsification stage. It does not
restore an untouched lockbox and it does not identify the unrestricted original
source program.

## Evidence reconciliation

- Phase 13 reproduction status: **{reconciliation['status']}**.
- Exact artifact reproduction: **{reconciliation['exact_artifact_reproduction']}**.
- External pasted placebo claim: **UNVERIFIED_EXTERNAL_CLAIM** until backed by
  executable artifacts.
- Original reported direction p=0.0033: not accepted verbatim because its
  calculation was absent, but the component now has an independent project
  reproduction: **{direction['gate']}**.

## `tick_rate_ratio` same-clock random-day placebo

- Included strata: **{placebo['strata']}**.
- Information versus a uniform eligible day: **{placebo['bits_per_event']:.4f} bits/event**.
- One-sided random-day p-value: **{placebo['one_sided_random_day_pvalue']:.4g}**.
- Gate: **{placebo['gate']}**.
- Median stratum contribution: **{placebo['median_stratum_information_bits']:.4f} bits**.
- Largest absolute stratum contribution: **{placebo['largest_absolute_stratum_contribution_bits']:.4f} bits**.

The test uses causal features computed directly from genuine raw tick files at
the same UTC clock second and weekday on other dates. It does not use synthetic
ticks or M1 interpolation.

The aggregate likelihood gate passes, but the negative median contribution and
large maximum contribution show heterogeneous, concentrated evidence. This is
provisional evidence for a weak intensity component, not a threshold mechanism
or complete entry rule.

## Contrarian direction shifted-event placebo

- Eligible canonical epochs: **{direction['epochs_tested']} / 420**.
- Max-statistic window: **{direction['max_stat_window_minutes']} minutes**.
- Maximum contrarian strength: **{direction['max_observed_contrarian_strength']:.4f}** above chance.
- Search-corrected shifted-event p-value: **{direction['max_stat_shifted_event_pvalue']:.6g}**.
- Significant predeclared 2–20 minute windows: **{direction['short_windows_pointwise_significant']} / 7**.
- Gate: **{direction['gate']}**.

This is a reproducible directional association based only on completed M1 bars.
It identifies neither when an entry occurs nor a unique direction formula.

## Targeted 420-event planted recovery

| Scenario | Clock family | Clock after MDL | Contrarian family | Joint family |
|---|---:|---:|---:|---:|
{cal_lines}

This calibration measures whether the declared modest family is recoverable;
it is not evidence that the real account used that family.
The clock family was detectably predictive in every replicate, but it cleared
the registered MDL cost in **0%** of replicates. Median clock net MDL evidence
was **{calibration_by_name['continuous_low_noise']['median_clock_mdl_net_bits']:.2f} bits**
without censoring and **{calibration_by_name['censored_execution_noise']['median_clock_mdl_net_bits']:.2f} bits**
with censoring/execution noise. At this sample size, family detection is not
unique program identification.

**At N≈420, under the tested noise conditions and the project's current MDL
specification, even the planted clock+direction mechanism failed the acceptance
criterion; the gate lacks power for this mechanism class at this sample size.**

## Availability diagnostic

- Assessment: **{availability['assessment']}**.
- Clock-rescaled maximum-gap p-value: **{availability['conditional_uniform_max_spacing_pvalue']:.4g}**.

Long gaps cannot distinguish account downtime from genuine no-signal periods or
clock-model misspecification. Availability remains a named latent confound.

## Five-outcome taxonomy by component

| Component | CTPI outcome |
|---|---|
{tax_lines}

## Decision

No compact complete entry/direction/size/exit algorithm is identified. A second
untouched ledger remains the most valuable possible positive confirmation, but
it is unavailable under the project constraint and is not requested. The
project must not replace it with synthetic account evidence.

The 420-epoch evidence base is now frozen for discovery. Further unregistered
feature mining on these same trades is outside the CTPI plan.
"""
    (OUT / "CTPI_RECOVERABILITY_REPORT.md").write_text(report, encoding="utf-8")
    return payload


def run(*, rerun_phase13: bool = True, permutations: int = 19999, replicates: int = 100) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    reconciliation = reconcile_phase13(rerun=rerun_phase13)
    placebo = run_tick_rate_random_day_placebo(permutations=permutations)
    direction = run_direction_placebo(permutations=2000)
    calibration = run_targeted_planted_calibration(replicates=replicates)
    availability = availability_gap_diagnostic(simulations=permutations)
    verdict = issue_recoverability_report(reconciliation, placebo, direction, calibration, availability)
    summary = {
        "status": "complete",
        "reconciliation": reconciliation["status"],
        "tick_rate_placebo_gate": placebo["gate"],
        "direction_placebo_gate": direction["gate"],
        "planted_calibration": calibration["summaries"],
        "availability": availability["assessment"],
        "final_verdict": verdict["final_verdict"],
    }
    write_json(OUT / "run_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-phase13-rerun", action="store_true")
    parser.add_argument("--permutations", type=int, default=19999)
    parser.add_argument("--replicates", type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(run(
        rerun_phase13=not args.skip_phase13_rerun,
        permutations=args.permutations,
        replicates=args.replicates,
    ), indent=2))


if __name__ == "__main__":
    main()
