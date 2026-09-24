"""Canonical evidence auditing and ledger loading.

This module refuses to promote fields inferred from Phase 7C into original
ledger observations.  Its input is read-only; all artifacts are new outputs.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .io import sha256


CANONICAL_LEDGER_SHA256 = "3B22B24C5F7BEB2118FFEC613640A9AB1472C3D04E4503229D00771277E4B6BD"
CANONICAL_RECORD_COUNT = 423
CANONICAL_EPOCH_COUNT = 420
SPLIT_ORDER_PAIRS = (
    ("36168589", "36168590"),
    ("36227385", "36227388"),
    ("36335183", "36335196"),
)
REQUIRED_RECON_COLUMNS = {
    "ticket", "side", "volume", "recorded_open_time", "recorded_close_time",
    "open_time_utc", "close_time_utc", "recorded_price", "recorded_pnl",
    "entry_tick_time_utc", "entry_tick_bid", "entry_tick_ask", "entry_exec_price",
    "exit_tick_time_utc", "exit_tick_bid", "exit_tick_ask", "exit_exec_price",
    "match_status",
}


@dataclass(frozen=True)
class EvidencePaths:
    root: Path

    @property
    def ledger(self) -> Path:
        return self.root / "data" / "raw" / "trades_raw.tsv"

    @property
    def reconciliation(self) -> Path:
        return self.root / "outputs" / "market_reconstruction" / "phase7c_trade_reconciliation.csv"

    @property
    def raw_ticks(self) -> Path:
        return self.root / "data" / "market" / "raw_ticks"


def normalize_ticket(value: object) -> str:
    raw = str(value).strip()
    stripped = raw.lstrip("0")
    return stripped or "0"


def _count_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for row in csv.reader(handle, delimiter="\t") if row)


def audit_canonical_evidence(root: Path) -> dict[str, Any]:
    """Return a fact-only audit and fail closed if canonical invariants differ."""

    paths = EvidencePaths(root)
    for path in (paths.ledger, paths.reconciliation, paths.raw_ticks):
        if not path.exists():
            raise FileNotFoundError(f"Required canonical evidence is missing: {path}")
    ledger_rows = _count_rows(paths.ledger)
    ledger_hash = sha256(paths.ledger)
    if ledger_rows != CANONICAL_RECORD_COUNT:
        raise ValueError(f"Expected {CANONICAL_RECORD_COUNT} canonical records, found {ledger_rows}")
    if ledger_hash != CANONICAL_LEDGER_SHA256:
        raise ValueError("Canonical ledger hash does not match the Phase 7C source lock")
    recon = pd.read_csv(paths.reconciliation, dtype={"ticket": str})
    missing = sorted(REQUIRED_RECON_COLUMNS.difference(recon.columns))
    if len(recon) != CANONICAL_RECORD_COUNT or missing:
        raise ValueError(f"Invalid Phase 7C reconciliation: rows={len(recon)}, missing={missing}")
    tick_files = sorted(paths.raw_ticks.glob("xauusd_ticks_*.json"))
    if not tick_files:
        raise ValueError("Canonical raw tick directory contains no hourly tick JSON files")
    return {
        "status": "CANONICAL_LOCKED",
        "ledger": {"path": paths.ledger.relative_to(root).as_posix(), "rows": ledger_rows, "sha256": ledger_hash},
        "reconciliation": {"path": paths.reconciliation.relative_to(root).as_posix(), "rows": len(recon)},
        "raw_ticks": {
            "path": paths.raw_ticks.relative_to(root).as_posix(),
            "glob": "xauusd_ticks_<ISO>.json",
            "files": len(tick_files),
            "first": tick_files[0].name,
            "last": tick_files[-1].name,
        },
        "forbidden_substitutions": ["M1 interpolated feed", "synthetic/modelled feed", "bid-only M1 proxy"],
    }


def load_canonical_records(root: Path) -> pd.DataFrame:
    """Load the Phase 7C view as typed records without changing its source file."""

    audit_canonical_evidence(root)
    path = EvidencePaths(root).reconciliation
    records = pd.read_csv(path, dtype={"ticket": str})
    for column in ("open_time_utc", "close_time_utc", "entry_tick_time_utc", "exit_tick_time_utc"):
        records[column] = pd.to_datetime(records[column], utc=True, errors="raise")
    records["ticket_normalized"] = records["ticket"].map(normalize_ticket)
    records["record_id"] = records["ticket_normalized"]
    records["recorded_price_semantics"] = "recorded_entry_price_supported_by_phase7c"
    records["exit_price_semantics"] = "derived_public_tick_estimate_not_independent_ledger_observation"
    return records.sort_values(["open_time_utc", "close_time_utc", "ticket_normalized"], kind="mergesort").reset_index(drop=True)


def build_decision_epochs(records: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply only the three project-defined split-pair merges."""

    required = {"ticket_normalized", "side", "open_time_utc", "close_time_utc"}
    missing = required.difference(records.columns)
    if missing:
        raise ValueError(f"Missing record columns for epoch construction: {sorted(missing)}")
    annotated = records.copy().sort_values(["open_time_utc", "close_time_utc", "ticket_normalized"], kind="mergesort").reset_index(drop=True)
    pair_for_ticket = {ticket: pair_index for pair_index, pair in enumerate(SPLIT_ORDER_PAIRS) for ticket in pair}
    found = set(annotated["ticket_normalized"])
    expected = set(pair_for_ticket)
    if found.intersection(expected) != expected:
        raise ValueError(f"Required split tickets missing: {sorted(expected.difference(found))}")
    annotated["split_pair_index"] = annotated["ticket_normalized"].map(pair_for_ticket)
    annotated["_epoch_key"] = [
        f"split:{int(pair)}" if pd.notna(pair) else f"record:{row}"
        for row, pair in enumerate(annotated["split_pair_index"])
    ]
    for pair_index, pair in enumerate(SPLIT_ORDER_PAIRS):
        members = annotated[annotated["split_pair_index"] == pair_index]
        if len(members) != 2 or set(members["ticket_normalized"]) != set(pair) or members["side"].nunique() != 1:
            raise ValueError(f"Invalid fixed split-order pair: {pair}")
        first, second = members.iloc[0], members.iloc[1]
        if not (first.open_time_utc < second.open_time_utc < first.close_time_utc):
            raise ValueError(f"Split-order pair is not strictly overlapping: {pair}")
    key_order = annotated.groupby("_epoch_key", sort=False).head(1)["_epoch_key"].tolist()
    key_to_epoch = {key: index for index, key in enumerate(key_order)}
    annotated["epoch_id"] = annotated["_epoch_key"].map(key_to_epoch).astype(int)
    annotated["epoch_record_rank"] = annotated.groupby("epoch_id").cumcount()
    annotated["is_epoch_anchor"] = annotated["epoch_record_rank"].eq(0)
    annotated["decision_time_utc"] = annotated.groupby("epoch_id")["open_time_utc"].transform("min")
    epochs = annotated[annotated["is_epoch_anchor"]].copy()
    epochs["record_count"] = epochs["epoch_id"].map(annotated.groupby("epoch_id").size())
    epochs["member_tickets"] = epochs["epoch_id"].map(
        annotated.groupby("epoch_id")["ticket_normalized"].apply(lambda items: list(items))
    )
    if len(annotated) != CANONICAL_RECORD_COUNT or len(epochs) != CANONICAL_EPOCH_COUNT:
        raise ValueError("Unexpected canonical record/epoch count")
    return annotated.drop(columns=["_epoch_key"]), epochs.reset_index(drop=True)
