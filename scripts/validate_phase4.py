"""Independent checks for the data-limited Phase 4 conclusion."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from phase4_data_recovery import classify_market_header


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"


def main() -> None:
    reports = [
        "phase4_data_recovery_inventory.md", "phase4_tick_execution_analysis.md", "phase4_order_deal_lifecycle.md",
        "phase4_clock_trigger_analysis.md", "phase4_opportunity_reconstruction.md", "phase4_state_machine_analysis.md",
        "phase4_exit_reconstruction.md", "phase4_sizing_analysis.md", "phase4_direction_analysis.md",
        "phase4_nearmiss_analysis.md", "phase4_data_gap_certificate.md", "phase4_status.md",
    ]
    tables = [
        "phase4_trade_tick_table.csv", "phase4_opportunity_table.csv", "phase4_nearmiss_table.csv",
        "phase4_state_features.csv", "phase4_candidate_rules.csv", "phase4_replication_results.csv",
    ]
    missing = [name for name in [*reports, *tables, "phase4_validation.json"] if not (OUT / name).exists()]
    if missing:
        raise AssertionError(f"Missing Phase 4 artifacts: {missing}")
    for name in tables:
        table = pd.read_csv(OUT / name)
        if len(table) != 1 or table.loc[0, "analysis_status"] != "NOT_IDENTIFIABLE":
            raise AssertionError(f"{name} must contain its single, explicit data-limited status row")
    status = (OUT / "phase4_status.md").read_text(encoding="utf-8")
    if "LEVEL D — UNIDENTIFIED" not in status or "1. **Was higher-resolution data recovered?** No." not in status:
        raise AssertionError("Phase 4 status does not retain its evidence-limited conclusion")
    inventory = (OUT / "phase4_data_recovery_inventory.md").read_text(encoding="utf-8")
    if "ABSENT" not in inventory or "Dukascopy bid-only M1 proxy" not in inventory:
        raise AssertionError("Recovery inventory lacks the decisive absence/source evidence")
    if classify_market_header(["timestamp", "open", "high", "low", "close", "volume"]) != "ohlc_bar_only":
        raise AssertionError("OHLC-only source was misclassified as a quote source")
    metrics = json.loads((OUT / "phase4_validation.json").read_text(encoding="utf-8"))
    if metrics["branch"] != "C_DATA_LIMITED_NO_TRANSACTION_DATA_RECOVERED" or metrics["identification_level"] != "D — UNIDENTIFIED":
        raise AssertionError("Phase 4 validation level or branch was changed")
    print(json.dumps({"status": "ok", "reports": len(reports), "tables": len(tables), "branch": metrics["branch"]}, indent=2))


if __name__ == "__main__":
    main()
