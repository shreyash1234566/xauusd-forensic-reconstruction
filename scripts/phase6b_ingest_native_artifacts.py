"""Phase 6B ingestion gate.  It does not modify native source artifacts."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from native_artifact_ingestion import discover_artifacts, inspect_artifact


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"
INCOMING = ROOT / "data" / "native" / "incoming"
PHASE6 = OUT / "phase6_validation.json"


def write_status_csv(name: str, scope: str, status: str, reason: str) -> None:
    row = {"artifact": name, "scope": scope, "status": status, "reason": reason}
    with (OUT / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def markdown_table(rows: list[dict[str, object]], columns: list[str]) -> str:
    if not rows:
        return "No artifacts discovered."
    result = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        result.append("| " + " | ".join(str(row.get(column, "")).replace("|", "/") for column in columns) + " |")
    return "\n".join(result)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    INCOMING.mkdir(parents=True, exist_ok=True)
    phase6 = json.loads(PHASE6.read_text(encoding="utf-8"))
    if not phase6["baseline_locked"] or phase6["canonical"]["trade_rows"] != 423:
        raise RuntimeError("Phase 6 canonical baseline is not locked")
    inspected = [inspect_artifact(path) for path in discover_artifacts(INCOMING)]
    manifest = [
        {"path": item.path, "extension": item.extension, "size_bytes": item.size_bytes, "sha256": item.sha256, "encoding": item.encoding or "BINARY_OR_UNDETERMINED", "delimiter": repr(item.delimiter) if item.delimiter else "NOT_APPLICABLE", "columns": ", ".join(item.columns) or "NOT_DETERMINED", "role": item.role}
        for item in inspected
    ]
    status = "WAITING_FOR_NATIVE_ARTIFACTS" if not inspected else "NATIVE_ARTIFACTS_DISCOVERED_PENDING_GATE"
    schema = """# Phase 6B native-artifact ingestion schema

## Intake location

Place copies of original artifacts in `data/native/incoming/`. The pipeline reads them in place, computes SHA-256, and never overwrites, renames, de-duplicates, or normalizes the raw sources.

## Supported sources

| Source | Accepted formats | Minimum evidence | Important non-assumption |
| --- | --- | --- | --- |
| Tick/quote export | CSV, TSV, Parquet | timestamp plus Bid and Ask for quote-side reachability | `Price` alone is not assumed to be Bid, Ask, Last or fill price. |
| Orders | CSV, TSV, HTML report | order ticket, state/type, time, symbol, volume | order ID is not assumed to equal deal ID. |
| Deals | CSV, TSV, HTML report | deal ticket, order/position relation where present, time, price, side | one order is not assumed to create one deal. |
| Positions | CSV, TSV, HTML report | position ID, direction, volume, open/close timing where present | positions are not collapsed into ledger rows before linkage. |
| Journal/Experts logs | TXT, LOG, CSV, HTML | documented timestamps/event messages | logs are not assumed to expose EA source or full internal state. |

## Validation protocol

For every artifact: record source path, SHA-256, size, encoding, delimiter, header, missing-value profile, duplicate policy, timestamp convention/timezone evidence, symbol evidence, and conservative role classification. Field meaning is accepted only when supplied documentation or native export headers establish it. Ambiguities remain `UNKNOWN_SCHEMA`.

## Acceptance gates before Phase 6C

A provenance; B XAUUSD.f/equivalence; C timestamp coverage; D substantial entry alignment; E Bid/Ask execution reachability; F order/deal/position linkage. Failure at any gate is recorded and stops trigger reconstruction.
"""
    (OUT / "phase6b_ingestion_schema.md").write_text(schema, encoding="utf-8")
    (OUT / "phase6b_artifact_manifest.md").write_text(
        "# Phase 6B artifact manifest\n\n" + markdown_table(manifest, ["path", "extension", "size_bytes", "sha256", "encoding", "delimiter", "columns", "role"]) + "\n",
        encoding="utf-8",
    )
    reason = "No native artifacts were supplied to data/native/incoming/. Phase 6C is intentionally not started." if not inspected else "Artifacts found; schema-level inspection completed, but quality/linkage gates still require validated field semantics."
    for name, scope in [
        ("phase6b_tick_quality.csv", "native tick quality and entry/exit coverage"),
        ("phase6b_order_table.csv", "native order records"), ("phase6b_deal_table.csv", "native deal records"),
        ("phase6b_position_table.csv", "native position records"), ("phase6b_strategy_opportunity_table.csv", "non-executed strategy opportunities"),
        ("phase6b_execution_alignment.csv", "Bid/Ask execution reachability"), ("phase6b_lifecycle_table.csv", "order-to-deal-to-position linkage"),
    ]:
        write_status_csv(name, scope, "DATA_UNAVAILABLE" if not inspected else "PENDING_QUALITY_GATE", reason)
    (OUT / "phase6b_journal_analysis.md").write_text(
        "# Phase 6B journal analysis\n\n"
        + ("**DATA_UNAVAILABLE.** No Journal/Experts/terminal log artifact was supplied.\n" if not inspected else "Artifacts are present but no journal semantic extraction occurs until source role and timestamp semantics pass validation.\n"),
        encoding="utf-8",
    )
    (OUT / "phase6b_data_quality.md").write_text(
        "# Phase 6B data quality\n\n"
        f"**Status: {status}.** {reason}\n\n"
        "No native timestamp, Bid, Ask, spread, execution price, order/deal/position relationship, Magic ID, comment, SL/TP, modification or pending-order fact was inferred from Phase 1–6A data.\n",
        encoding="utf-8",
    )
    (OUT / "phase6b_status.md").write_text(
        "# Phase 6B status\n\n"
        f"**STATUS = {status}.**\n\n"
        "The canonical 423-trade ledger remains locked by Phase 6A. The ingestion pipeline is prepared but no Phase 6C trigger search has been started. Supply preserved copies of same-account tick and transaction artifacts to `data/native/incoming/`; do not include credentials.\n",
        encoding="utf-8",
    )
    validation = {
        "phase": "6B", "run_utc": datetime.now(UTC).isoformat(), "status": status,
        "baseline_lock_required": True, "phase6_baseline_sha256": phase6["canonical"]["raw_sha256"],
        "incoming_path": str(INCOMING), "artifacts_discovered": len(inspected), "artifacts": manifest,
        "raw_artifacts_mutated": False, "phase6c_started": False,
        "gates": {"A_provenance": "WAITING", "B_symbol": "WAITING", "C_coverage": "WAITING", "D_alignment": "WAITING", "E_bid_ask_reachability": "WAITING", "F_lifecycle_linkage": "WAITING"},
    }
    (OUT / "phase6b_ingestion_validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    print(json.dumps({"status": status, "artifacts": len(inspected), "phase6c_started": False}, indent=2))


if __name__ == "__main__":
    main()
