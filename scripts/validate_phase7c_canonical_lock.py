from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "data" / "raw" / "trades_raw.tsv"
RECON_PATH = ROOT / "outputs" / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
TICKS_DIR = ROOT / "data" / "market" / "raw_ticks"
OUT_DIR = ROOT / "outputs" / "market_reconstruction"

EXPECTED_LEDGER_SHA256 = "3B22B24C5F7BEB2118FFEC613640A9AB1472C3D04E4503229D00771277E4B6BD"
EXPECTED_ROWS = 423
REQUIRED_RECON_COLUMNS = {
    "ticket",
    "side",
    "volume",
    "recorded_open_time",
    "recorded_close_time",
    "open_time_utc",
    "close_time_utc",
    "entry_tick_time_utc",
    "entry_tick_bid",
    "entry_tick_ask",
    "entry_exec_price",
    "exit_tick_time_utc",
    "exit_tick_bid",
    "exit_tick_ask",
    "exit_exec_price",
    "match_status",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def count_tsv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return sum(1 for row in csv.reader(f, delimiter="\t") if row)


def read_reconciliation(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return rows, list(reader.fieldnames or [])


def main() -> None:
    if not LEDGER_PATH.exists():
        raise AssertionError(f"Missing canonical ledger: {LEDGER_PATH}")
    if not RECON_PATH.exists():
        raise AssertionError(f"Missing Phase 7C reconciliation: {RECON_PATH}")
    if not TICKS_DIR.exists():
        raise AssertionError(f"Missing raw tick directory: {TICKS_DIR}")

    ledger_rows = count_tsv_rows(LEDGER_PATH)
    ledger_sha = sha256(LEDGER_PATH)
    recon_rows, recon_columns = read_reconciliation(RECON_PATH)
    raw_tick_files = sorted(TICKS_DIR.glob("xauusd_ticks_*.json"))
    missing_columns = sorted(REQUIRED_RECON_COLUMNS.difference(recon_columns))

    if ledger_rows != EXPECTED_ROWS:
        raise AssertionError(f"Canonical ledger row count changed: {ledger_rows}")
    if ledger_sha != EXPECTED_LEDGER_SHA256:
        raise AssertionError(f"Canonical ledger hash changed: {ledger_sha}")
    if len(recon_rows) != EXPECTED_ROWS:
        raise AssertionError(f"Phase 7C reconciliation row count changed: {len(recon_rows)}")
    if missing_columns:
        raise AssertionError(f"Phase 7C reconciliation is missing columns: {missing_columns}")
    if not raw_tick_files:
        raise AssertionError("No hourly raw tick JSON files found")

    manifest = {
        "status": "CANONICAL_LOCKED",
        "canonical_trade_ledger": {
            "path": str(LEDGER_PATH.relative_to(ROOT)).replace("\\", "/"),
            "rows": ledger_rows,
            "sha256": ledger_sha,
        },
        "canonical_trade_to_market_alignment": {
            "path": str(RECON_PATH.relative_to(ROOT)).replace("\\", "/"),
            "rows": len(recon_rows),
            "source_type": "genuine historical raw XAUUSD tick stream",
            "required_columns_present": True,
        },
        "raw_tick_source": {
            "path": str(TICKS_DIR.relative_to(ROOT)).replace("\\", "/"),
            "file_glob": "xauusd_ticks_<ISO>.json",
            "file_count": len(raw_tick_files),
            "first_file": raw_tick_files[0].name,
            "last_file": raw_tick_files[-1].name,
        },
        "forbidden_substitutions": [
            "M1 interpolated feed",
            "synthetic/modelled feed",
            "Dukascopy bid-only M1 proxy as canonical alignment",
        ],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "phase7c_canonical_source_lock.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "phase7c_canonical_source_lock.md").write_text(
        "\n".join(
            [
                "# Phase 7C Canonical Source Lock",
                "",
                "STATUS = CANONICAL_LOCKED",
                "",
                "The canonical trade-to-market alignment artifact is `outputs/market_reconstruction/phase7c_trade_reconciliation.csv`.",
                "",
                "This artifact contains the 423 canonical trades reconciled against the genuine historical raw XAUUSD tick stream.",
                "",
                "The underlying raw source files are the hourly JSON files in `data/market/raw_ticks/` with names matching `xauusd_ticks_<ISO>.json`.",
                "",
                "The canonical 423-row trade ledger remains `data/raw/trades_raw.tsv`.",
                "",
                "Do not replace this alignment source with M1 interpolated data, synthetic/modelled feeds, or the earlier bid-only M1 proxy.",
                "",
                f"- canonical ledger rows: {ledger_rows}",
                f"- canonical ledger SHA256: `{ledger_sha}`",
                f"- Phase 7C reconciliation rows: {len(recon_rows)}",
                f"- raw tick hourly JSON files: {len(raw_tick_files)}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
