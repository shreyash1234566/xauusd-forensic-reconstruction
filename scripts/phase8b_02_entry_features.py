"""
Phase 8B - Stage 2: Pre-Entry Feature Extraction & Distribution Analysis
Extracts multi-timeframe and clock features for all 423 trades and counterfactual bars.
Deterministic Cheap stage (~1-2 seconds).
"""

from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUTS_DIR = ROOT / "outputs"
PANEL_PATH = DATA_DIR / "processed" / "decision_panel.parquet"
RECON_PATH = OUTPUTS_DIR / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
OUTPUT_DIR = OUTPUTS_DIR / "strategy_reconstruction"

def main():
    print("=================================================================")
    print("PHASE 8B - STAGE 02: PRE-ENTRY FEATURE EXTRACTION")
    print("=================================================================")

    df_panel = pd.read_parquet(PANEL_PATH)
    recon = pd.read_csv(RECON_PATH)

    df_panel['dt'] = pd.to_datetime(df_panel['dt'])
    df_panel['hour_eet'] = (df_panel['utc_hour'] + 3) % 24

    trade_panel = df_panel[df_panel['is_trade'] == 1].copy()
    non_trade_panel = df_panel[df_panel['is_trade'] == 0].copy()

    print(f"Total Market Bars: {len(df_panel):,}")
    print(f"Trade Bars: {len(trade_panel)} | Counterfactual Non-Trade Bars: {len(non_trade_panel):,}")

    # Feature List
    feature_cols = [c for c in df_panel.columns if c not in ['dt', 'is_trade', 'trade_dir', 'hour_eet']]

    # Compute Statistical Separation (Cohen's d) between Trades and Non-Trades
    effect_sizes = []
    for f in feature_cols:
        t_vals = trade_panel[f].dropna()
        nt_vals = non_trade_panel[f].dropna()
        if len(t_vals) > 0 and len(nt_vals) > 0:
            mean_t, std_t = t_vals.mean(), t_vals.std()
            mean_nt, std_nt = nt_vals.mean(), nt_vals.std()
            pooled_std = np.sqrt(((len(t_vals)-1)*std_t**2 + (len(nt_vals)-1)*std_nt**2) / (len(t_vals)+len(nt_vals)-2))
            d = (mean_t - mean_nt) / (pooled_std + 1e-9)
            effect_sizes.append({
                'feature': f,
                'trade_mean': mean_t,
                'non_trade_mean': mean_nt,
                'trade_std': std_t,
                'non_trade_std': std_nt,
                'cohens_d': d,
                'abs_d': abs(d)
            })

    effect_df = pd.DataFrame(effect_sizes).sort_values('abs_d', ascending=False)
    print("\nTop 10 Pre-Entry Features Separating Trade vs Non-Trade Bars (|d|):")
    print(effect_df[['feature', 'trade_mean', 'non_trade_mean', 'cohens_d']].head(10).to_string(index=False))

    # Direction Separation (Buy vs Sell)
    buys = trade_panel[trade_panel['trade_dir'] == 1]
    sells = trade_panel[trade_panel['trade_dir'] == 0]
    dir_effects = []
    for f in feature_cols:
        b_vals = buys[f].dropna()
        s_vals = sells[f].dropna()
        if len(b_vals) > 0 and len(s_vals) > 0:
            mean_b, std_b = b_vals.mean(), b_vals.std()
            mean_s, std_s = sells[f].mean(), sells[f].std()
            pooled_std = np.sqrt(((len(b_vals)-1)*std_b**2 + (len(s_vals)-1)*std_s**2) / (len(buys)+len(sells)-2))
            d = (mean_b - mean_s) / (pooled_std + 1e-9)
            dir_effects.append({
                'feature': f,
                'buy_mean': mean_b,
                'sell_mean': mean_s,
                'cohens_d': d,
                'abs_d': abs(d)
            })

    dir_df = pd.DataFrame(dir_effects).sort_values('abs_d', ascending=False)
    print("\nTop 10 Pre-Entry Features Separating Buy vs Sell Trades (|d|):")
    print(dir_df[['feature', 'buy_mean', 'sell_mean', 'cohens_d']].head(10).to_string(index=False))

    # Save outputs
    out_path = OUTPUT_DIR / "phase8b_trade_features.csv"
    trade_panel.to_csv(out_path, index=False)
    print(f"\n[PASS] Saved trade features dataset: {out_path} ({len(trade_panel)} rows)")
    print("STAGE 02 COMPLETE.\n")

if __name__ == "__main__":
    main()
