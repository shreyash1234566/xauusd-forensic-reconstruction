"""CTPI Tracks 1 and 2: sample-size power and frozen-component replay audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from scripts.ctpi_immediate_execution import (
        PANEL, PHASE13_FEATURES, PHASE13_FREEZE, ROOT,
        _clock_rates_from_cells, _direction_candidates, _poisson_gain_bits,
        clock_design,
    )
    from scripts.ctpi_direction_placebo import M1
    from scripts.phase12_exact_entry_identity_audit import (
        PANEL_PATH, construct_canonical_E, construct_exhaustive_F, build_U,
    )
    from scripts.tickfeat10 import TickStore, extract_tick_features_arrays
except ModuleNotFoundError:
    from ctpi_immediate_execution import (
        PANEL, PHASE13_FEATURES, PHASE13_FREEZE, ROOT,
        _clock_rates_from_cells, _direction_candidates, _poisson_gain_bits,
        clock_design,
    )
    from ctpi_direction_placebo import M1
    from phase12_exact_entry_identity_audit import (
        PANEL_PATH, construct_canonical_E, construct_exhaustive_F, build_U,
    )
    from tickfeat10 import TickStore, extract_tick_features_arrays


OUT = ROOT / "outputs" / "ctpi_next_tracks"
TICKS_DIR = ROOT / "data" / "market" / "raw_ticks"
PHASE12 = ROOT / "outputs" / "strategy_reconstruction" / "phase12_exact_entry_identity_audit.json"
SEED = 20260927
EVENT_COUNTS = (800, 1600, 3200)


def write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _simulate_event_sample(
    panel: pd.DataFrame,
    weights: np.ndarray,
    event_count: int,
    scenario: dict,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    available = np.ones(len(panel), dtype=bool)
    if scenario["inactive_day_fraction"]:
        unique_days = pd.Series(panel.dt.dt.floor("D").unique())
        inactive_n = int(round(len(unique_days) * scenario["inactive_day_fraction"]))
        inactive = set(rng.choice(unique_days.to_numpy(), size=inactive_n, replace=False))
        available = ~panel.dt.dt.floor("D").isin(inactive).to_numpy()
    eligible = np.flatnonzero(available)
    probability = weights[eligible] / weights[eligible].sum()
    latent = np.sort(rng.choice(eligible, size=event_count, replace=False, p=probability))
    latent_returns = panel.return_5.to_numpy(float)[latent]
    labels = np.where(latent_returns >= 0, -1, 1)
    flips = rng.random(len(labels)) < scenario["direction_flip"]
    labels[flips] *= -1

    observed = latent.copy()
    jitter = rng.random(len(observed)) < scenario["jitter_probability"]
    shifts = rng.choice((-1, 1), size=len(observed))
    observed[jitter] = np.clip(observed[jitter] + shifts[jitter], 0, len(panel) - 1)
    label_by_position: dict[int, int] = {}
    for position, label in zip(observed, labels):
        label_by_position.setdefault(int(position), int(label))
    if len(label_by_position) < event_count:
        pool = np.setdiff1d(eligible, np.fromiter(label_by_position, dtype=int), assume_unique=False)
        extra = rng.choice(pool, size=event_count - len(label_by_position), replace=False)
        extra_labels = np.where(panel.return_5.to_numpy(float)[extra] >= 0, -1, 1)
        extra_flips = rng.random(len(extra_labels)) < scenario["direction_flip"]
        extra_labels[extra_flips] *= -1
        label_by_position.update({int(pos): int(label) for pos, label in zip(extra, extra_labels)})
    positions = np.asarray(sorted(label_by_position), dtype=int)
    event_labels = np.asarray([label_by_position[int(position)] for position in positions], dtype=int)
    return positions, event_labels


def run_power_curve(*, replicates: int = 100, event_counts: tuple[int, ...] = EVENT_COUNTS) -> dict:
    panel = pd.read_parquet(PANEL, columns=["dt", "return_1", "return_5", "return_15", "return_30"])
    panel["dt"] = pd.to_datetime(panel.dt, utc=True)
    panel = panel.dropna(subset=["return_1", "return_5", "return_15", "return_30"]).reset_index(drop=True)
    freeze = json.loads(PHASE13_FREEZE.read_text(encoding="utf-8"))
    X, names = clock_design(panel.dt.dt.hour, panel.dt.dt.minute, panel.dt.dt.dayofweek)
    coefficients = np.asarray([freeze["coefficients"][name] for name in names])
    eta = float(freeze["intercept"]) + X @ coefficients
    weights = np.exp(np.clip(eta - np.max(eta), -30, 0))
    split_time = panel.dt.quantile(0.75)
    train_mask = panel.dt < split_time
    test_mask = ~train_mask
    scenarios = (
        {"name": "continuous_low_noise", "inactive_day_fraction": 0.0, "jitter_probability": 0.0, "direction_flip": 0.10},
        {"name": "censored_execution_noise", "inactive_day_fraction": 0.20, "jitter_probability": 0.20, "direction_flip": 0.10},
    )
    rows: list[dict] = []
    for event_count in event_counts:
        for scenario_index, scenario in enumerate(scenarios):
            for replicate in range(replicates):
                rng = np.random.default_rng(SEED + event_count * 1000 + scenario_index * 10000 + replicate)
                positions, labels = _simulate_event_sample(panel, weights, event_count, scenario, rng)
                y = np.zeros(len(panel), dtype=int)
                y[positions] = 1
                test_rate, base_rate, parameter_count = _clock_rates_from_cells(
                    panel.loc[train_mask, "dt"], y[train_mask], panel.loc[test_mask, "dt"],
                )
                clock_bits = _poisson_gain_bits(y[test_mask], test_rate, base_rate)
                test_events = max(int(y[test_mask].sum()), 1)
                clock_cost = 0.5 * parameter_count * math.log2(max(int(y[train_mask].sum()), 2))
                event_train = (panel.dt.iloc[positions] < split_time).to_numpy()
                train_candidates = _direction_candidates(panel, positions[event_train], labels[event_train])
                selected = max(
                    train_candidates,
                    key=lambda item: (item["accuracy"], -item["horizon"], item["polarity"] == "contrarian"),
                )
                test_candidates = _direction_candidates(panel, positions[~event_train], labels[~event_train])
                selected_test = next(
                    item for item in test_candidates
                    if item["horizon"] == selected["horizon"] and item["polarity"] == selected["polarity"]
                )
                accuracy = min(max(selected_test["accuracy"], 1e-9), 1 - 1e-9)
                direction_bits = selected_test["n"] * (
                    accuracy * math.log2(2 * accuracy)
                    + (1 - accuracy) * math.log2(2 * (1 - accuracy))
                )
                direction_net = direction_bits - math.log2(8)
                clock_net = clock_bits - clock_cost
                rows.append({
                    "event_count": event_count, "scenario": scenario["name"], "replicate": replicate,
                    "test_events": test_events, "clock_bits_per_event": clock_bits / test_events,
                    "clock_mdl_net_bits": clock_net,
                    "direction_mdl_net_bits": direction_net,
                    "selected_direction_horizon": selected["horizon"],
                    "selected_direction_polarity": selected["polarity"],
                    "direction_test_accuracy": selected_test["accuracy"],
                    "clock_mdl_accept": clock_net > 0,
                    "direction_mdl_accept": direction_net > 0 and selected["polarity"] == "contrarian",
                    "joint_mdl_accept": clock_net > 0 and direction_net > 0 and selected["polarity"] == "contrarian",
                })
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / "sample_size_power_curve_runs.csv", index=False)
    summary_rows = []
    for (event_count, scenario), group in frame.groupby(["event_count", "scenario"], sort=True):
        summary_rows.append({
            "event_count": int(event_count), "scenario": scenario, "replicates": len(group),
            "clock_mdl_acceptance_rate": float(group.clock_mdl_accept.mean()),
            "direction_mdl_acceptance_rate": float(group.direction_mdl_accept.mean()),
            "joint_mdl_acceptance_rate": float(group.joint_mdl_accept.mean()),
            "median_clock_mdl_net_bits": float(group.clock_mdl_net_bits.median()),
            "median_direction_mdl_net_bits": float(group.direction_mdl_net_bits.median()),
            "median_direction_test_accuracy": float(group.direction_test_accuracy.median()),
        })
    first_by_scenario = {}
    for scenario in (item["name"] for item in scenarios):
        eligible = [row for row in summary_rows if row["scenario"] == scenario and row["joint_mdl_acceptance_rate"] >= 0.80]
        first_by_scenario[scenario] = min((row["event_count"] for row in eligible), default=None)
    payload = {
        "status": "complete",
        "event_counts": list(event_counts), "replicates_per_cell": replicates,
        "noise_models": [item["name"] for item in scenarios],
        "acceptance_definition": "clock net MDL > 0 and selected contrarian direction net MDL > 0",
        "first_tested_n_with_at_least_80pct_joint_acceptance": first_by_scenario,
        "scope_limit": "This is a grid result under the frozen planted mechanism and noise models, not a universal sample-size requirement.",
        "summary": summary_rows,
    }
    write_json(OUT / "sample_size_power_curve.json", payload)
    return payload


def _f1_threshold(scores: np.ndarray, labels: np.ndarray, total_cases: int) -> tuple[float, dict]:
    valid = np.isfinite(scores)
    values = scores[valid]
    y = labels[valid].astype(bool)
    order = np.argsort(-values, kind="stable")
    values, y = values[order], y[order]
    tp = np.cumsum(y)
    fp = np.cumsum(~y)
    fn = total_cases - tp
    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / max(total_cases, 1)
    f1 = np.divide(2 * precision * recall, precision + recall, out=np.zeros_like(precision), where=(precision + recall) > 0)
    # Thresholds change only after the last tied score.
    ends = np.r_[np.flatnonzero(values[1:] != values[:-1]), len(values) - 1]
    best = int(ends[np.argmax(f1[ends])])
    return float(values[best]), {
        "discovery_f1": float(f1[best]), "discovery_precision": float(precision[best]),
        "discovery_recall": float(recall[best]), "discovery_signals": int(best + 1),
    }


def _metrics(frame: pd.DataFrame) -> dict:
    y = frame.is_case.astype(bool).to_numpy()
    pred = frame.predicted_entry.astype(bool).to_numpy()
    tp = int(np.sum(y & pred)); fp = int(np.sum(~y & pred)); fn = int(np.sum(y & ~pred)); tn = int(np.sum(~y & ~pred))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "cases": int(y.sum()), "controls": int((~y).sum()), "signals": int(pred.sum()),
    }


def _completed_return_20(close: pd.Series, timestamp: pd.Timestamp) -> float:
    end = timestamp.floor("min") - pd.Timedelta(minutes=1)
    start = end - pd.Timedelta(minutes=20)
    try:
        return float(close.loc[end] - close.loc[start])
    except KeyError:
        return float("nan")


def run_validated_component_replay() -> dict:
    """Discovery-freeze a deterministic projection of the validated intensity score."""

    OUT.mkdir(parents=True, exist_ok=True)
    records, epochs = construct_canonical_E()
    flat = construct_exhaustive_F(records, epochs, PANEL_PATH)
    universe = build_U(epochs, flat).sort_values("timestamp_utc").reset_index(drop=True)
    universe["timestamp_utc"] = pd.to_datetime(universe.timestamp_utc, utc=True)
    universe["supported"] = universe.timestamp_utc.dt.hour.between(5, 16)

    freeze = json.loads(PHASE13_FREEZE.read_text(encoding="utf-8"))
    feature_row = pd.read_csv(PHASE13_FEATURES).set_index("feature").loc["tick_rate_ratio"]
    X, names = clock_design(
        universe.timestamp_utc.dt.hour, universe.timestamp_utc.dt.minute,
        universe.timestamp_utc.dt.dayofweek,
    )
    coefficients = np.asarray([freeze["coefficients"][name] for name in names])
    universe["clock_eta"] = float(freeze["intercept"]) + X @ coefficients

    store = TickStore(TICKS_DIR)
    ratios = np.full(len(universe), np.nan)
    coverage = np.zeros(len(universe), dtype=float)
    for index, timestamp in enumerate(universe.timestamp_utc):
        if not universe.supported.iloc[index]:
            continue
        target_ms = int(timestamp.value // 1_000_000)
        features = extract_tick_features_arrays(store.get_window_arrays(target_ms), target_ms)
        ratios[index] = float(features["tick_rate_ratio"])
        coverage[index] = float(features["tick_coverage"])
    universe["tick_rate_ratio"] = ratios
    universe["tick_coverage"] = coverage
    z = (ratios - float(feature_row.discovery_mean)) / float(feature_row.discovery_std)
    score = universe.clock_eta.to_numpy(float) + float(feature_row.frozen_beta) * z
    score[(coverage < 0.99) | ~universe.supported.to_numpy()] = np.nan
    universe["validated_component_score"] = score

    discovery = universe.partition.eq("discovery").to_numpy()
    total_discovery_cases = int((universe.is_case.astype(bool) & discovery).sum())
    threshold, threshold_metrics = _f1_threshold(
        score[discovery], universe.is_case.to_numpy()[discovery], total_discovery_cases,
    )
    universe["predicted_entry"] = np.isfinite(score) & (score >= threshold)

    side_by_epoch = epochs.set_index("epoch_id").side.to_dict()
    universe["observed_side"] = universe.epoch_id.map(side_by_epoch)
    bars = pd.read_csv(M1, usecols=["timestamp", "close"])
    bars["timestamp"] = pd.to_datetime(bars.timestamp, utc=True)
    close = bars.drop_duplicates("timestamp", keep="last").set_index("timestamp").close.sort_index()
    predicted_side = []
    return20 = []
    for row in universe.itertuples(index=False):
        if not row.predicted_entry:
            return20.append(float("nan")); predicted_side.append(None); continue
        value = _completed_return_20(close, pd.Timestamp(row.timestamp_utc))
        return20.append(value)
        predicted_side.append("Sell" if value > 0 else "Buy" if value < 0 else None)
    universe["completed_return_20"] = return20
    universe["predicted_side"] = predicted_side
    universe["direction_correct"] = (
        universe.is_case.astype(bool) & universe.predicted_entry
        & universe.observed_side.eq(universe.predicted_side)
    )

    metrics = {}
    for partition in ("discovery", "buffer", "lockbox", "COMPLETE_LEDGER"):
        subset = universe if partition == "COMPLETE_LEDGER" else universe.loc[universe.partition.eq(partition)]
        values = _metrics(subset)
        matched = subset.loc[subset.is_case.astype(bool) & subset.predicted_entry & subset.predicted_side.notna()]
        values["direction_accuracy_among_entry_tp"] = float(matched.direction_correct.mean()) if len(matched) else None
        correct = int(subset.direction_correct.sum())
        control_signals = int((~subset.is_case.astype(bool) & subset.predicted_entry).sum())
        wrong_direction = int((subset.is_case.astype(bool) & subset.predicted_entry & ~subset.direction_correct).sum())
        joint_fp = control_signals + wrong_direction
        joint_fn = int(subset.is_case.astype(bool).sum()) - correct
        joint_precision = correct / (correct + joint_fp) if correct + joint_fp else 0.0
        joint_recall = correct / (correct + joint_fn) if correct + joint_fn else 0.0
        values["entry_direction_joint"] = {
            "tp": correct, "fp": joint_fp, "fn": joint_fn,
            "precision": joint_precision, "recall": joint_recall,
            "f1": 2 * joint_precision * joint_recall / (joint_precision + joint_recall)
            if joint_precision + joint_recall else 0.0,
        }
        metrics[partition] = values

    universe.to_parquet(OUT / "validated_component_universe.parquet", index=False)
    baseline = json.loads(PHASE12.read_text(encoding="utf-8"))["results_by_partition"]
    payload = {
        "status": "complete",
        "score": "frozen Phase13 harmonic clock eta + frozen beta * discovery-standardized tick_rate_ratio",
        "signal_conversion": "single threshold chosen only on discovery to maximize exact entry F1",
        "threshold": threshold, "threshold_discovery_fit": threshold_metrics,
        "direction": "contrarian to completed 20-minute public-feed M1 return",
        "coverage_rule": "05:00-16:59 UTC and causal raw-tick coverage >= 0.99",
        "metrics": metrics,
        "phase12_m3_baseline": baseline,
        "claim_limit": "This is a deterministic projection of validated components, not a discovered source trigger or complete lifecycle policy.",
        "input_hashes": {
            str(PANEL.relative_to(ROOT)).replace("\\", "/"): sha256(PANEL),
            str(PHASE13_FREEZE.relative_to(ROOT)).replace("\\", "/"): sha256(PHASE13_FREEZE),
            str(M1.relative_to(ROOT)).replace("\\", "/"): sha256(M1),
        },
    }
    write_json(OUT / "validated_component_replay.json", payload)
    return payload


def write_report(power: dict, replay: dict) -> None:
    power_rows = "\n".join(
        f"| {row['event_count']} | {row['scenario']} | {row['clock_mdl_acceptance_rate']:.1%} | "
        f"{row['direction_mdl_acceptance_rate']:.1%} | {row['joint_mdl_acceptance_rate']:.1%} | "
        f"{row['median_clock_mdl_net_bits']:.1f} |"
        for row in power["summary"]
    )
    metric_rows = "\n".join(
        f"| {partition} | {values['precision']:.4f} | {values['recall']:.4f} | {values['f1']:.4f} | "
        f"{values['entry_direction_joint']['precision']:.4f} | {values['entry_direction_joint']['recall']:.4f} | "
        f"{values['entry_direction_joint']['f1']:.4f} |"
        for partition, values in replay["metrics"].items()
    )
    baseline = replay["phase12_m3_baseline"]["COMPLETE_LEDGER"]
    current = replay["metrics"]["COMPLETE_LEDGER"]
    report = f"""# CTPI Next Tracks — Data Requirement and Validated-Component Replay

## Track 1 — Sample-size power under the frozen planted mechanism

| N | Scenario | Clock MDL pass | Direction MDL pass | Joint MDL pass | Median clock net bits |
|---:|---|---:|---:|---:|---:|
{power_rows}

First tested N with at least 80% joint MDL acceptance:

- Continuous low noise: **{power['first_tested_n_with_at_least_80pct_joint_acceptance']['continuous_low_noise']}**
- Censored/execution noise: **{power['first_tested_n_with_at_least_80pct_joint_acceptance']['censored_execution_noise']}**

These are grid results under the tested mechanism and noise models, not a
universal minimum data requirement.

## Track 2 — Frozen validated-component deterministic projection

The continuous intensity score is converted to signals with one threshold
selected strictly on discovery data. It is then frozen for buffer and lockbox.

| Partition | Entry precision | Entry recall | Entry F1 | Entry+direction precision | Entry+direction recall | Entry+direction F1 |
|---|---:|---:|---:|---:|---:|---:|
{metric_rows}

For the complete ledger, the Phase 12 M3 baseline had precision
**{baseline['precision']:.4f}**, recall **{baseline['recall']:.4f}**, and F1
**{baseline['f1']:.4f}**. The validated-component projection has precision
**{current['precision']:.4f}**, recall **{current['recall']:.4f}**, and F1
**{current['f1']:.4f}**.

This does not identify a source trigger. Clock and tick rate define an intensity,
not an entry command; the discovery-frozen threshold is an explicit diagnostic
projection. Exit and sizing remain outside this replay.
"""
    (OUT / "CTPI_NEXT_TRACKS_REPORT.md").write_text(report, encoding="utf-8")


def run(*, replicates: int = 100) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    power = run_power_curve(replicates=replicates)
    replay = run_validated_component_replay()
    write_report(power, replay)
    summary = {
        "status": "complete",
        "first_tested_n_80pct_joint_mdl": power["first_tested_n_with_at_least_80pct_joint_acceptance"],
        "complete_entry_metrics": replay["metrics"]["COMPLETE_LEDGER"],
    }
    write_json(OUT / "run_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replicates", type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(run(replicates=args.replicates), indent=2))


if __name__ == "__main__":
    main()

