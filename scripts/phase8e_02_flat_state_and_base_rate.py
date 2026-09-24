"""
Phase 8E - Stage 2: Flat-State Opportunity Set, Base Rate Decomposition, and Position Lockout Causal Audit
Covers:
- Section 4: Conditional-on-Flat Analysis (Flat universe vs Busy universe)
- Section 6: Strict Temporal Causality
- Section 7: True Flat-State Signal Base Rate Decomposition
- Section 18: Position Lockout Causal Test (Scenario A, B, C)
- Generates:
    outputs/strategy_reconstruction/phase8e_flat_state_analysis.csv
"""

from pathlib import Path
import time
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT / "outputs" / "strategy_reconstruction"
PANEL_PATH = ROOT / "data" / "processed" / "decision_panel.parquet"
RECON_PATH = OUTPUTS_DIR.parent / "market_reconstruction" / "phase7c_trade_reconciliation.csv"

def run_flat_state_and_lockout_analysis():
    print("=================================================================")
    print("PHASE 8E - STAGE 02: FLAT-STATE ANALYSIS & POSITION LOCKOUT")
    print("=================================================================")
    t0 = time.time()

    panel = pd.read_parquet(PANEL_PATH)
    recon = pd.read_csv(RECON_PATH)

    recon['open_dt'] = pd.to_datetime(recon['open_time_utc'])
    recon['close_dt'] = pd.to_datetime(recon['close_time_utc'])
    recon = recon.sort_values('open_dt').reset_index(drop=True)

    panel['dt'] = pd.to_datetime(panel['dt'])
    panel['hour'] = panel['dt'].dt.hour
    panel['dayofweek'] = panel['dt'].dt.dayofweek

    # 1. Precise Interval Intersection for Position State
    trade_intervals = list(zip(recon['open_dt'], recon['close_dt']))
    is_busy = np.zeros(len(panel), dtype=bool)
    in_cooldown = np.zeros(len(panel), dtype=bool)

    # 120s cooldown post-close
    cooldown_intervals = list(zip(recon['close_dt'], recon['close_dt'] + pd.Timedelta(minutes=2)))

    panel_dt = panel['dt']
    for o_dt, c_dt in trade_intervals:
        mask = (panel_dt >= o_dt) & (panel_dt <= c_dt)
        is_busy |= mask.values

    for c_dt, cd_end in cooldown_intervals:
        mask = (panel_dt > c_dt) & (panel_dt <= cd_end)
        in_cooldown |= mask.values

    panel['is_busy'] = is_busy
    panel['is_flat'] = ~is_busy
    panel['in_cooldown'] = in_cooldown

    # Identify bars containing real trade opens
    trade_open_m1 = set(recon['open_dt'].dt.floor('min'))
    panel['has_trade_open'] = panel['dt'].isin(trade_open_m1)
    total_real_trades = len(recon)

    print(f"Total M1 Bars: {len(panel):,}")
    print(f"Total Busy Bars: {panel['is_busy'].sum():,} ({panel['is_busy'].mean()*100:.2f}%)")
    print(f"Total Flat Bars: {panel['is_flat'].sum():,} ({panel['is_flat'].mean()*100:.2f}%)")
    print(f"Total Real Trade Bars: {panel['has_trade_open'].sum()} / {total_real_trades}")

    # 2. Hierarchical Eligibility Gating Decomposition
    g0_all = np.ones(len(panel), dtype=bool)
    g1_flat = panel['is_flat'].values
    g2_session = g1_flat & (panel['hour'] >= 5) & (panel['hour'] <= 16)
    g3_weekend = g2_session & ~((panel['dayofweek'] == 4) & (panel['hour'] >= 20))
    g4_cooldown = g3_weekend & ~panel['in_cooldown'].values
    g5_atr = g4_cooldown & (panel['h1_atr_pct_14'] >= 0.25)

    gates = [
        ("Level 0: Total Market Universe", g0_all, "All 1-minute historical bars"),
        ("Level 1: Conditional-on-Flat Universe", g1_flat, "PositionsTotal() == 0 (Strict single-position rule)"),
        ("Level 2: Flat + Active Session", g2_session, "05:00 - 16:00 UTC (Institutional liquidity window)"),
        ("Level 3: Flat + Session + Weekend Filter", g3_weekend, "Excludes Friday post-20:00 UTC"),
        ("Level 4: Flat + Session + Cooldown Filter", g4_cooldown, "Inter-trade lockout >= 2 minutes post-close"),
        ("Level 5: Flat + Session + Volatility Filter", g5_atr, "H1 ATR >= 0.25% minimum expansion threshold")
    ]

    gate_records = []
    for name, mask, desc in gates:
        n_bars = int(mask.sum())
        n_trades = int((mask & panel['has_trade_open'].values).sum())
        recall_pct = float(n_trades / total_real_trades * 100.0)
        base_rate = float(n_trades / n_bars * 100.0) if n_bars > 0 else 0.0
        odds = int(n_bars / n_trades) if n_trades > 0 else 0

        gate_records.append({
            'analysis_type': 'Eligibility Gate Decomposition',
            'universe_name': name,
            'description': desc,
            'bars_count': n_bars,
            'bars_pct_of_total': float(n_bars / len(panel) * 100.0),
            'real_trades_captured': n_trades,
            'real_trades_pct': recall_pct,
            'base_rate_pct': base_rate,
            'one_in_n_bars': odds,
            'executed_trades': n_trades,
            'execution_precision_pct': 100.0,
            'concurrency_lockout_pct': 0.0
        })

    # 3. Position Lockout Causal Simulation (Section 18: Scenarios A, B, C)
    print("\n--- SECTION 18: POSITION LOCKOUT CAUSAL SIMULATION ---")

    # Define candidate market trigger:
    # In-session (05-16 UTC), H1 ATR >= 0.25%, |return_1| >= $0.30
    sig_session = (panel['hour'] >= 5) & (panel['hour'] <= 16)
    sig_atr = (panel['h1_atr_pct_14'] >= 0.25)
    sig_return = (panel['return_1'].abs() >= 0.30)
    raw_trigger_mask = sig_session & sig_atr & sig_return
    raw_signal_indices = np.where(raw_trigger_mask)[0]
    n_raw_signals = len(raw_signal_indices)

    real_trade_dts = pd.to_datetime(recon['open_time_utc']).values
    holding_bars = 8  # Median holding duration ~7.6 minutes

    # Helper function to match generated trades to real trades within <= 5 min
    def evaluate_matching(trade_indices):
        exec_dts = panel.iloc[trade_indices]['dt'].values
        matched = 0
        for r_dt in real_trade_dts:
            diffs = np.abs((exec_dts - r_dt).astype('timedelta64[m]').astype(float))
            if len(diffs) > 0 and np.min(diffs) <= 5.0:
                matched += 1
        return matched

    # Scenario A: Raw Signals without Position Lockout (Concurrent multi-position permitted)
    scen_a_matched = evaluate_matching(raw_signal_indices)
    scen_a_prec = (scen_a_matched / n_raw_signals * 100.0) if n_raw_signals > 0 else 0.0
    scen_a_rec = (scen_a_matched / total_real_trades * 100.0)

    # Scenario B: Signals + Strict Position Lockout (Single-position: PositionsTotal == 0)
    scen_b_indices = []
    cur_exit_idx = -1
    for idx in raw_signal_indices:
        if idx > cur_exit_idx:
            scen_b_indices.append(idx)
            cur_exit_idx = idx + holding_bars
    n_scen_b = len(scen_b_indices)
    scen_b_matched = evaluate_matching(scen_b_indices)
    scen_b_prec = (scen_b_matched / n_scen_b * 100.0) if n_scen_b > 0 else 0.0
    scen_b_rec = (scen_b_matched / total_real_trades * 100.0)
    scen_b_lockout = ((n_raw_signals - n_scen_b) / n_raw_signals * 100.0) if n_raw_signals > 0 else 0.0

    # Scenario C: Signals + Position Lockout + 2-Minute Cooldown
    scen_c_indices = []
    cur_exit_idx = -1
    cooldown_bars = 2
    for idx in raw_signal_indices:
        if idx > cur_exit_idx + cooldown_bars:
            scen_c_indices.append(idx)
            cur_exit_idx = idx + holding_bars
    n_scen_c = len(scen_c_indices)
    scen_c_matched = evaluate_matching(scen_c_indices)
    scen_c_prec = (scen_c_matched / n_scen_c * 100.0) if n_scen_c > 0 else 0.0
    scen_c_rec = (scen_c_matched / total_real_trades * 100.0)
    scen_c_lockout = ((n_raw_signals - n_scen_c) / n_raw_signals * 100.0) if n_raw_signals > 0 else 0.0

    scenarios = [
        ("Scenario A: Raw Unconstrained Signals", "No position lockout (multi-position permitted)", n_raw_signals, scen_a_matched, scen_a_rec, scen_a_prec, 0.0),
        ("Scenario B: Single-Position Lockout", "PositionsTotal() == 0 (Strict single position, ~8m hold)", n_scen_b, scen_b_matched, scen_b_rec, scen_b_prec, scen_b_lockout),
        ("Scenario C: Single-Position + 2m Cooldown", "PositionsTotal() == 0 + 2-minute post-close cooldown", n_scen_c, scen_c_matched, scen_c_rec, scen_c_prec, scen_c_lockout)
    ]

    for name, desc, n_exec, matched, rec, prec, lockout in scenarios:
        gate_records.append({
            'analysis_type': 'Position Lockout Causal Test',
            'universe_name': name,
            'description': desc,
            'bars_count': n_raw_signals,
            'bars_pct_of_total': float(n_raw_signals / len(panel) * 100.0),
            'real_trades_captured': matched,
            'real_trades_pct': rec,
            'base_rate_pct': float(matched / n_exec * 100.0) if n_exec > 0 else 0.0,
            'one_in_n_bars': int(n_exec / matched) if matched > 0 else 0,
            'executed_trades': n_exec,
            'execution_precision_pct': prec,
            'concurrency_lockout_pct': lockout
        })
        print(f"{name:<42} | Executed: {n_exec:>6} | Matched: {matched:>3} / 423 ({rec:>5.2f}%) | Precision: {prec:>5.2f}% | Lockout Suppressed: {lockout:>5.2f}%")

    flat_df = pd.DataFrame(gate_records)
    out_path = OUTPUTS_DIR / "phase8e_flat_state_analysis.csv"
    flat_df.to_csv(out_path, index=False)
    print(f"\n[PASS] Successfully generated Flat-State Analysis: {out_path}")
    print(f"Completed in {time.time() - t0:.2f}s\n")
    return flat_df

if __name__ == "__main__":
    run_flat_state_and_lockout_analysis()
