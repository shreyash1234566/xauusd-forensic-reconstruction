"""
Tests for Phase 7B: Tick-Level 423-Trade Market-Feed Reconciliation & Microstructural Alignment.
"""

import json
import hashlib
import pandas as pd
import numpy as np
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "market_reconstruction"
VIS_DIR = OUT_DIR / "phase7b_visual_validation"
RAW_TRADES = ROOT / "data" / "raw" / "trades_raw.tsv"
EXPECTED_SHA256 = "3B22B24C5F7BEB2118FFEC613640A9AB1472C3D04E4503229D00771277E4B6BD"


def test_phase7b_canonical_ledger_invariants():
    """Verify raw trade file conforms strictly to cryptographic and statistical ledger invariants."""
    assert RAW_TRADES.exists(), "Raw trades dataset must exist"
    calc_hash = hashlib.sha256(RAW_TRADES.read_bytes()).hexdigest().upper()
    assert calc_hash == EXPECTED_SHA256, f"Cryptographic hash mismatch: {calc_hash}"

    df = pd.read_csv(
        RAW_TRADES,
        sep='\t',
        header=None,
        names=['ticket', 'side', 'open_time', 'close_time', 'symbol', 'volume', 'close_price', 'pnl'],
        dtype={'ticket': str, 'volume': str, 'close_price': str, 'pnl': str}
    )

    assert len(df) == 423, "Ledger must contain exactly 423 records"
    assert (df['side'] == 'Buy').sum() == 214, "Must have exactly 214 Buys"
    assert (df['side'] == 'Sell').sum() == 209, "Must have exactly 209 Sells"
    assert (df['symbol'] == 'XAUUSD.f').all(), "All symbols must be XAUUSD.f"
    assert (df['volume'] == '0.01').sum() == 401, "Must have 401 0.01 lot trades"
    assert (df['volume'] == '0.02').sum() == 21, "Must have 21 0.02 lot trades"
    assert (df['volume'] == '0.03').sum() == 1, "Must have 1 0.03 lot trade"
    assert round(df['pnl'].astype(float).sum(), 2) == 1451.22, "Recorded total PnL must be +1451.22"


def test_phase7b_deliverable_artifacts_exist():
    """Verify that all Phase 7B required deliverable files and visual charts are present and non-empty."""
    required_files = [
        OUT_DIR / "phase7b_status.md",
        OUT_DIR / "phase7b_tick_quality.csv",
        OUT_DIR / "phase7b_feed_results.csv",
        OUT_DIR / "phase7b_trade_match.csv",
        OUT_DIR / "phase7b_pnl_reconstruction.csv",
        OUT_DIR / "phase7b_timezone_sensitivity.csv",
        OUT_DIR / "phase7b_feed_comparison.md",
        OUT_DIR / "phase7b_validation.json",
        VIS_DIR / "first_20_trades_overlay.png",
        VIS_DIR / "every_25th_trade_overlay.png",
        VIS_DIR / "volume_anomaly_trades_overlay.png",
        VIS_DIR / "largest_winners_overlay.png",
        VIS_DIR / "largest_losses_overlay.png",
        VIS_DIR / "last_20_trades_overlay.png"
    ]
    for p in required_files:
        assert p.exists(), f"Required Phase 7B deliverable missing: {p}"
        assert p.stat().st_size > 0, f"Deliverable {p} is empty"


def test_phase7b_tick_quality_table():
    """Verify tick quality table schema and feed coverage."""
    df = pd.read_csv(OUT_DIR / "phase7b_tick_quality.csv")
    assert len(df) >= 7, "Must document at least 7 candidate feeds"
    assert 'feed_id' in df.columns
    assert 'bid_availability' in df.columns
    assert 'timestamp_precision' in df.columns
    assert 'broker_native_status' in df.columns

    # Verify no native feeds are falsely marked as broker-native
    assert not (df['broker_native_status'] == 'Broker-Native Internal Feed').any()


def test_phase7b_feed_benchmarking_and_controls():
    """Verify candidate feed benchmarking, ranking, and negative control rejections."""
    df = pd.read_csv(OUT_DIR / "phase7b_feed_results.csv")
    assert len(df) >= 7

    # Winning feeds must be Gold spot / CFD
    top_feed = df.iloc[0]
    assert 'XAU' in top_feed['underlying_market'] or 'Gold' in top_feed['underlying_market']
    assert top_feed['coverage_pct_3_00'] >= 80.0

    # Negative controls (Silver, EURUSD) must be strictly REJECTED with 0 matches
    silver = df[df['candidate_id'] == 'FEED_06_XAGUSD_SILVER_TICK'].iloc[0]
    eurusd = df[df['candidate_id'] == 'FEED_07_EURUSD_FOREX_TICK'].iloc[0]
    assert silver['evaluation_verdict'] == 'REJECTED'
    assert silver['match_le_3_00'] == 0
    assert eurusd['evaluation_verdict'] == 'REJECTED'
    assert eurusd['match_le_3_00'] == 0

    # Futures must have large basis error (> $15/oz) and be REJECTED
    futures = df[df['candidate_id'] == 'FEED_05_COMEX_GC_FUTURES_TICK'].iloc[0]
    assert futures['median_entry_error'] > 15.0
    assert futures['evaluation_verdict'] == 'REJECTED'


def test_phase7b_timezone_sensitivity():
    """Verify timezone sensitivity grid search identifies DST-aware EET/EEST as optimal."""
    df = pd.read_csv(OUT_DIR / "phase7b_timezone_sensitivity.csv")
    assert len(df) >= 8, "Must sweep across candidate timezones"

    top_tz = df.iloc[0]
    assert top_tz['timezone_mode'] == 'dst_eet'
    assert top_tz['verdict'] == 'OPTIMAL'
    assert top_tz['median_entry_error'] < 1.0
    assert top_tz['entry_in_bar_pct'] > 80.0


def test_phase7b_trade_match_ledger():
    """Verify full 423-trade tick matching ledger integrity."""
    df = pd.read_csv(OUT_DIR / "phase7b_trade_match.csv")
    assert len(df) == 423, "All 423 trades must be present"
    assert df['match_le_3_00'].sum() >= 360, "At least 360 trades must meet <= $3.00 tolerance match"
    assert df['entry_price_error'].median() < 1.0, "Median entry error must be below $1.00/oz"
    assert df['exit_price_error'].median() < 1.0, "Median exit error must be below $1.00/oz"


def test_phase7b_pnl_reconstruction():
    """Verify P&L reconstruction ledger and residual metrics."""
    df = pd.read_csv(OUT_DIR / "phase7b_pnl_reconstruction.csv")
    assert len(df) == 423
    assert round(df['recorded_pnl'].sum(), 2) == 1451.22
    assert df['reconstructed_pnl_zero_spread'].sum() > 1400.0, "Gross PnL must be near +1451.22"
    assert df['reconstructed_pnl_spread'].sum() > 1200.0, "Net PnL with spread must exceed +1200"
    assert df['residual_spread'].median() < 1.0, "Median residual must be low"


def test_phase7b_validation_json():
    """Verify validation JSON metrics conform to required schema and invariants."""
    p_json = OUT_DIR / "phase7b_validation.json"
    data = json.loads(p_json.read_text(encoding='utf-8'))

    assert data['phase'] == '7B'
    assert data['canonical_invariants']['expected_sha256'] == EXPECTED_SHA256
    assert data['canonical_invariants']['hash_verified'] is True
    assert data['canonical_invariants']['trade_count'] == 423
    assert data['optimal_specifications']['underlying_market'] == 'XAUUSD'
    assert data['optimal_specifications']['contract_multiplier_C'] == 100.0
    assert data['optimal_specifications']['stored_price_role'] == 'H_ENTRY'
    assert data['reconciliation_metrics']['tolerance_matches']['le_3_00'] >= 360
    assert 'UNDERLYING_MARKET_IDENTIFIED' in data['final_classification']['decision']
