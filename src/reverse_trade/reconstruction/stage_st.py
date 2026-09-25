"""Conditional direction, size, and exit analyses for Stages S-T."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler

from .evidence import build_decision_epochs, load_canonical_records
from .io import write_json


FEATURES = ["hour_utc", "day_of_week", "ret_5s", "ret_30s", "range_30s", "realized_vol_30s", "spread_now", "tick_rate_30s"]


def _cases(risk_set_path: Path) -> pd.DataFrame:
    frame = pd.read_csv(risk_set_path)
    frame = frame.loc[frame.row_role.eq("case") & frame.feature_status.eq("observed")].copy()
    frame["decision_time_utc"] = pd.to_datetime(frame.decision_time_utc, utc=True, format="mixed")
    return frame.sort_values("decision_time_utc").reset_index(drop=True)


def run_stage_s(risk_set_path: Path, splits_path: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    cases = _cases(risk_set_path)
    splits = json.loads(splits_path.read_text(encoding="utf-8"))
    rows = []
    coefficients: dict[str, Any] = {}
    for fold in splits:
        train_end, test_start, test_end = pd.Timestamp(fold["train_end"]), pd.Timestamp(fold["test_start"]), pd.Timestamp(fold["test_end"])
        train = cases.loc[cases.decision_time_utc <= train_end]
        test = cases.loc[cases.decision_time_utc.between(test_start, test_end, inclusive="both")]
        x_train, x_test = train[FEATURES].to_numpy(float), test[FEATURES].to_numpy(float)
        y_train, y_test = train.side.eq("Buy").astype(int).to_numpy(), test.side.eq("Buy").astype(int).to_numpy()
        scaler = StandardScaler().fit(x_train)
        model = LogisticRegression(C=1.0, max_iter=2000).fit(scaler.transform(x_train), y_train)
        p = np.clip(model.predict_proba(scaler.transform(x_test))[:, 1], 1e-15, 1 - 1e-15)
        base_p = float(np.clip(y_train.mean(), 1e-15, 1 - 1e-15))
        ll = float(np.sum(y_test * np.log(p) + (1 - y_test) * np.log(1 - p)))
        base_ll = float(np.sum(y_test * np.log(base_p) + (1 - y_test) * np.log(1 - base_p)))
        accuracy = float(np.mean((p >= 0.5) == y_test))
        base_accuracy = float(max(np.mean(y_test), 1 - np.mean(y_test)))
        rows.append({
            "fold_id": fold["fold_id"], "train_cases": len(train), "test_cases": len(test),
            "direction_accuracy": accuracy, "majority_test_accuracy": base_accuracy,
            "direction_bits_per_trade_vs_train_rate": (ll - base_ll) / (len(test) * np.log(2.0)),
        })
        coefficients[f"fold_{fold['fold_id']}"] = {name: float(value) for name, value in zip(FEATURES, model.coef_[0])}
    scores = pd.DataFrame(rows)
    scores.to_csv(output / "direction_fold_scores.csv", index=False)
    write_json(output / "direction_coefficients.json", coefficients)
    volumes = cases.volume.astype(float)
    volume_table = volumes.value_counts().sort_index().rename_axis("volume").reset_index(name="epochs")
    volume_table["fraction"] = volume_table.epochs / len(cases)
    volume_table.to_csv(output / "volume_distribution.csv", index=False)
    mean_bits = float(scores.direction_bits_per_trade_vs_train_rate.mean())
    summary = {
        "status": "passed_conditional_analysis",
        "supported_entry_epochs": len(cases),
        "buy_epochs": int(cases.side.eq("Buy").sum()), "sell_epochs": int(cases.side.eq("Sell").sum()),
        "mean_outer_direction_bits_per_trade": mean_bits,
        "mean_direction_accuracy": float(scores.direction_accuracy.mean()),
        "mean_majority_test_accuracy": float(scores.majority_test_accuracy.mean()),
        "volume_levels": int(volumes.nunique()), "base_0_01_volume_fraction": float(volumes.eq(0.01).mean()),
        "direction_mechanism_identified": mean_bits > 0,
        "size_mechanism_identified": False,
        "scope": "conditional on an observed supported entry; not autonomous entry recovery",
    }
    write_json(output / "stage_status.json", summary)
    return summary


def run_stage_t(root: Path, risk_set_path: Path, splits_path: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    cases = _cases(risk_set_path)
    records = load_canonical_records(root)
    annotated, _ = build_decision_epochs(records)
    feature_columns = ["epoch_id", *FEATURES]
    analysis = annotated.merge(cases[feature_columns], on="epoch_id", how="inner", validate="many_to_one")
    analysis["holding_seconds"] = (analysis.close_time_utc - analysis.open_time_utc).dt.total_seconds()
    analysis["signed_exit_move"] = np.where(
        analysis.side.eq("Buy"), analysis.exit_exec_price - analysis.recorded_price,
        analysis.recorded_price - analysis.exit_exec_price,
    )
    analysis[["record_id", "epoch_id", "side", "volume", "open_time_utc", "close_time_utc", "holding_seconds", "signed_exit_move", "recorded_pnl"]].to_csv(
        output / "conditional_exit_records.csv", index=False
    )
    time_grid = np.asarray([60, 180, 300, 600, 900, 1800, 3600], dtype=float)
    grid_rows = []
    for seconds in time_grid:
        error = np.abs(analysis.holding_seconds.to_numpy(float) - seconds)
        grid_rows.append({
            "holding_seconds": seconds, "median_absolute_error_seconds": float(np.median(error)),
            "within_1_second": int((error <= 1).sum()), "within_5_seconds": int((error <= 5).sum()),
            "within_60_seconds": int((error <= 60).sum()),
        })
    pd.DataFrame(grid_rows).to_csv(output / "fixed_time_exit_grid.csv", index=False)
    splits = json.loads(splits_path.read_text(encoding="utf-8"))
    fold_rows = []
    model_features = FEATURES + ["side_buy", "volume"]
    analysis["side_buy"] = analysis.side.eq("Buy").astype(float)
    for fold in splits:
        test_start, test_end = pd.Timestamp(fold["test_start"]), pd.Timestamp(fold["test_end"])
        # Outcome must have become available before the test begins.
        train = analysis.loc[analysis.close_time_utc < test_start]
        test = analysis.loc[analysis.open_time_utc.between(test_start, test_end, inclusive="both")]
        x_train, x_test = train[model_features].to_numpy(float), test[model_features].to_numpy(float)
        y_train = np.log1p(train.holding_seconds.to_numpy(float))
        y_test_seconds = test.holding_seconds.to_numpy(float)
        scaler = StandardScaler().fit(x_train)
        model = Ridge(alpha=10.0).fit(scaler.transform(x_train), y_train)
        predicted = np.maximum(0.0, np.expm1(model.predict(scaler.transform(x_test))))
        baseline = np.full(len(test), float(np.median(train.holding_seconds)))
        fold_rows.append({
            "fold_id": fold["fold_id"], "train_records": len(train), "test_records": len(test),
            "model_mae_seconds": float(np.mean(np.abs(predicted - y_test_seconds))),
            "median_baseline_mae_seconds": float(np.mean(np.abs(baseline - y_test_seconds))),
        })
    fold_scores = pd.DataFrame(fold_rows)
    fold_scores.to_csv(output / "holding_duration_fold_scores.csv", index=False)
    improvement = float((fold_scores.median_baseline_mae_seconds - fold_scores.model_mae_seconds).mean())
    summary = {
        "status": "passed_conditional_analysis",
        "supported_records": len(analysis), "supported_epochs": int(analysis.epoch_id.nunique()),
        "median_holding_seconds": float(analysis.holding_seconds.median()),
        "fixed_time_exact_matches_within_1s_max": int(pd.DataFrame(grid_rows).within_1_second.max()),
        "mean_duration_mae_improvement_seconds": improvement,
        "exit_mechanism_identified": False,
        "reason": "One realized exit per trade does not identify time, price, trailing, discretionary, or broker-trigger alternatives; public path replay is still required.",
        "scope": "conditional diagnostic using supported entry epochs and Phase7C-derived exit quotes",
    }
    write_json(output / "stage_status.json", summary)
    return summary

