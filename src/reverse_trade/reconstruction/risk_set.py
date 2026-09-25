"""Streaming construction of a quote-clock case-control risk set.

Controls are sampled independently of trade labels: one quote is drawn with a
fixed seed from every provider minute containing quotes. Its known inclusion
probability is 1 / quotes_in_minute. Cases are then attached from the fixed
canonical epochs as a separate role, so case timestamps never generate the
underlying quote clock or the controls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .coverage import parse_hour_filename
from .evidence import build_decision_epochs, load_canonical_records
from .io import write_json
from .validation import assert_causal_feature_frame


SEED = 20260924
LOOKBACK_MS = 30_000


def _decode(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with path.open("r", encoding="utf-8") as handle:
        values = json.load(handle)
    if not values:
        return np.array([], dtype=np.int64), np.array([], dtype=float), np.array([], dtype=float)
    if isinstance(values[0], dict):
        ts = np.asarray([row["timestamp"] for row in values], dtype=np.int64)
        ask = np.asarray([row["askPrice"] for row in values], dtype=float)
        bid = np.asarray([row["bidPrice"] for row in values], dtype=float)
    else:
        matrix = np.asarray(values, dtype=float)
        ts, ask, bid = matrix[:, 0].astype(np.int64), matrix[:, 1], matrix[:, 2]
    order = np.argsort(ts, kind="stable")
    return ts[order], ask[order], bid[order]


def _features(ts: np.ndarray, ask: np.ndarray, bid: np.ndarray, source_index: int) -> dict[str, Any]:
    """Features at one nanosecond after source_index, using timestamps <= source tick."""

    source_ms = int(ts[source_index])
    end = int(np.searchsorted(ts, source_ms, side="right"))
    start30 = int(np.searchsorted(ts, source_ms - 30_000, side="left"))
    start5 = int(np.searchsorted(ts, source_ms - 5_000, side="left"))
    t30, a30, b30 = ts[start30:end], ask[start30:end], bid[start30:end]
    t5, a5, b5 = ts[start5:end], ask[start5:end], bid[start5:end]
    mid30 = (a30 + b30) / 2.0
    mid5 = (a5 + b5) / 2.0
    complete30 = len(t30) >= 2 and int(t30[0]) <= source_ms - 29_000
    complete5 = len(t5) >= 2 and int(t5[0]) <= source_ms - 4_000
    valid = complete30 and complete5 and np.isfinite(mid30).all() and np.isfinite(mid5).all() and np.all(mid30 > 0)
    if valid:
        log_returns = np.diff(np.log(mid30))
        ret5 = float(mid5[-1] / mid5[0] - 1.0)
        ret30 = float(mid30[-1] / mid30[0] - 1.0)
        range30 = float(mid30.max() - mid30.min())
        vol30 = float(np.sqrt(np.square(log_returns).sum()))
        rate30 = float(len(t30) / 30.0)
        status = "observed"
    else:
        ret5 = ret30 = range30 = vol30 = rate30 = None
        status = "unknown_incomplete_lookback"
    source_time = pd.to_datetime(source_ms, unit="ms", utc=True)
    boundary = source_time + pd.Timedelta(nanoseconds=1)
    return {
        "decision_time_utc": boundary,
        "source_quote_time_utc": source_time,
        "maximum_input_time": source_time,
        "hour_utc": source_time.hour + source_time.minute / 60.0 + source_time.second / 3600.0,
        "day_of_week": source_time.dayofweek,
        "ret_5s": ret5,
        "ret_30s": ret30,
        "range_30s": range30,
        "realized_vol_30s": vol30,
        "spread_now": float(ask[source_index] - bid[source_index]),
        "tick_rate_30s": rate30,
        "feature_status": status,
    }


def _epoch_table(root: Path) -> pd.DataFrame:
    records = load_canonical_records(root)
    annotated, epochs = build_decision_epochs(records)
    volume = annotated.groupby("epoch_id").volume.sum()
    epochs = epochs[["epoch_id", "decision_time_utc", "side"]].copy()
    epochs["volume"] = epochs.epoch_id.map(volume)
    epochs["hour"] = pd.to_datetime(epochs.decision_time_utc, utc=True).dt.floor("h")
    return epochs


def build_sampled_quote_risk_set(root: Path, ticks_dir: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    epochs = _epoch_table(root)
    epoch_hours = {hour: group.copy() for hour, group in epochs.groupby("hour")}
    files = sorted(ticks_dir.glob("xauusd_ticks_*.json"), key=parse_hour_filename)
    if not files:
        raise FileNotFoundError(f"No hourly ticks in {ticks_dir}")
    risk_path = output / "sampled_quote_risk_set.csv"
    exposure_path = output / "quote_exposure_by_minute.csv"
    if risk_path.exists() or exposure_path.exists():
        raise FileExistsError("Risk-set outputs already exist; choose a new output directory")
    prior_ts = np.array([], dtype=np.int64)
    prior_ask = np.array([], dtype=float)
    prior_bid = np.array([], dtype=float)
    risk_header = exposure_header = True
    total_quotes = controls = cases = observed_features = 0
    aligned_case_ids: set[int] = set()
    for file_index, path in enumerate(files, start=1):
        hour = parse_hour_filename(path)
        ts, ask, bid = _decode(path)
        total_quotes += len(ts)
        if len(prior_ts):
            combined_ts = np.concatenate([prior_ts, ts])
            combined_ask = np.concatenate([prior_ask, ask])
            combined_bid = np.concatenate([prior_bid, bid])
            offset = len(prior_ts)
        else:
            combined_ts, combined_ask, combined_bid, offset = ts, ask, bid, 0
        rows: list[dict[str, Any]] = []
        exposure_rows: list[dict[str, Any]] = []
        if len(ts):
            minute_key = ts // 60_000
            unique_minutes, starts, counts = np.unique(minute_key, return_index=True, return_counts=True)
            for minute, start, count in zip(unique_minutes, starts, counts):
                # Seed per minute makes reruns/chunking invariant.
                rng = np.random.default_rng(SEED ^ (int(minute) & 0xFFFFFFFF))
                local = int(start + rng.integers(0, int(count)))
                feature = _features(combined_ts, combined_ask, combined_bid, offset + local)
                feature.update({
                    "row_role": "control",
                    "is_observed_epoch": False,
                    "epoch_id": None,
                    "side": None,
                    "volume": None,
                    "stratum_minute_utc": pd.to_datetime(int(minute) * 60_000, unit="ms", utc=True),
                    "quotes_in_stratum": int(count),
                    "control_inclusion_probability": 1.0 / int(count),
                    "case_quote_delta_seconds": None,
                    "provider_id": "dukascopy_supplemental",
                    "source_file": path.name,
                })
                rows.append(feature)
                exposure_rows.append({
                    "stratum_minute_utc": feature["stratum_minute_utc"],
                    "quote_count": int(count),
                    "sampled_control_quote_time_utc": feature["source_quote_time_utc"],
                    "control_inclusion_probability": 1.0 / int(count),
                    "provider_id": "dukascopy_supplemental",
                    "source_file": path.name,
                })
                controls += 1
        for epoch in epoch_hours.get(hour, pd.DataFrame()).itertuples(index=False):
            target_ms = int(pd.Timestamp(epoch.decision_time_utc).value // 1_000_000)
            source_index = int(np.searchsorted(combined_ts, target_ms, side="right") - 1) if len(combined_ts) else -1
            if source_index >= 0:
                feature = _features(combined_ts, combined_ask, combined_bid, source_index)
                delta = (target_ms - int(combined_ts[source_index])) / 1000.0
                if delta > 1.0:
                    feature["feature_status"] = "unknown_no_quote_within_observation_tolerance"
                feature.update({
                    "row_role": "case",
                    "is_observed_epoch": True,
                    "epoch_id": int(epoch.epoch_id),
                    "side": epoch.side,
                    "volume": float(epoch.volume),
                    "stratum_minute_utc": pd.Timestamp(epoch.decision_time_utc).floor("min"),
                    "quotes_in_stratum": None,
                    "control_inclusion_probability": 1.0,
                    "case_quote_delta_seconds": delta,
                    "provider_id": "dukascopy_supplemental",
                    "source_file": path.name,
                })
                aligned_case_ids.add(int(epoch.epoch_id))
            else:
                feature = {
                    "decision_time_utc": epoch.decision_time_utc,
                    "source_quote_time_utc": pd.NaT,
                    "maximum_input_time": pd.NaT,
                    "hour_utc": pd.Timestamp(epoch.decision_time_utc).hour,
                    "day_of_week": pd.Timestamp(epoch.decision_time_utc).dayofweek,
                    "ret_5s": None, "ret_30s": None, "range_30s": None, "realized_vol_30s": None,
                    "spread_now": None, "tick_rate_30s": None,
                    "feature_status": "unknown_no_preceding_quote",
                    "row_role": "case", "is_observed_epoch": True, "epoch_id": int(epoch.epoch_id),
                    "side": epoch.side, "volume": float(epoch.volume),
                    "stratum_minute_utc": pd.Timestamp(epoch.decision_time_utc).floor("min"),
                    "quotes_in_stratum": None, "control_inclusion_probability": 1.0,
                    "case_quote_delta_seconds": None, "provider_id": "dukascopy_supplemental", "source_file": path.name,
                }
            rows.append(feature)
            cases += 1
        if rows:
            frame = pd.DataFrame(rows)
            observed_features += int(frame.feature_status.eq("observed").sum())
            assert_causal_feature_frame(frame)
            frame.to_csv(risk_path, mode="w" if risk_header else "a", header=risk_header, index=False)
            risk_header = False
        if exposure_rows:
            pd.DataFrame(exposure_rows).to_csv(exposure_path, mode="w" if exposure_header else "a", header=exposure_header, index=False)
            exposure_header = False
        if len(ts):
            cutoff = int(ts[-1]) - LOOKBACK_MS
            keep = ts >= cutoff
            prior_ts, prior_ask, prior_bid = ts[keep], ask[keep], bid[keep]
        else:
            prior_ts = prior_ask = prior_bid = np.array([], dtype=float)
            prior_ts = prior_ts.astype(np.int64)
        if file_index % 250 == 0 or file_index == len(files):
            print(f"risk set: processed {file_index}/{len(files)} hours; controls={controls}; cases={cases}", flush=True)
    missing_cases = sorted(set(epochs.epoch_id.astype(int)) - aligned_case_ids)
    summary = {
        "status": "passed" if cases == len(epochs) else "failed",
        "provider_id": "dukascopy_supplemental",
        "hour_files": len(files),
        "full_quote_clock_events": total_quotes,
        "sampled_controls": controls,
        "canonical_cases": cases,
        "cases_with_a_preceding_quote": len(aligned_case_ids),
        "case_ids_without_preceding_quote": missing_cases,
        "rows_with_observed_features": observed_features,
        "control_sampling": "one seeded-uniform quote per nonempty provider minute",
        "control_probability": "1 / quotes_in_stratum",
        "seed": SEED,
        "unknown_never_negative": True,
    }
    write_json(output / "opportunity_manifest.json", summary)
    write_json(output / "sampling_design.json", {
        "clock": "all Dukascopy quotes",
        "case_selection": "latest provider quote at or before canonical epoch time, maximum registered delta 1 second",
        "control_selection": "one seeded-uniform quote from every nonempty UTC provider minute",
        "inclusion_probability_column": "control_inclusion_probability",
        "absolute_rate_evaluation": "requires full quote exposure counts and autonomous replay, not sampled controls alone",
    })
    if summary["status"] != "passed":
        raise RuntimeError(f"Risk-set construction failed: {summary}")
    return summary


def audit_sampled_quote_risk_set(output: Path) -> dict[str, Any]:
    """Audit saved risk-set support without changing its registered rules."""

    path = output / "sampled_quote_risk_set.csv"
    frame = pd.read_csv(path)
    decision = pd.to_datetime(frame.decision_time_utc, utc=True, format="mixed")
    maximum = pd.to_datetime(frame.maximum_input_time, utc=True, errors="coerce", format="mixed")
    cases = frame.loc[frame.row_role.eq("case")].copy()
    controls = frame.loc[frame.row_role.eq("control")].copy()
    feature_columns = ["ret_5s", "ret_30s", "range_30s", "realized_vol_30s", "spread_now", "tick_rate_30s"]
    observed = frame.feature_status.eq("observed")
    numeric = frame.loc[observed, feature_columns].to_numpy(dtype=float)
    retained = cases.loc[cases.feature_status.eq("observed"), [
        "epoch_id", "decision_time_utc", "source_quote_time_utc", "feature_status", "case_quote_delta_seconds"
    ]].copy()
    retained["disposition"] = "retained_primary_case_control"
    dropped = cases.loc[~cases.feature_status.eq("observed"), [
        "epoch_id", "decision_time_utc", "source_quote_time_utc", "feature_status", "case_quote_delta_seconds"
    ]].copy()
    dropped["disposition"] = "unevaluable_primary_case_control"
    pd.concat([retained, dropped], ignore_index=True).sort_values("epoch_id").to_csv(
        output / "retained_dropped_audit.csv", index=False
    )
    summary = {
        "status": "passed_partial_support",
        "rows": len(frame),
        "canonical_cases": len(cases),
        "cases_with_observed_features": int(cases.feature_status.eq("observed").sum()),
        "cases_unevaluable": int((~cases.feature_status.eq("observed")).sum()),
        "case_status_counts": cases.feature_status.value_counts().to_dict(),
        "controls": len(controls),
        "controls_with_observed_features": int(controls.feature_status.eq("observed").sum()),
        "control_status_counts": controls.feature_status.value_counts().to_dict(),
        "causality_violations": int((maximum.notna() & (maximum >= decision)).sum()),
        "duplicate_case_epoch_ids": int(cases.epoch_id.duplicated().sum()),
        "invalid_control_probabilities": int(((controls.control_inclusion_probability <= 0) | (controls.control_inclusion_probability > 1)).sum()),
        "nonfinite_observed_feature_cells": int((~np.isfinite(numeric)).sum()),
        "maximum_case_quote_delta_seconds": float(cases.case_quote_delta_seconds.max()),
        "primary_analysis_scope": "299 supported cases and supported sampled controls only; unknown rows are not negatives",
    }
    hard_failures = [
        summary["causality_violations"], summary["duplicate_case_epoch_ids"],
        summary["invalid_control_probabilities"], summary["nonfinite_observed_feature_cells"],
    ]
    if any(hard_failures) or summary["canonical_cases"] != 420:
        summary["status"] = "failed"
    write_json(output / "risk_set_audit.json", summary)
    return summary
