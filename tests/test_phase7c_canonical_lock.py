from pathlib import Path

from scripts.validate_phase7c_canonical_lock import (
    EXPECTED_LEDGER_SHA256,
    EXPECTED_ROWS,
    LEDGER_PATH,
    RECON_PATH,
    REQUIRED_RECON_COLUMNS,
    TICKS_DIR,
    count_tsv_rows,
    read_reconciliation,
    sha256,
)


def test_phase7c_is_canonical_raw_tick_alignment() -> None:
    assert LEDGER_PATH.exists()
    assert RECON_PATH.exists()
    assert TICKS_DIR.exists()

    assert count_tsv_rows(LEDGER_PATH) == EXPECTED_ROWS
    assert sha256(LEDGER_PATH) == EXPECTED_LEDGER_SHA256

    rows, columns = read_reconciliation(RECON_PATH)
    assert len(rows) == EXPECTED_ROWS
    assert REQUIRED_RECON_COLUMNS.issubset(set(columns))

    raw_tick_files = list(Path(TICKS_DIR).glob("xauusd_ticks_*.json"))
    assert raw_tick_files
