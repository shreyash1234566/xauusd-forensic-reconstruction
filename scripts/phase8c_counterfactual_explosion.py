"""
Phase 8C - Stage 2: Counterfactual Explosion & Selectivity Ablation
Tests the 5-stage ablation (Session, Session+ATR, Session+ATR+Impulse, Session+ATR+Impulse+Dir, Full Entry Rule).
Computes exact capture, explosion counts, false positives, precision, recall, and odds ratios.
"""

from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUTS_DIR = ROOT / "outputs"
PANEL_PATH = DATA_DIR / "processed" / "decision_panel.parquet"
M1_PATH = DATA_DIR / "market" / "normalized" / "xauusd_m1.csv"
RECON_PATH = OUTPUTS_DIR / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
OUTPUT_DIR = OUTPUTS_DIR / "strategy_reconstruction"

def main():
    print("=================================================================")
    print("PHASE 8C - STAGE 02: COUNTERFACTUAL EXPLOSION ABLATION")
    print("=================================================================")

    dp = pd.read_parquet(PANEL_PATH)
    m1 = pd.read_csv(M1_PATH)
    dp['dt'] = pd.to_datetime(dp['dt'])
    m1['dt'] = pd.to_datetime(m1['timestamp'])

    df = pd.merge(dp, m1[['dt', 'open', 'high', 'low', 'close']], on='dt', how='inner')
    df = df.sort_values('dt').reset_index(drop=True)
    df['hour_eet'] = (df['utc_hour'] + 3) % 24
    df['impulse_dollars'] = (df['close'].shift(1) - df['open'].shift(1)).abs()
    df['impulse_sign'] = np.sign(df['close'].shift(1) - df['open'].shift(1))

    recon = pd.read_csv(RECON_PATH)
    recon['open_dt_utc'] = pd.to_datetime(recon['open_time_utc'])

    n_total_bars = len(df)
    n_observed_trades = len(recon)

    print(f"Total Market Opportunity Universe: {n_total_bars:,} bars")
    print(f"Total Observed Trades:             {n_observed_trades:,} trades (Base rate: {n_observed_trades/n_total_bars*100:.4f}%)\n")

    # Define the 5 Ablation Stages
    # Condition A: Session Only (07:00-16:00 EET)
    cond_a = df['hour_eet'].between(7, 16)

    # Condition B: Session + ATR (H1 ATR >= 0.25%)
    cond_b = cond_a & (df['h1_atr_pct_14'] >= 0.25)

    # Condition C: Session + ATR + Impulse (|Delta P| >= $0.30)
    cond_c = cond_b & (df['impulse_dollars'] >= 0.30)

    # Condition D: Session + ATR + Impulse + Direction (Impulse != 0)
    cond_d = cond_c & (df['impulse_sign'] != 0)

    # Condition E: Full Entry Rule with Single Position Simulation
    # Generate signal boolean mask
    df['sig_e'] = cond_d
    taken_mask = np.zeros(n_total_bars, dtype=bool)

    # Fast simulation of single-position blocking
    in_pos_until = -1
    dts_arr = df['dt'].values
    sig_e_arr = df['sig_e'].values
    opens_arr = df['open'].values
    closes_arr = df['close'].values
    highs_arr = df['high'].values
    lows_arr = df['low'].values
    impulse_signs = df['impulse_sign'].values

    pos_taken_indices = []
    for i in range(n_total_bars):
        if sig_e_arr[i] and i > in_pos_until:
            pos_taken_indices.append(i)
            # simulate quick exit boundary (trailing stop / sl / 45m max hold)
            side_buy = (impulse_signs[i] > 0)
            entry_p = opens_arr[i]
            peak_fav = 0.0
            exit_idx = min(i + 45, n_total_bars - 1) # max hold 45 min
            for k in range(i, min(i + 60, n_total_bars)):
                cur_h = highs_arr[k]
                cur_l = lows_arr[k]
                cur_c = closes_arr[k]
                fav = (cur_h - entry_p) if side_buy else (entry_p - cur_l)
                adv = (entry_p - cur_l) if side_buy else (cur_h - entry_p)
                if fav > peak_fav:
                    peak_fav = fav
                # SL
                if adv >= 2.50:
                    exit_idx = k
                    break
                # Trail
                if peak_fav >= 3.00:
                    cur_fav = (cur_c - entry_p) if side_buy else (entry_p - cur_c)
                    if cur_fav <= peak_fav - 1.00:
                        exit_idx = k
                        break
                if k - i >= 45:
                    exit_idx = k
                    break
            in_pos_until = exit_idx

    taken_mask[pos_taken_indices] = True
    df['cond_e'] = taken_mask

    ablations = [
        ('A. Session Only (07:00-16:00 EET)', cond_a),
        ('B. Session + ATR (H1 ATR >= 0.25%)', cond_b),
        ('C. Session + ATR + Impulse (|ΔP| >= $0.30)', cond_c),
        ('D. Session + ATR + Impulse + Direction', cond_d),
        ('E. Full Entry Rule (Single-Position Gated)', df['cond_e'])
    ]

    results = []

    # Map observed trade times to bars
    trade_bar_indices = set()
    for _, r in recon.iterrows():
        t_open = r['open_dt_utc']
        # find closest bar within 3 minutes
        diffs = (df['dt'] - t_open).abs()
        min_idx = diffs.idxmin()
        if diffs.iloc[min_idx] <= pd.Timedelta(minutes=3):
            trade_bar_indices.add(min_idx)

    print(f"Matched {len(trade_bar_indices)} trade entries uniquely to M1 bars.\n")

    for name, mask in ablations:
        active_indices = set(df[mask].index)
        captured_trades = len(trade_bar_indices.intersection(active_indices))
        total_generated = len(active_indices)
        false_positives = total_generated - captured_trades
        missed_trades = len(trade_bar_indices) - captured_trades

        precision = (captured_trades / total_generated * 100.0) if total_generated > 0 else 0.0
        recall = (captured_trades / len(trade_bar_indices) * 100.0) if len(trade_bar_indices) > 0 else 0.0

        tn = (n_total_bars - len(trade_bar_indices)) - false_positives
        fp_rate = (false_positives / (tn + false_positives) * 100.0) if (tn + false_positives) > 0 else 0.0

        # Odds Ratio
        tp = captured_trades
        fn = missed_trades
        fp = false_positives
        odds_ratio = ((tp + 0.5) * (tn + 0.5)) / ((fp + 0.5) * (fn + 0.5))

        results.append({
            'stage': name,
            'observed_captured': captured_trades,
            'observed_total': len(trade_bar_indices),
            'recall_pct': recall,
            'total_generated_bars': total_generated,
            'false_positives': false_positives,
            'precision_pct': precision,
            'fp_rate_pct': fp_rate,
            'odds_ratio': odds_ratio
        })

    res_df = pd.DataFrame(results)
    out_path = OUTPUT_DIR / "phase8c_counterfactual_explosion.csv"
    res_df.to_csv(out_path, index=False)
    print(f"[PASS] Saved counterfactual explosion table: {out_path}\n")

    print(res_df[['stage', 'observed_captured', 'recall_pct', 'total_generated_bars', 'false_positives', 'precision_pct', 'odds_ratio']].to_string(index=False))
    print("\nSTAGE 02 COMPLETE.\n")

if __name__ == "__main__":
    main()
