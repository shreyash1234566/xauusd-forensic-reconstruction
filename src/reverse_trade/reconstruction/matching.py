"""Fixed one-to-one entry matching and transparent reconstruction counts."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment


@dataclass(frozen=True)
class MatchConfig:
    entry_tolerance: pd.Timedelta = pd.Timedelta(seconds=120)
    require_side: bool = False
    require_volume: bool = False
    volume_tolerance: float = 1e-12


def _time_column(frame: pd.DataFrame, preferred: str) -> str:
    if preferred in frame.columns:
        return preferred
    raise ValueError(f"Missing required time column: {preferred}")


def match_entries(observed: pd.DataFrame, predicted: pd.DataFrame, config: MatchConfig = MatchConfig()) -> tuple[pd.DataFrame, dict[str, float | int]]:
    """Maximum-cardinality, minimum-time-error match without greedy ambiguity."""

    observed_time = _time_column(observed, "decision_time_utc")
    predicted_time = "open_time_utc" if "open_time_utc" in predicted.columns else _time_column(predicted, "decision_time_utc")
    obs = observed.copy().reset_index(names="observed_index")
    pred = predicted.copy().reset_index(names="predicted_index")
    obs[observed_time] = pd.to_datetime(obs[observed_time], utc=True)
    pred[predicted_time] = pd.to_datetime(pred[predicted_time], utc=True)
    big = 1e18
    cost = np.full((len(obs), len(pred)), big, dtype=float)
    for i, left in obs.iterrows():
        for j, right in pred.iterrows():
            seconds = abs((right[predicted_time] - left[observed_time]).total_seconds())
            compatible = seconds <= config.entry_tolerance.total_seconds()
            if compatible and config.require_side and "side" in obs and "side" in pred:
                compatible = left.side == right.side
            if compatible and config.require_volume and "volume" in obs and "volume" in pred:
                compatible = abs(float(left.volume) - float(right.volume)) <= config.volume_tolerance
            if compatible:
                cost[i, j] = seconds
    rows: list[dict[str, object]] = []
    if len(obs) and len(pred):
        left_indices, right_indices = linear_sum_assignment(cost)
        paired = {int(i): int(j) for i, j in zip(left_indices, right_indices) if cost[i, j] < big}
    else:
        paired = {}
    used_pred = set(paired.values())
    for i, left in obs.iterrows():
        base = {"observed_index": int(left.observed_index), "status": "fn"}
        if i in paired:
            j = paired[i]
            right = pred.iloc[j]
            base.update({
                "status": "tp", "predicted_index": int(right.predicted_index),
                "timing_error_seconds": float(cost[i, j]),
                "direction_match": bool(left.side == right.side) if "side" in obs and "side" in pred else None,
                "volume_error": abs(float(left.volume) - float(right.volume)) if "volume" in obs and "volume" in pred else None,
            })
        rows.append(base)
    for j, right in pred.iterrows():
        if j not in used_pred:
            rows.append({"observed_index": None, "predicted_index": int(right.predicted_index), "status": "fp"})
    if rows:
        table = pd.DataFrame(rows)
        tp = int((table["status"] == "tp").sum())
        fn = int((table["status"] == "fn").sum())
        fp = int((table["status"] == "fp").sum())
    else:
        table = pd.DataFrame(columns=["observed_index", "predicted_index", "status", "timing_error_seconds", "direction_match", "volume_error"])
        tp = fn = fp = 0
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    summary: dict[str, float | int] = {
        "tp": tp, "fp": fp, "fn": fn, "observed": len(obs), "predicted": len(pred),
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }
    return table, summary
