"""
Phase 8B - Stage 4: Counterfactual Testing & Strategy Family Falsification
Evaluates 8 candidate strategy families and matched controls across 402,401 bars.
Statistical / Deterministic stage (~2-3 seconds).
"""

from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUTS_DIR = ROOT / "outputs"
PANEL_PATH = DATA_DIR / "processed" / "decision_panel.parquet"
OUTPUT_DIR = OUTPUTS_DIR / "strategy_reconstruction"

def main():
    print("=================================================================")
    print("PHASE 8B - STAGE 04: COUNTERFACTUAL TESTING & FALSIFICATION")
    print("=================================================================")

    df_panel = pd.read_parquet(PANEL_PATH)
    df_panel['dt'] = pd.to_datetime(df_panel['dt'])
    df_panel['hour_eet'] = (df_panel['utc_hour'] + 3) % 24
    df_panel['dow'] = df_panel['dt'].dt.dayofweek

    total_bars = len(df_panel)
    total_trades = df_panel['is_trade'].sum()
    print(f"Loaded {total_bars:,} bars ({total_trades} trade entries, {total_bars - total_trades:,} negative bars)")

    # 1. 8 Candidate Strategy Families
    families = [
        {
            'name': '1. Trend Continuation (EMA8 > EMA21 + Time)',
            'rule': (df_panel['hour_eet'].between(7, 16)) & (df_panel['dist_ema_21'].abs() > 2.0)
        },
        {
            'name': '2. Momentum Breakout (|Return1| > 2 sigma + ATR + Time)',
            'rule': (df_panel['hour_eet'].between(7, 16)) & (df_panel['h1_atr_pct_14'] > 0.33) & (df_panel['return_1'].abs() > 3.0)
        },
        {
            'name': '3. Mean Reversion (RSI > 70 or < 30 + Time)',
            'rule': (df_panel['hour_eet'].between(7, 16)) & ((df_panel['rsi_14'] > 70) | (df_panel['rsi_14'] < 30))
        },
        {
            'name': '4. Volatility Expansion (ATR > 0.40% + Time)',
            'rule': (df_panel['hour_eet'].between(7, 16)) & (df_panel['h1_atr_pct_14'] > 0.40)
        },
        {
            'name': '5. Bollinger Band Breakout (%B > 1.0 or < 0.0 + Time)',
            'rule': (df_panel['hour_eet'].between(7, 16)) & ((df_panel['bb_pct_b'] > 1.0) | (df_panel['bb_pct_b'] < 0.0))
        },
        {
            'name': '6. Candlestick Reversal (Wick Ratio > 0.6 + Time)',
            'rule': (df_panel['hour_eet'].between(7, 16)) & ((df_panel['lower_wick_ratio'] > 0.60) | (df_panel['upper_wick_ratio'] > 0.60))
        },
        {
            'name': '7. Micro-Impulse Scalp (|Return_1| > 2.0 bps + Time)',
            'rule': (df_panel['hour_eet'].between(7, 16)) & (df_panel['return_1'].abs() > 2.0)
        },
        {
            'name': '8. Pure Time Window (07:00-16:00 EET Only)',
            'rule': df_panel['hour_eet'].between(7, 16)
        }
    ]

    fam_results = []
    for fam in families:
        mask = fam['rule']
        tp = int((mask & (df_panel['is_trade'] == 1)).sum())
        fn = int(total_trades - tp)
        fp = int((mask & (df_panel['is_trade'] == 0)).sum())
        tn = int((~mask & (df_panel['is_trade'] == 0)).sum())
        tot_trig = int(mask.sum())

        precision = (tp / tot_trig * 100.0) if tot_trig > 0 else 0.0
        recall = (tp / total_trades * 100.0)
        fpr = (fp / (fp + tn) * 100.0) if (fp + tn) > 0 else 0.0

        # Odds Ratio
        odds_ratio = ((tp + 0.5) * (tn + 0.5)) / ((fp + 0.5) * (fn + 0.5))

        fam_results.append({
            'family_name': fam['name'],
            'trades_captured': tp,
            'unexplained_trades': fn,
            'counterfactual_fps': fp,
            'total_bars_triggered': tot_trig,
            'recall_pct': recall,
            'precision_pct': precision,
            'false_positive_rate_pct': fpr,
            'odds_ratio': odds_ratio
        })

    fam_df = pd.DataFrame(fam_results)
    out_fam_path = OUTPUT_DIR / "phase8b_counterfactual_controls.csv"
    fam_df.to_csv(out_fam_path, index=False)
    print(f"[PASS] Saved counterfactual controls & falsification results: {out_fam_path}")

    print("\n8 Candidate Strategy Families Falsification Table:")
    print(fam_df[['family_name', 'trades_captured', 'counterfactual_fps', 'recall_pct', 'precision_pct', 'odds_ratio']].to_string(index=False))

    # 2. Time Filter Robustness across Train (60%), Val (20%), Test (20%)
    print("\nEvaluating Time Windows across 3 Chronological Splits...")
    n_tot = len(df_panel)
    i_tr = int(n_tot * 0.60)
    i_va = int(n_tot * 0.80)

    splits = [
        ('Train (60%)', df_panel.iloc[:i_tr]),
        ('Val (20%)', df_panel.iloc[i_tr:i_va]),
        ('Test (20%)', df_panel.iloc[i_va:])
    ]

    time_windows = {
        'A: 07:00-16:00 EET': (7, 16),
        'B: 06:00-15:00 EET': (6, 15),
        'C: 08:00-16:00 EET': (8, 16),
        'D: 08:00-12:00 EET': (8, 12)
    }

    for name, (h_s, h_e) in time_windows.items():
        print(f"\nWindow {name}:")
        for s_name, s_df in splits:
            tot_s = s_df['is_trade'].sum()
            in_w = (s_df['hour_eet'] >= h_s) & (s_df['hour_eet'] <= h_e)
            cap = (in_w & (s_df['is_trade'] == 1)).sum()
            b_cnt = in_w.sum()
            rec = cap / tot_s * 100.0 if tot_s > 0 else 0.0
            prec = cap / b_cnt * 100.0 if b_cnt > 0 else 0.0
            print(f"  {s_name:12s}: Captured {cap}/{tot_s} ({rec:.1f}%), Bars: {b_cnt:,}, Precision: {prec:.4f}%")

    # 3. Volatility Filter Grid
    print("\nEvaluating Volatility Filter Grid (H1 ATR%):")
    for thr in [0.25, 0.30, 0.33, 0.35, 0.40]:
        in_vol = df_panel['h1_atr_pct_14'] >= thr
        cap = (in_vol & (df_panel['is_trade'] == 1)).sum()
        fps = (in_vol & (df_panel['is_trade'] == 0)).sum()
        rec = cap / total_trades * 100.0
        prec = cap / in_vol.sum() * 100.0
        print(f"  ATR >= {thr:.2f}%: Captured {cap}/{total_trades} ({rec:.1f}%), False Positives: {fps:,}, Precision: {prec:.4f}%")

    print("\nSTAGE 04 COMPLETE.\n")

if __name__ == "__main__":
    main()
