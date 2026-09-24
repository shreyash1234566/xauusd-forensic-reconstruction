"""Independent structural validation for Phase 2 persisted artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"


def main() -> None:
    required = [
        "event_nearmiss_table.csv", "event_nearmiss_analysis.md", "event_sequence_analysis.md",
        "state_machine_analysis.md", "clock_event_analysis.md", "direction_event_analysis.md",
        "microstructure_analysis.md", "sparse_event_rules.csv", "event_replication_results.csv",
        "phase2_validation.json", "phase2_status.md",
    ]
    missing = [name for name in required if not (OUT / name).exists()]
    if missing:
        raise AssertionError(f"Missing Phase 2 artifacts: {missing}")
    near = pd.read_csv(OUT / "event_nearmiss_table.csv")
    controls = pd.read_csv(OUT / "event_matched_controls.csv")
    results = pd.read_csv(OUT / "event_replication_results.csv")
    clock = pd.read_csv(OUT / "clock_event_results.csv")
    if len(near) != 423 or near["ticket"].nunique() != 423:
        raise AssertionError("Near-miss table does not retain one row for every observed trade")
    if len(controls) < 800 or controls["ticket"].nunique() < 420:
        raise AssertionError("Matched-control coverage is unexpectedly incomplete")
    if len(results[results["evaluation"].eq("oos_aggregate")]) != 3:
        raise AssertionError("Expected three aggregate sparse-event model results")
    if clock["matched_bh_q"].isna().any():
        raise AssertionError("Clock boundary analysis lacks matched-control adjustment")

    event_panel = pd.read_csv(OUT / "phase2_event_panel.csv.gz", usecols=["timestamp", "event_prebar_close"])
    event_panel["timestamp"] = pd.to_datetime(event_panel["timestamp"])
    bars = pd.read_csv(ROOT / "data" / "market" / "normalized" / "xauusd_m1.csv", usecols=["timestamp", "close"])
    bars["timestamp"] = pd.to_datetime(bars["timestamp"])
    bars["expected_completed_close"] = bars["close"].shift(1)
    joined = event_panel.merge(bars[["timestamp", "expected_completed_close"]], on="timestamp", how="left", validate="one_to_one").dropna()
    if not np.allclose(joined["event_prebar_close"], joined["expected_completed_close"], rtol=0, atol=3e-4):
        raise AssertionError("Phase 2 event bar is not lagged to a completed M1 bar")

    sparse = pd.read_csv(OUT / "sparse_event_rules.csv")
    forbidden = ["pnl", "close_time", "exit_price", "mfe", "mae"]
    feature_text = " ".join(sparse["rule_or_feature"].fillna("").astype(str)).lower()
    present_forbidden = [word for word in forbidden if word in feature_text]
    if present_forbidden:
        raise AssertionError(f"Outcome-derived entry feature leaked into sparse model: {present_forbidden}")
    status = (OUT / "phase2_status.md").read_text(encoding="utf-8")
    if "LEVEL D — UNIDENTIFIED" not in status:
        raise AssertionError("Phase 2 status is not conservatively retained at Level D")

    result = {
        "status": "ok", "required_artifacts": len(required), "nearmiss_rows": len(near),
        "matched_control_rows": len(controls), "aggregate_models": 3,
        "lagged_completed_m1_rows_checked": len(joined), "forbidden_outcome_features": present_forbidden,
        "identification_level": "D — UNIDENTIFIED",
    }
    metrics = json.loads((OUT / "phase2_validation.json").read_text(encoding="utf-8"))
    metrics["independent_validation"] = result
    (OUT / "phase2_validation.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
