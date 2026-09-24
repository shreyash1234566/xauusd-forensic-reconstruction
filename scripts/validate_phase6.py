"""Independent validation for the Phase 6 A4/STOP-A evidence branch."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"


def main() -> None:
    required = [
        "phase6_baseline_lock.md", "phase6_baseline_lock.json", "phase6_environment_inventory.md", "phase6_tick_recovery_report.md", "phase6_tick_coverage.csv",
        "phase6_order_recovery.md", "phase6_order_opportunity_table.csv", "phase6_journal_analysis.md", "phase6_data_quality.md", "phase6_clock_trigger_analysis.md",
        "phase6_trade_lifecycle_table.csv", "phase6_intrabar_analysis.md", "phase6_hidden_state_analysis.md", "phase6_opportunity_reconstruction.md",
        "phase6_negative_space_analysis.md", "phase6_exit_reconstruction.md", "phase6_sizing_analysis.md", "phase6_direction_analysis.md", "phase6_information_boundary.md", "phase6_status.md", "phase6_validation.json",
    ]
    missing = [name for name in required if not (OUT / name).exists()]
    if missing:
        raise AssertionError(f"Missing Phase 6 artifacts: {missing}")
    lock = json.loads((OUT / "phase6_baseline_lock.json").read_text(encoding="utf-8"))
    canonical = lock["canonical"]
    expected = {"trade_rows": 423, "buy": 214, "sell": 209, "wins": 367, "losses": 56, "net_pnl": 1451.22, "strict_overlap_entries": 3}
    if any(canonical[key] != value for key, value in expected.items()):
        raise AssertionError("Phase 6 baseline lock does not preserve canonical ledger")
    validation = json.loads((OUT / "phase6_validation.json").read_text(encoding="utf-8"))
    if validation["phase6a_decision"] != "A4_NO_NATIVE_ACCOUNT_OR_TERMINAL_EVIDENCE" or validation["phase6b_6c_run"]:
        raise AssertionError("Phase 6 continued beyond a failed native-data gate")
    for name in ["phase6_tick_coverage.csv", "phase6_order_opportunity_table.csv", "phase6_trade_lifecycle_table.csv"]:
        row = pd.read_csv(OUT / name)
        if len(row) != 1 or row.loc[0, "status"] != "DATA_UNAVAILABLE":
            raise AssertionError(f"{name} must explicitly mark unavailable native data")
    status = (OUT / "phase6_status.md").read_text(encoding="utf-8")
    if "LEVEL D — UNIDENTIFIED" not in status or "Did the project move beyond Level D?** No." not in status:
        raise AssertionError("Phase 6 status promoted without native evidence")
    print(json.dumps({"status": "ok", "artifacts": len(required), "decision": validation["phase6a_decision"], "level": validation["identification_level"]}, indent=2))


if __name__ == "__main__":
    main()
