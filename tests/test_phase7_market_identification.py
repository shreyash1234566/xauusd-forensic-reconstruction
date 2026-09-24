"""
Tests for Phase 7: Full 423-Trade Market / Chart Identification & P&L Reconstruction.
"""

import json
import hashlib
import pandas as pd
import numpy as np
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "market_reconstruction"
VIS_DIR = OUT_DIR / "phase7_visual_validation"
RAW_TRADES = ROOT / "data" / "raw" / "trades_raw.tsv"
EXPECTED_SHA256 = "3B22B24C5F7BEB2118FFEC613640A9AB1472C3D04E4503229D00771277E4B6BD"


def test_canonical_ledger_invariants():
    """Verify raw trade file exists and conforms to immutable ledger invariants."""
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


def test_all_deliverable_artifacts_exist():
    """Verify that all Phase 7 required files and directories are present."""
    required_files = [
        OUT_DIR / "phase7_status.md",
        OUT_DIR / "phase7_methodology.md",
        OUT_DIR / "phase7_candidate_feed_results.csv",
        OUT_DIR / "phase7_trade_feed_match.csv",
        OUT_DIR / "phase7_timezone_results.csv",
        OUT_DIR / "phase7_price_role_results.csv",
        OUT_DIR / "phase7_contract_multiplier_results.csv",
        OUT_DIR / "phase7_pnl_reconstruction.csv",
        OUT_DIR / "phase7_validation.json",
        VIS_DIR / "pnl_equity_curve_reconstruction.png",
        VIS_DIR / "residual_distribution_plot.png",
        VIS_DIR / "first_10_trades_overlay.png",
        VIS_DIR / "every_50th_trade_overlay.png",
        VIS_DIR / "volume_anomaly_trades_overlay.png",
        VIS_DIR / "major_loss_trades_overlay.png",
        VIS_DIR / "last_10_trades_overlay.png"
    ]
    for p in required_files:
        assert p.exists(), f"Required Phase 7 deliverable missing: {p}"
        assert p.stat().st_size > 0, f"Deliverable {p} is empty"


def test_candidate_feeds_ranking():
    """Verify candidate feed ranking and negative control rejections."""
    df = pd.read_csv(OUT_DIR / "phase7_candidate_feed_results.csv")
    assert len(df) >= 7, "Must benchmark at least 7 candidate feeds"

    # Winning feeds must be Gold spot / CFD
    top_feed = df.iloc[0]
    assert 'XAU' in top_feed['underlying_market'] or 'Gold' in top_feed['underlying_market']
    assert top_feed['strict_coverage_pct'] >= 80.0

    # Negative controls (Silver, EURUSD) must be strictly REJECTED with 0 matches
    silver = df[df['candidate_id'] == 'FEED_06_XAGUSD_SILVER_SPOT'].iloc[0]
    eurusd = df[df['candidate_id'] == 'FEED_07_EURUSD_FOREX_SPOT'].iloc[0]
    assert silver['evaluation_verdict'] == 'REJECTED'
    assert silver['strict_matched_count'] == 0
    assert eurusd['evaluation_verdict'] == 'REJECTED'
    assert eurusd['strict_matched_count'] == 0

    # Futures must have large basis error (> $15/oz) and be REJECTED
    futures = df[df['candidate_id'] == 'FEED_05_COMEX_GC_FUTURES_CONTINUOUS'].iloc[0]
    assert futures['median_open_error'] > 15.0
    assert futures['evaluation_verdict'] == 'REJECTED'


def test_timezone_optimization():
    """Verify timezone grid search identifies DST-aware EET/EEST as optimal."""
    df = pd.read_csv(OUT_DIR / "phase7_timezone_results.csv")
    assert len(df) >= 20, "Must sweep across global timezones"

    top_tz = df.iloc[0]
    assert top_tz['timezone_mode'] == 'dst_eet'
    assert top_tz['verdict'] == 'OPTIMAL'
    assert top_tz['median_open_error'] < 1.5
    assert top_tz['open_in_bar_pct'] > 80.0


def test_price_role_hypothesis():
    """Verify hypothesis testing confirms H_ENTRY and rejects H_EXIT."""
    df = pd.read_csv(OUT_DIR / "phase7_price_role_results.csv")
    assert len(df) == 2

    hentry = df[df['hypothesis'] == 'H_ENTRY'].iloc[0]
    hexit = df[df['hypothesis'] == 'H_EXIT'].iloc[0]

    assert 'CONFIRMED' in hentry['verdict']
    assert 'REJECTED' in hexit['verdict']
    assert hentry['median_open_error'] < hexit['median_open_error']
    assert hentry['open_in_bar_pct'] > hexit['open_in_bar_pct'] * 2.5


def test_contract_multiplier_optimization():
    """Verify multiplier C=100 is selected and alternative multipliers rejected."""
    df = pd.read_csv(OUT_DIR / "phase7_contract_multiplier_results.csv")
    c100 = df[df['multiplier_C'] == 100].iloc[0]
    assert c100['verdict'] == 'OPTIMAL_STANDARD'
    assert c100['median_implied_exit_error'] < 1.0

    # Test rejection of non-100 standard values (1, 10, 50, 500, 1000)
    for c_val in [1, 10, 50, 500, 1000]:
        c_row = df[df['multiplier_C'] == c_val].iloc[0]
        assert c_row['verdict'] == 'REJECTED'
        assert c_row['median_implied_exit_error'] > 2.0


def test_trade_feed_match_ledger():
    """Verify full 423-trade alignment ledger integrity."""
    df = pd.read_csv(OUT_DIR / "phase7_trade_feed_match.csv")
    assert len(df) == 423, "All 423 trades must be matched"
    assert df['matched'].sum() >= 380, "At least 380 trades must meet tolerance match"
    assert df['entry_error'].median() < 1.2, "Median entry error must be below $1.20/oz"
    assert df['exit_error'].median() < 1.2, "Median exit error must be below $1.20/oz"


def test_pnl_reconstruction_ledger():
    """Verify P&L reconstruction ledger and residual metrics."""
    df = pd.read_csv(OUT_DIR / "phase7_pnl_reconstruction.csv")
    assert len(df) == 423
    assert round(df['recorded_pnl'].sum(), 2) == 1451.22
    assert df['reconstructed_net_pnl_spread'].sum() > 900.0
    assert df['residual_vs_recorded'].abs().median() < 2.0


def test_validation_json_structure():
    """Verify validation JSON metrics file conform to expected schema and invariants."""
    p_json = OUT_DIR / "phase7_validation.json"
    data = json.loads(p_json.read_text(encoding='utf-8'))

    assert data['phase'] == 7
    assert data['canonical_invariants']['expected_sha256'] == EXPECTED_SHA256
    assert data['canonical_invariants']['hash_verified'] is True
    assert data['canonical_invariants']['trade_count'] == 423
    assert data['market_identification']['underlying_market'] == 'XAUUSD'
    assert data['market_identification']['decision_classification'] == 'STRONG_UNDERLYING_MARKET_MATCH'
    assert data['optimal_specifications']['contract_multiplier'] == 100.0
    assert data['optimal_specifications']['stored_price_role'] == 'H_ENTRY'
    assert data['ledger_matching_performance']['matched_trades_count'] >= 380
