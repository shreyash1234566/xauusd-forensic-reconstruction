"""Independent checks for Phase 5 observable-space artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from phase5_observable_reconstruction import completed_features


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"


def main() -> None:
    reports = [
        "phase5_canonical_recheck.md", "phase5_feature_dictionary.md", "phase5_negative_space_analysis.md", "phase5_baseline_analysis.md",
        "phase5_feature_ablation.md", "phase5_symbolic_regression.md", "phase5_event_sequence_analysis.md", "phase5_direction_analysis.md",
        "phase5_sizing_analysis.md", "phase5_exit_analysis.md", "phase5_regime_stability.md", "phase5_information_boundary.md", "phase5_status.md",
    ]
    data = ["phase5_canonical_statistics.json", "phase5_feature_table.csv.gz", "phase5_negative_space_table.csv.gz", "phase5_symbolic_candidates.csv", "phase5_replication_results.csv", "phase5_validation.json"]
    missing = [name for name in [*reports, *data] if not (OUT / name).exists()]
    if missing:
        raise AssertionError(f"Missing Phase 5 artifacts: {missing}")
    canonical = json.loads((OUT / "phase5_canonical_statistics.json").read_text(encoding="utf-8"))
    expected = {"trade_rows": 423, "buy": 214, "sell": 209, "profitable": 367, "losing": 56, "total_pnl": 1451.22, "overlapping_entries": 3}
    if any(canonical[key] != value for key, value in expected.items()):
        raise AssertionError("Canonical raw-ledger statistics changed")
    feature = pd.read_csv(OUT / "phase5_feature_table.csv.gz", nrows=20)
    if feature.entry.sum() < 0 or "m1_return_1" not in feature or "seconds_since_last_entry" not in feature:
        raise AssertionError("Feature table is missing its observable families")
    negative = pd.read_csv(OUT / "phase5_negative_space_table.csv.gz")
    if negative.ticket.nunique() != 423 or not negative.control_set.str.startswith(("A_", "B_", "C_", "D_", "E_", "F_")).all():
        raise AssertionError("Negative-space controls do not cover each canonical ticket")
    candidates = pd.read_csv(OUT / "phase5_symbolic_candidates.csv")
    if len(candidates) != 8 or "matched_qvalue" not in candidates:
        raise AssertionError("Symbolic family or correction record changed")
    validation = json.loads((OUT / "phase5_validation.json").read_text(encoding="utf-8"))
    if validation["identification_level"] != "D — UNIDENTIFIED" or validation["symbolic_accepted"] != 0:
        raise AssertionError("Unsupported Phase 5 identification promotion")
    print(json.dumps({"status": "ok", "feature_rows": validation["candidate_minutes"], "negative_rows": len(negative), "level": validation["identification_level"]}, indent=2))


if __name__ == "__main__":
    main()
