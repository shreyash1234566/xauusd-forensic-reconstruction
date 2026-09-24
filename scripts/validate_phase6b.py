"""Independent checks for the waiting native-artifact ingestion branch."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"


def main() -> None:
    required = [
        "phase6b_ingestion_schema.md", "phase6b_ingestion_validation.json", "phase6b_tick_quality.csv", "phase6b_order_table.csv",
        "phase6b_deal_table.csv", "phase6b_position_table.csv", "phase6b_strategy_opportunity_table.csv", "phase6b_execution_alignment.csv",
        "phase6b_lifecycle_table.csv", "phase6b_journal_analysis.md", "phase6b_data_quality.md", "phase6b_status.md",
    ]
    missing = [name for name in required if not (OUT / name).exists()]
    if missing:
        raise AssertionError(f"Missing Phase 6B artifacts: {missing}")
    validation = json.loads((OUT / "phase6b_ingestion_validation.json").read_text(encoding="utf-8"))
    if validation["status"] != "WAITING_FOR_NATIVE_ARTIFACTS" or validation["artifacts_discovered"] != 0 or validation["phase6c_started"]:
        raise AssertionError("Phase 6B waiting branch misreported artifact availability or started 6C")
    for filename in ["phase6b_tick_quality.csv", "phase6b_order_table.csv", "phase6b_deal_table.csv", "phase6b_position_table.csv", "phase6b_strategy_opportunity_table.csv", "phase6b_execution_alignment.csv", "phase6b_lifecycle_table.csv"]:
        table = pd.read_csv(OUT / filename)
        if len(table) != 1 or table.loc[0, "status"] != "DATA_UNAVAILABLE":
            raise AssertionError(f"{filename} must explicitly retain its unavailable-data status")
    print(json.dumps({"status": "ok", "artifacts": len(required), "ingestion_status": validation["status"]}, indent=2))


if __name__ == "__main__":
    main()
