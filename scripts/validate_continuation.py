"""Validate persisted continuation artifacts and leakage controls."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"


def main() -> None:
    required = [
        "claude_evidence_ledger.md",
        "algorithm_claim_audit.md",
        "sizing_state_analysis.md",
        "entry_reconstruction.md",
        "exit_reconstruction.md",
        "candidate_rule_comparison.csv",
        "entry_match_table.csv",
        "exit_match_table.csv",
        "walk_forward_results.csv",
        "algorithm_identification_status.md",
    ]
    missing = [name for name in required if not (OUT / name).exists()]
    if missing:
        raise AssertionError(f"Missing required artifacts: {missing}")

    metrics = json.loads((OUT / "continuation_metrics.json").read_text(encoding="utf-8"))
    counts = {
        "candidate_event_rows": int(metrics["candidate_event_rows"]),
        "entry_match_rows": len(pd.read_csv(OUT / "entry_match_table.csv")),
        "exit_match_rows": len(pd.read_csv(OUT / "exit_match_table.csv")),
        "near_miss_rows": len(pd.read_csv(OUT / "near_miss_events.csv")),
        "walk_forward_rows": len(pd.read_csv(OUT / "walk_forward_results.csv")),
        "candidate_model_rows": len(pd.read_csv(OUT / "candidate_rule_comparison.csv")),
    }
    expected = {
        "candidate_event_rows": 346_696,
        "entry_match_rows": 423,
        "exit_match_rows": 423,
        "near_miss_rows": 1_260,
        "walk_forward_rows": 45,
        "candidate_model_rows": 9,
    }
    if counts != expected:
        raise AssertionError(f"Artifact row counts differ: {counts} != {expected}")

    # Persisted candidate rows must contain the prior M1 close, never the close
    # from the minute in which the entry label is defined.
    candidate = pd.read_csv(
        OUT / "candidate_event_table.csv.gz", usecols=["timestamp", "m1_close"]
    )
    candidate["timestamp"] = pd.to_datetime(candidate["timestamp"])
    bars = pd.read_csv(
        ROOT / "data" / "market" / "normalized" / "xauusd_m1.csv",
        usecols=["timestamp", "close"],
    )
    bars["timestamp"] = pd.to_datetime(bars["timestamp"])
    bars = bars.sort_values("timestamp")
    bars["expected_prior_close"] = bars["close"].shift(1)
    check = candidate.merge(
        bars[["timestamp", "expected_prior_close"]], on="timestamp", how="left", validate="one_to_one"
    )
    finite = check[["m1_close", "expected_prior_close"]].dropna()
    # Features are persisted from float32, whose quantization near XAUUSD 4,000
    # is about 0.00024; allow only that representation error.
    lagged_close_ok = bool(
        np.allclose(finite["m1_close"], finite["expected_prior_close"], rtol=0, atol=3e-4)
    )
    if not lagged_close_ok:
        raise AssertionError("Persisted m1_close is not the immediately prior completed-bar close")

    audit = (OUT / "algorithm_claim_audit.md").read_text(encoding="utf-8")
    status = (OUT / "algorithm_identification_status.md").read_text(encoding="utf-8")
    if "LEVEL D — UNIDENTIFIED" not in status:
        raise AssertionError("Final identification level is not explicitly Level D")
    if "price = entry price | PLAUSIBLE HYPOTHESIS" not in audit:
        raise AssertionError("Price semantics are not conservatively graded")

    result = {
        "status": "ok",
        "required_artifacts": len(required),
        "row_counts": counts,
        "lagged_m1_close_rows_checked": len(finite),
        "lagged_m1_close_ok": lagged_close_ok,
        "identification_level": "D — UNIDENTIFIED",
    }
    (OUT / "continuation_validation.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
