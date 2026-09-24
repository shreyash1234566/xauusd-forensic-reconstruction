"""Independent validation of Phase 3 artifacts and completed-bar safeguards."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"


def main() -> None:
    required = [
        "phase3_data_inventory.md", "phase3_clock_event_analysis.md", "phase3_state_machine_analysis.md",
        "phase3_cooldown_analysis.md", "phase3_opportunity_analysis.md", "phase3_intrabar_analysis.md",
        "phase3_nearmiss_analysis.md", "phase3_direction_analysis.md", "phase3_event_sequence_analysis.md",
        "phase3_hidden_eligibility.md", "phase3_status.md", "phase3_nearmiss_table.csv", "phase3_event_windows.csv",
        "phase3_state_features.csv", "phase3_sparse_rules.csv", "phase3_replication_results.csv", "phase3_validation.json",
    ]
    missing = [name for name in required if not (OUT / name).exists()]
    if missing:
        raise AssertionError(f"Missing Phase 3 artifacts: {missing}")
    near = pd.read_csv(OUT / "phase3_nearmiss_table.csv")
    state = pd.read_csv(OUT / "phase3_state_features.csv", usecols=["timestamp", "entry", "eligible_observed_capacity", "event_prebar_close"])
    results = pd.read_csv(OUT / "phase3_replication_results.csv")
    if len(near) != 423 or near.trade_ticket.nunique() != 423:
        raise AssertionError("Phase 3 near-miss coverage is not one row per observed trade")
    if len(state) != 346_696 or int(state.entry.sum()) != 420:
        raise AssertionError("Phase 3 state-panel row or entry-bar count changed")
    if state.loc[state.entry.eq(1), "eligible_observed_capacity"].eq(0).any():
        raise AssertionError("Observed capacity envelope excludes a known entry")
    if len(results[results.evaluation.eq("oos_aggregate")]) != 8:
        raise AssertionError("Expected six clock and two sparse aggregate hypotheses")
    state.timestamp = pd.to_datetime(state.timestamp)
    bars = pd.read_csv(ROOT / "data" / "market" / "normalized" / "xauusd_m1.csv", usecols=["timestamp", "close"])
    bars.timestamp = pd.to_datetime(bars.timestamp)
    bars["expected_completed_close"] = bars.close.shift(1)
    checked = state.merge(bars[["timestamp", "expected_completed_close"]], on="timestamp", how="left", validate="one_to_one").dropna()
    if not np.allclose(checked.event_prebar_close, checked.expected_completed_close, rtol=0, atol=3e-4):
        raise AssertionError("Phase 3 event feature uses a non-completed M1 close")
    sparse = pd.read_csv(OUT / "phase3_sparse_rules.csv")
    rule_text = " ".join(sparse.rule_or_feature.fillna("").astype(str)).lower()
    forbidden = [word for word in ["pnl", "close_time", "exit_price", "mfe", "mae"] if word in rule_text]
    if forbidden:
        raise AssertionError(f"Outcome leakage in Phase 3 sparse rules: {forbidden}")
    status = (OUT / "phase3_status.md").read_text(encoding="utf-8")
    if "LEVEL D — UNIDENTIFIED" not in status:
        raise AssertionError("Phase 3 status was promoted without replication evidence")
    outcome = {
        "status": "ok", "required_artifacts": len(required), "nearmiss_rows": len(near),
        "state_rows": len(state), "aggregate_hypotheses": 8, "completed_m1_rows_checked": len(checked),
        "forbidden_outcome_features": forbidden, "identification_level": "D — UNIDENTIFIED",
    }
    metrics = json.loads((OUT / "phase3_validation.json").read_text(encoding="utf-8"))
    metrics["independent_validation"] = outcome
    (OUT / "phase3_validation.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(outcome, indent=2))


if __name__ == "__main__":
    main()
