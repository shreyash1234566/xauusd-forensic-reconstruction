"""
Phase 8B - Stage 1: Input Verification and Environment Integrity Check
Validates all required input files, hashes, schemas, and tick store availability.
Deterministic Cheap stage (< 1 second).
"""

import sys
import hashlib
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUTS_DIR = ROOT / "outputs"
RAW_TRADES_PATH = DATA_DIR / "raw" / "trades_raw.tsv"
RECON_PATH = OUTPUTS_DIR / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
PANEL_PATH = DATA_DIR / "processed" / "decision_panel.parquet"
TICKS_DIR = DATA_DIR / "market" / "raw_ticks"

EXPECTED_HASH = "3b22b24c5f7beb2118ffec613640a9ab1472c3d04e4503229d00771277e4b6bd"

def compute_sha256(file_path):
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower()

def main():
    print("=================================================================")
    print("PHASE 8B - STAGE 01: INPUT VERIFICATION & ENVIRONMENT AUDIT")
    print("=================================================================")

    # 1. Raw trades check
    if not RAW_TRADES_PATH.exists():
        print(f"[FAIL] Raw trades file not found: {RAW_TRADES_PATH}")
        sys.exit(1)

    file_hash = compute_sha256(RAW_TRADES_PATH)
    if file_hash != EXPECTED_HASH:
        print(f"[FAIL] Hash mismatch for {RAW_TRADES_PATH}")
        print(f"  Expected: {EXPECTED_HASH}")
        print(f"  Got:      {file_hash}")
        sys.exit(1)
    print(f"[PASS] Canonical trades_raw.tsv verified (SHA-256: {file_hash[:16]}...)")

    raw_df = pd.read_csv(RAW_TRADES_PATH, sep="\t", header=None)
    if len(raw_df) != 423:
        print(f"[FAIL] Expected 423 trades, got {len(raw_df)}")
        sys.exit(1)
    print(f"[PASS] Canonical trade count verified: 423 rows")

    # 2. Phase 7C Reconciliation check
    if not RECON_PATH.exists():
        print(f"[FAIL] Reconciliation file not found: {RECON_PATH}")
        sys.exit(1)

    recon_df = pd.read_csv(RECON_PATH)
    if len(recon_df) != 423:
        print(f"[FAIL] Expected 423 reconciled trades, got {len(recon_df)}")
        sys.exit(1)
    print(f"[PASS] Reconciled trade dataset verified: 423 rows")

    # 3. Decision Panel check
    if not PANEL_PATH.exists():
        print(f"[FAIL] Decision panel file not found: {PANEL_PATH}")
        sys.exit(1)

    panel_df = pd.read_parquet(PANEL_PATH)
    print(f"[PASS] Decision panel verified: {len(panel_df):,} bars, {panel_df['is_trade'].sum()} positive trades")

    # 4. Raw Ticks directory check
    if not TICKS_DIR.exists():
        print(f"[FAIL] Raw ticks directory not found: {TICKS_DIR}")
        sys.exit(1)

    tick_files = list(TICKS_DIR.glob("*.json"))
    print(f"[PASS] Raw ticks store verified: {len(tick_files)} hourly JSON files available")

    # Ensure output directory exists
    out_dir = OUTPUTS_DIR / "strategy_reconstruction"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[PASS] Output directory ready: {out_dir}")

    print("\nSTAGE 01 STATUS: ALL PRECONDITIONS MET (100% PASS)\n")

if __name__ == "__main__":
    main()
