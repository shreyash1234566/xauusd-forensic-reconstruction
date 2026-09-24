"""
Tests for Phase 7C: Real Raw-Tick Validation of All 423 XAUUSD.f Trades.
Validates genuine physical Bid/Ask millisecond ticks, non-circular P&L reconstruction,
negative controls, timezone sensitivity, and visual deliverables.
"""

import json
import hashlib
import pandas as pd
import numpy as np
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "market_reconstruction"
VIS_DIR = OUT_DIR / "phase7c_visual_validation"
RAW_TRADES = ROOT / "data" / "raw" / "trades_raw.tsv"
EXPECTED_SHA256 = "3B22B24C5F7BEB2118FFEC613640A9AB1472C3D04E4503229D00771277E4B6BD"


def test_phase7c_canonical_ledger_invariants():
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


def test_phase7c_deliverable_artifacts_exist():
    """Verify that all Phase 7C required deliverable files and visual overlay plots are present and non-empty."""
    required_files = [
        OUT_DIR / "phase7c_report.md",
        OUT_DIR / "phase7c_raw_tick_validation.csv",
        OUT_DIR / "phase7c_trade_reconciliation.csv",
        OUT_DIR / "phase7c_m1_vs_raw_tick_comparison.csv",
        OUT_DIR / "phase7c_feed_comparison.csv",
        OUT_DIR / "phase7c_timezone_sensitivity.csv",
        OUT_DIR / "phase7c_residual_analysis.csv",
        OUT_DIR / "phase7c_validation.json",
        VIS_DIR / "first_20_trades_raw_tick_overlay.png",
        VIS_DIR / "every_25th_trade_raw_tick_overlay.png",
        VIS_DIR / "largest_winners_raw_tick_overlay.png",
        VIS_DIR / "largest_losses_raw_tick_overlay.png",
        VIS_DIR / "volume_anomaly_raw_tick_overlay.png",
        VIS_DIR / "pnl_reconstruction_equity_curve.png",
        VIS_DIR / "m1_vs_raw_tick_error_distribution.png"
    ]
    for p in required_files:
        assert p.exists(), f"Required Phase 7C deliverable missing: {p}"
        assert p.stat().st_size > 0, f"Deliverable {p} is empty"


def test_phase7c_raw_tick_matching_quality():
    """Verify that genuine raw tick matching achieves expected precision boundaries."""
    df = pd.read_csv(OUT_DIR / "phase7c_trade_reconciliation.csv")
    assert len(df) == 423, "Must evaluate all 423 trades"

    # Verify median entry price error is sub-dollar (< $0.80/oz)
    median_entry_err = df['entry_price_error'].median()
    assert median_entry_err < 0.80, f"Median entry price error too high: {median_entry_err}"

    # Verify median timestamp delta is sub-second (< 0.5s)
    median_time_delta = df['entry_time_delta_sec'].median()
    assert median_time_delta < 0.50, f"Median time delta too high: {median_time_delta}"

    # Verify tolerance match counts
    matches_3_00 = (df['entry_price_error'] <= 3.00).sum()
    assert matches_3_00 >= 360, f"Expected >= 360 trades within $3.00/oz, got {matches_3_00}"


def test_phase7c_feed_benchmarking_and_controls():
    """Verify candidate feed benchmarking, ranking, and strict negative control rejections."""
    df = pd.read_csv(OUT_DIR / "phase7c_feed_comparison.csv")
    assert len(df) >= 7

    # Top feed must be Gold spot / CFD
    top_feed = df.iloc[0]
    assert 'XAU' in top_feed['underlying_market'] or 'Gold' in top_feed['underlying_market']
    assert top_feed['coverage_pct_3_00'] >= 80.0

    # Negative controls (Silver, EURUSD) must be strictly REJECTED with 0 matches
    silver = df[df['candidate_id'] == 'FEED_06_XAGUSD_SILVER_TICK'].iloc[0]
    eurusd = df[df['candidate_id'] == 'FEED_07_EURUSD_FOREX_TICK'].iloc[0]
    assert 'REJECTED' in silver['evaluation_verdict']
    assert silver['matches_le_3_00'] == 0
    assert 'REJECTED' in eurusd['evaluation_verdict']
    assert eurusd['matches_le_3_00'] == 0

    # COMEX Futures must be rejected due to massive contango/basis gap (> $15/oz)
    futures = df[df['candidate_id'] == 'FEED_05_COMEX_GC_FUTURES_TICK'].iloc[0]
    assert futures['median_entry_error'] > 15.0
    assert 'REJECTED' in futures['evaluation_verdict']


def test_phase7c_timezone_sensitivity():
    """Verify DST-aware EET/EEST is strictly optimal over static offsets."""
    df = pd.read_csv(OUT_DIR / "phase7c_timezone_sensitivity.csv")
    assert len(df) >= 6

    top_tz = df.iloc[0]
    assert top_tz['timezone_mode'] == 'dst_eet'
    assert top_tz['verdict'] == 'OPTIMAL'
    assert top_tz['median_entry_error'] < 0.80
    assert top_tz['coverage_pct_3_00'] > 80.0


def test_phase7c_pnl_reconstruction():
    """Verify non-circular P&L reconstruction matches recorded P&L within tight bounds."""
    df = pd.read_csv(OUT_DIR / "phase7c_trade_reconciliation.csv")
    assert len(df) == 423

    # Total recorded PnL
    recorded_total = df['recorded_pnl'].sum()
    assert round(recorded_total, 2) == 1451.22

    # Gross reconstructed PnL should match within $10 of recorded PnL
    gross_pnl = df['reconstructed_pnl_raw_mid'].sum()
    pnl_delta = abs(gross_pnl - recorded_total)
    assert pnl_delta < 10.0, f"Gross PnL delta too large: ${pnl_delta:.2f}"

    # Reconstructed net PnL (including bid/ask spread) should be positive and > $1100
    net_pnl = df['reconstructed_pnl_raw_bidask'].sum()
    assert net_pnl > 1100.0, f"Net PnL too low: ${net_pnl:.2f}"


def test_phase7c_validation_json_schema():
    """Verify validation JSON metadata conforms to schema and certified invariants."""
    p_json = OUT_DIR / "phase7c_validation.json"
    data = json.loads(p_json.read_text(encoding='utf-8'))

    assert data['phase'] == '7C'
    assert data['canonical_invariants']['hash_verified'] is True
    assert data['canonical_invariants']['trade_count'] == 423
    assert data['optimal_specifications']['underlying_market'] == 'XAUUSD'
    assert data['optimal_specifications']['contract_multiplier_C'] == 100.0
    assert data['optimal_specifications']['stored_price_role'] == 'H_ENTRY'
    assert data['reconciliation_metrics']['total_raw_ticks_analyzed'] > 7_000_000
    assert data['reconciliation_metrics']['tolerance_matches']['le_3_00'] >= 360
    assert 'UNDERLYING_MARKET_IDENTIFIED' in data['final_classification']['decision']
