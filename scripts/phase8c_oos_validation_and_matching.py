"""
Phase 8C - Stage 6: Trade-by-Trade Comparison, Match Tolerance Bands & Chronological OOS Validation
Covers:
- Section 4: Strict vs Relaxed Match Criteria (Tolerance Bands 1 to 4)
- Section 17: Complete 423-Trade by Trade Comparison Dataset (phase8c_trade_by_trade_comparison.csv)
- Section 18: Chronological 3-Split Out-of-Sample Validation (60% Train, 20% Val, 20% Test) with Frozen Parameters
"""

from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUTS_DIR = ROOT / "outputs"
RECON_PATH = OUTPUTS_DIR / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
GEN_TRADES_PATH = OUTPUTS_DIR / "strategy_reconstruction" / "phase8c_generated_trades.csv"
PANEL_PATH = DATA_DIR / "processed" / "decision_panel.parquet"
OUTPUT_DIR = OUTPUTS_DIR / "strategy_reconstruction"

def main():
    print("=================================================================")
    print("PHASE 8C - STAGE 06: TRADE COMPARISON & OUT-OF-SAMPLE VALIDATION")
    print("=================================================================")

    recon = pd.read_csv(RECON_PATH)
    recon['open_dt_utc'] = pd.to_datetime(recon['open_time_utc'])
    recon['close_dt_utc'] = pd.to_datetime(recon['close_time_utc'])
    recon['obs_duration_min'] = (recon['close_dt_utc'] - recon['open_dt_utc']).dt.total_seconds() / 60.0
    recon['obs_pnl'] = recon['recorded_pnl'].astype(float)
    recon['obs_price'] = recon['recorded_price'].astype(float)
    recon['obs_volume'] = recon['volume'].astype(float)

    gen_trades = pd.read_csv(GEN_TRADES_PATH)
    gen_trades['entry_dt'] = pd.to_datetime(gen_trades['entry_time'])
    gen_trades['exit_dt'] = pd.to_datetime(gen_trades['exit_time'])
    gen_trades['gen_dur_min'] = gen_trades['holding_minutes'].astype(float)
    gen_trades['gen_pnl'] = gen_trades['pnl'].astype(float)
    gen_trades['gen_price'] = gen_trades['entry_price'].astype(float)
    gen_trades['gen_volume'] = gen_trades['lot_size'].astype(float)

    n_obs = len(recon)
    n_gen = len(gen_trades)
    print(f"Loaded {n_obs} observed trades and {n_gen:,} autonomously generated trades.\n")

    # -------------------------------------------------------------
    # 1. SECTION 4: STRICT VS RELAXED MATCH CRITERIA
    # -------------------------------------------------------------
    print("--- 1. SECTION 4: MATCH TOLERANCE BANDS BENCHMARK ---")

    bands = [
        ("Band 1 (Strict: <=1m, Price <=$0.50, Dur <=20%, Same Side)", 1.0, 0.50, 0.20, True),
        ("Band 2 (Moderate: <=5m, Price <=$1.50, Dur <=50%, Same Side)", 5.0, 1.50, 0.50, True),
        ("Band 3 (Relaxed: <=15m, Price <=$3.00, Same Side)", 15.0, 3.00, None, True),
        ("Band 4 (Direction-Only: <=60m, Same Side)", 60.0, None, None, True)
    ]

    band_results = []
    for b_name, max_t, max_p, max_dur_pct, same_side in bands:
        matched_obs_set = set()
        matched_gen_set = set()

        for i, r_obs in recon.iterrows():
            t_o = r_obs['open_dt_utc']
            p_o = r_obs['obs_price']
            dur_o = r_obs['obs_duration_min']
            side_o = r_obs['side']

            # filter candidate generated trades
            diffs_t = (gen_trades['entry_dt'] - t_o).abs().dt.total_seconds() / 60.0
            mask = (diffs_t <= max_t)

            if same_side:
                mask = mask & (gen_trades['side'] == side_o)
            if max_p is not None:
                mask = mask & ((gen_trades['gen_price'] - p_o).abs() <= max_p)
            if max_dur_pct is not None:
                mask = mask & ((gen_trades['gen_dur_min'] - dur_o).abs() / max(dur_o, 0.1) <= max_dur_pct)

            cand = gen_trades[mask]
            if len(cand) > 0:
                best_idx = diffs_t[mask].idxmin()
                matched_obs_set.add(i)
                matched_gen_set.add(best_idx)

        n_matched = len(matched_obs_set)
        n_unmatched = n_obs - n_matched
        rec_pct = n_matched / n_obs * 100.0
        tot_gen_matches = len(matched_gen_set)
        fp_count = n_gen - tot_gen_matches
        prec_pct = tot_gen_matches / n_gen * 100.0 if n_gen > 0 else 0.0

        band_results.append({
            'tolerance_band': b_name,
            'matched_trades': n_matched,
            'recall_pct': rec_pct,
            'unmatched_trades': n_unmatched,
            'total_generated_trades': n_gen,
            'false_positives': fp_count,
            'precision_pct': prec_pct
        })

    band_df = pd.DataFrame(band_results)
    out_band_path = OUTPUT_DIR / "phase8c_match_tolerance_bands.csv"
    band_df.to_csv(out_band_path, index=False)
    print(band_df[['tolerance_band', 'matched_trades', 'recall_pct', 'false_positives', 'precision_pct']].to_string(index=False))

    # -------------------------------------------------------------
    # 2. SECTION 17: TRADE-BY-TRADE COMPARISON (423 ROWS)
    # -------------------------------------------------------------
    print("\n--- 2. SECTION 17: TRADE-BY-TRADE RECONCILIATION ---")
    trade_comparisons = []
    used_gen_indices = set()

    for i, r_obs in recon.iterrows():
        t_o = r_obs['open_dt_utc']
        p_o = r_obs['obs_price']
        dur_o = r_obs['obs_duration_min']
        side_o = r_obs['side']

        # Find closest generated trade within 30 minutes with same side
        diffs_t = (gen_trades['entry_dt'] - t_o).abs().dt.total_seconds() / 60.0
        mask = (diffs_t <= 30.0) & (gen_trades['side'] == side_o)

        cand = gen_trades[mask]
        if len(cand) > 0:
            best_idx = diffs_t[mask].idxmin()
            g = gen_trades.loc[best_idx]
            used_gen_indices.add(best_idx)

            t_delta = (g['entry_dt'] - t_o).total_seconds() / 60.0
            p_delta = g['gen_price'] - p_o
            dur_delta = g['gen_dur_min'] - dur_o
            pnl_delta = g['gen_pnl'] - r_obs['obs_pnl']

            if abs(t_delta) <= 1.0 and abs(p_delta) <= 0.50 and abs(dur_delta) <= 3.0:
                qual = "EXACT"
            elif abs(t_delta) <= 5.0 and abs(p_delta) <= 1.50:
                qual = "CLOSE"
            elif abs(t_delta) <= 15.0:
                qual = "LOOSE"
            else:
                qual = "DISTANT"

            trade_comparisons.append({
                'observed_ticket': r_obs['ticket'],
                'observed_open_time': r_obs['open_time_utc'],
                'observed_side': side_o,
                'observed_lot': r_obs['obs_volume'],
                'observed_entry_price': p_o,
                'observed_close_time': r_obs['close_time_utc'],
                'observed_duration_min': dur_o,
                'observed_pnl': r_obs['obs_pnl'],
                'matched_gen_ticket': g['gen_ticket'],
                'gen_open_time': g['entry_time'],
                'gen_side': g['side'],
                'gen_lot': g['gen_volume'],
                'gen_entry_price': g['gen_price'],
                'gen_close_time': g['exit_time'],
                'gen_duration_min': g['gen_dur_min'],
                'gen_pnl': g['gen_pnl'],
                'time_delta_min': t_delta,
                'price_delta_usd': p_delta,
                'duration_delta_min': dur_delta,
                'pnl_delta_usd': pnl_delta,
                'match_quality': qual
            })
        else:
            trade_comparisons.append({
                'observed_ticket': r_obs['ticket'],
                'observed_open_time': r_obs['open_time_utc'],
                'observed_side': side_o,
                'observed_lot': r_obs['obs_volume'],
                'observed_entry_price': p_o,
                'observed_close_time': r_obs['close_time_utc'],
                'observed_duration_min': dur_o,
                'observed_pnl': r_obs['obs_pnl'],
                'matched_gen_ticket': np.nan,
                'gen_open_time': None,
                'gen_side': None,
                'gen_lot': np.nan,
                'gen_entry_price': np.nan,
                'gen_close_time': None,
                'gen_duration_min': np.nan,
                'gen_pnl': np.nan,
                'time_delta_min': np.nan,
                'price_delta_usd': np.nan,
                'duration_delta_min': np.nan,
                'pnl_delta_usd': np.nan,
                'match_quality': "UNMATCHED"
            })

    comp_df = pd.DataFrame(trade_comparisons)
    out_comp_path = OUTPUT_DIR / "phase8c_trade_by_trade_comparison.csv"
    comp_df.to_csv(out_comp_path, index=False)
    print(f"[PASS] Saved full 423-trade comparison file: {out_comp_path}")
    print("\nMatch Quality Breakdown:")
    print(comp_df['match_quality'].value_counts().to_string())

    # -------------------------------------------------------------
    # 3. SECTION 18: CHRONOLOGICAL 3-SPLIT OUT-OF-SAMPLE VALIDATION
    # -------------------------------------------------------------
    print("\n--- 3. SECTION 18: CHRONOLOGICAL OUT-OF-SAMPLE VALIDATION ---")
    # Date boundaries for 60% Train, 20% Val, 20% Test
    t_min = recon['open_dt_utc'].min()
    t_max = recon['open_dt_utc'].max()
    t_train_end = t_min + (t_max - t_min) * 0.60
    t_val_end = t_min + (t_max - t_min) * 0.80

    recon['split'] = 'train'
    recon.loc[recon['open_dt_utc'] > t_train_end, 'split'] = 'val'
    recon.loc[recon['open_dt_utc'] > t_val_end, 'split'] = 'test'

    gen_trades['split'] = 'train'
    gen_trades.loc[gen_trades['entry_dt'] > t_train_end, 'split'] = 'val'
    gen_trades.loc[gen_trades['entry_dt'] > t_val_end, 'split'] = 'test'

    oos_results = []
    for sp in ['train', 'val', 'test']:
        obs_sp = recon[recon['split'] == sp]
        gen_sp = gen_trades[gen_trades['split'] == sp]

        n_o_sp = len(obs_sp)
        n_g_sp = len(gen_sp)

        # Match within 5 min
        matched_sp = 0
        for _, r_o in obs_sp.iterrows():
            d_t = (gen_sp['entry_dt'] - r_o['open_dt_utc']).abs()
            if (d_t <= pd.Timedelta(minutes=5)).any():
                matched_sp += 1

        rec_sp = matched_sp / n_o_sp * 100.0 if n_o_sp > 0 else 0.0
        prec_sp = matched_sp / n_g_sp * 100.0 if n_g_sp > 0 else 0.0
        f1_sp = (2 * prec_sp * rec_sp / (prec_sp + rec_sp)) if (prec_sp + rec_sp) > 0 else 0.0

        # Performance metrics
        obs_pnl_tot = obs_sp['obs_pnl'].sum()
        obs_wr = (obs_sp['obs_pnl'] > 0).mean() * 100.0

        gen_pnl_tot = gen_sp['gen_pnl'].sum()
        gen_wr = (gen_sp['gen_pnl'] > 0).mean() * 100.0
        gen_sharpe = (gen_sp['gen_pnl'].mean() / gen_sp['gen_pnl'].std() * np.sqrt(252 * 10)) if gen_sp['gen_pnl'].std() > 0 else 0.0

        oos_results.append({
            'split': sp.upper(),
            'obs_trade_count': n_o_sp,
            'gen_trade_count': n_g_sp,
            'matched_trades_5m': matched_sp,
            'recall_pct': rec_sp,
            'precision_pct': prec_sp,
            'f1_score': f1_sp,
            'obs_win_rate_pct': obs_wr,
            'obs_total_pnl': obs_pnl_tot,
            'gen_win_rate_pct': gen_wr,
            'gen_total_pnl': gen_pnl_tot,
            'gen_sharpe_proxy': gen_sharpe
        })

    oos_df = pd.DataFrame(oos_results)
    out_oos_path = OUTPUT_DIR / "phase8c_oos_validation_results.csv"
    oos_df.to_csv(out_oos_path, index=False)

    print(oos_df[['split', 'obs_trade_count', 'gen_trade_count', 'recall_pct', 'precision_pct', 'gen_win_rate_pct', 'gen_total_pnl']].to_string(index=False))

    print("\nSTAGE 06 COMPLETE.\n")

if __name__ == "__main__":
    main()
