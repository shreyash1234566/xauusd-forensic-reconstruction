"""Weighted chronological event-model baselines for the sampled quote risk set."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .event_models import calculate_bits_per_event, log_loss_to_log_likelihood
from .io import write_json


MODEL_FEATURES = {
    "B0_constant": [],
    "B1_calendar": ["hour_sin", "hour_cos", "dow_sin", "dow_cos"],
    "B2_tick": ["ret_5s", "ret_30s", "range_30s", "realized_vol_30s", "spread_now", "tick_rate_30s"],
    "B3_calendar_tick": ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "ret_5s", "ret_30s", "range_30s", "realized_vol_30s", "spread_now", "tick_rate_30s"],
    "B4_fixed_interactions": [
        "hour_sin", "hour_cos", "dow_sin", "dow_cos", "ret_5s", "ret_30s", "abs_ret_30s",
        "range_30s", "realized_vol_30s", "spread_now", "tick_rate_30s", "ret_x_vol", "spread_x_rate",
    ],
    "B5_history_augmented": [
        "hour_sin", "hour_cos", "dow_sin", "dow_cos", "ret_5s", "ret_30s", "range_30s",
        "realized_vol_30s", "spread_now", "tick_rate_30s", "log_seconds_since_prior_event",
    ],
}


def _prepare(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = pd.read_csv(path)
    frame["decision_time_utc"] = pd.to_datetime(frame.decision_time_utc, utc=True, format="mixed")
    frame["source_quote_time_utc"] = pd.to_datetime(frame.source_quote_time_utc, utc=True, errors="coerce", format="mixed")
    frame = frame.loc[frame.feature_status.eq("observed")].copy()
    case_quote_times = set(frame.loc[frame.row_role.eq("case"), "source_quote_time_utc"].dropna())
    collision = frame.row_role.eq("control") & frame.source_quote_time_utc.isin(case_quote_times)
    collision_count = int(collision.sum())
    frame = frame.loc[~collision].copy()
    frame["is_trade_entry"] = frame.row_role.eq("case").astype(int)
    frame["population_weight"] = np.where(
        frame.is_trade_entry.eq(1), 1.0, 1.0 / frame.control_inclusion_probability.astype(float)
    )
    hour = frame.hour_utc.astype(float)
    dow = frame.day_of_week.astype(float)
    frame["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    frame["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    frame["dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
    frame["dow_cos"] = np.cos(2 * np.pi * dow / 7.0)
    frame["abs_ret_30s"] = frame.ret_30s.abs()
    frame["ret_x_vol"] = frame.ret_30s * frame.realized_vol_30s
    frame["spread_x_rate"] = frame.spread_now * frame.tick_rate_30s
    event_times = np.sort(frame.loc[frame.is_trade_entry.eq(1), "decision_time_utc"].astype("int64").to_numpy())
    current = frame.decision_time_utc.astype("int64").to_numpy()
    prior_index = np.searchsorted(event_times, current, side="left") - 1
    seconds = np.full(len(frame), 365.0 * 24 * 3600.0)
    valid = prior_index >= 0
    seconds[valid] = (current[valid] - event_times[prior_index[valid]]) / 1e9
    frame["log_seconds_since_prior_event"] = np.log1p(np.maximum(seconds, 0.0))
    frame = frame.sort_values("decision_time_utc", kind="mergesort").reset_index(drop=True)
    return frame, {"case_control_quote_collisions_removed": collision_count}


def _weighted_ll(y: np.ndarray, probability: np.ndarray, weight: np.ndarray) -> float:
    p = np.clip(probability, 1e-15, 1 - 1e-15)
    return float(np.sum(weight * (y * np.log(p) + (1 - y) * np.log(1 - p))))


def _fit_predict(train: pd.DataFrame, test: pd.DataFrame, columns: list[str]) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    y_train = train.is_trade_entry.to_numpy(float)
    weight = train.population_weight.to_numpy(float)
    fit_weight = weight / np.mean(weight)
    if not columns:
        probability = float(np.clip(np.sum(weight * y_train) / np.sum(weight), 1e-15, 1 - 1e-15))
        return np.full(len(train), probability), np.full(len(test), probability), {"intercept_probability": probability}
    x_train = train[columns].to_numpy(float)
    x_test = test[columns].to_numpy(float)
    if not np.isfinite(x_train).all() or not np.isfinite(x_test).all():
        raise ValueError("Stage O received nonfinite supported features")
    scaler = StandardScaler().fit(x_train, sample_weight=fit_weight)
    model = LogisticRegression(C=1.0, max_iter=2000, solver="lbfgs")
    model.fit(scaler.transform(x_train), y_train, sample_weight=fit_weight)
    train_p = model.predict_proba(scaler.transform(x_train))[:, 1]
    test_p = model.predict_proba(scaler.transform(x_test))[:, 1]
    parameters = {
        "intercept": float(model.intercept_[0]),
        "coefficients_standardized": {name: float(value) for name, value in zip(columns, model.coef_[0])},
        "scaler_mean": {name: float(value) for name, value in zip(columns, scaler.mean_)},
        "scaler_scale": {name: float(value) for name, value in zip(columns, scaler.scale_)},
    }
    return train_p, test_p, parameters


def run_stage_o(risk_set_path: Path, splits_path: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    frame, audit = _prepare(risk_set_path)
    splits = json.loads(splits_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    parameters: dict[str, Any] = {}
    for fold in splits:
        train_end = pd.Timestamp(fold["train_end"])
        test_start = pd.Timestamp(fold["test_start"])
        test_end = pd.Timestamp(fold["test_end"])
        train = frame.loc[frame.decision_time_utc <= train_end].copy()
        test = frame.loc[frame.decision_time_utc.between(test_start, test_end, inclusive="both")].copy()
        if train.is_trade_entry.sum() < 20 or test.is_trade_entry.sum() < 1:
            raise ValueError(f"Fold {fold['fold_id']} lacks supported events: train={train.is_trade_entry.sum()} test={test.is_trade_entry.sum()}")
        fold_predictions: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for name, columns in MODEL_FEATURES.items():
            train_p, test_p, model_parameters = _fit_predict(train, test, columns)
            fold_predictions[name] = (train_p, test_p)
            parameters[f"fold_{fold['fold_id']}:{name}"] = model_parameters
        b0_train, b0_test = fold_predictions["B0_constant"]
        train_b0_ll = _weighted_ll(train.is_trade_entry.to_numpy(float), b0_train, train.population_weight.to_numpy(float))
        test_b0_ll = _weighted_ll(test.is_trade_entry.to_numpy(float), b0_test, test.population_weight.to_numpy(float))
        for name, (train_p, test_p) in fold_predictions.items():
            train_ll = _weighted_ll(train.is_trade_entry.to_numpy(float), train_p, train.population_weight.to_numpy(float))
            test_ll = _weighted_ll(test.is_trade_entry.to_numpy(float), test_p, test.population_weight.to_numpy(float))
            rows.append({
                "fold_id": fold["fold_id"], "model": name,
                "train_rows": len(train), "test_rows": len(test),
                "train_events": int(train.is_trade_entry.sum()), "test_events": int(test.is_trade_entry.sum()),
                "train_population_weight": float(train.population_weight.sum()), "test_population_weight": float(test.population_weight.sum()),
                "train_log_likelihood": train_ll, "test_log_likelihood": test_ll,
                "train_bits_per_event_vs_B0": calculate_bits_per_event(train_ll, train_b0_ll, int(train.is_trade_entry.sum())),
                "test_bits_per_event_vs_B0": calculate_bits_per_event(test_ll, test_b0_ll, int(test.is_trade_entry.sum())),
            })
    scores = pd.DataFrame(rows)
    scores.to_csv(output / "fold_model_scores.csv", index=False)
    aggregate = scores.groupby("model", as_index=False).agg(
        folds=("fold_id", "count"),
        test_events=("test_events", "sum"),
        mean_test_bits_per_event=("test_bits_per_event_vs_B0", "mean"),
        median_test_bits_per_event=("test_bits_per_event_vs_B0", "median"),
        minimum_test_bits_per_event=("test_bits_per_event_vs_B0", "min"),
    ).sort_values("mean_test_bits_per_event", ascending=False)
    aggregate.to_csv(output / "aggregate_model_scores.csv", index=False)
    write_json(output / "fold_model_parameters.json", parameters)
    finite = bool(np.isfinite(scores[["train_log_likelihood", "test_log_likelihood", "test_bits_per_event_vs_B0"]].to_numpy()).all())
    summary = {
        "status": "passed" if finite and len(scores) == len(splits) * len(MODEL_FEATURES) else "failed",
        "supported_rows": len(frame),
        "supported_cases": int(frame.is_trade_entry.sum()),
        "supported_controls": int(frame.is_trade_entry.eq(0).sum()),
        "population_weight_total": float(frame.population_weight.sum()),
        "folds": len(splits), "models": len(MODEL_FEATURES),
        "best_mean_test_model": str(aggregate.iloc[0].model),
        "best_mean_test_bits_per_event_vs_B0": float(aggregate.iloc[0].mean_test_bits_per_event),
        "sampling_correction": "Horvitz-Thompson control weight = 1 / inclusion probability; cases weight 1",
        "unknown_rows_excluded_not_negative": True,
        **audit,
    }
    write_json(output / "stage_status.json", summary)
    return summary

