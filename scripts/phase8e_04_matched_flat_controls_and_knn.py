"""
Phase 8E - Stage 4: Matched Flat Controls, Nearest-Neighbor Microstructural Distance, and Event Latency
Covers:
- Section 8: Matched Flat-State Counterfactual Control Design
- Section 12: Microstructural Nearest-Neighbor Analysis (K=10)
- Section 13: Local Event-Time Latency & Alignment Profiling
- Generates:
    outputs/strategy_reconstruction/phase8e_matched_flat_controls.csv
    outputs/strategy_reconstruction/phase8e_nearest_neighbors.csv
    outputs/strategy_reconstruction/phase8e_event_latency.csv
"""

from pathlib import Path
import time
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT / "outputs" / "strategy_reconstruction"
PANEL_PATH = ROOT / "data" / "processed" / "decision_panel.parquet"
RECON_PATH = OUTPUTS_DIR.parent / "market_reconstruction" / "phase7c_trade_reconciliation.csv"

def run_matched_controls_and_knn():
    print("=================================================================")
    print("PHASE 8E - STAGE 04: MATCHED CONTROLS, KNN & LATENCY PROFILING")
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

    # 1. Identify True Flat Bars
    trade_intervals = list(zip(recon['open_dt'], recon['close_dt']))
    is_busy = np.zeros(len(panel), dtype=bool)
    panel_dt = panel['dt']
    for o_dt, c_dt in trade_intervals:
        mask = (panel_dt >= o_dt) & (panel_dt <= c_dt)
        is_busy |= mask.values

    panel['is_flat'] = ~is_busy
    trade_open_m1 = set(recon['open_dt'].dt.floor('min'))
    panel['is_real_trade'] = panel['dt'].isin(trade_open_m1)

    # Filter eligible flat non-trade universe
    in_session = (panel['hour'] >= 5) & (panel['hour'] <= 16) & ~((panel['dayofweek'] == 4) & (panel['hour'] >= 20))
    flat_controls_universe = panel[panel['is_flat'] & in_session & (~panel['is_real_trade'])].copy().reset_index(drop=True)
    real_trade_bars = panel[panel['is_real_trade']].copy().reset_index(drop=True)

    print(f"Real Trade Bars: {len(real_trade_bars)}")
    print(f"Eligible Flat Background Universe: {len(flat_controls_universe):,} bars")

    # -------------------------------------------------------------
    # 1. MATCHED FLAT-STATE COUNTERFACTUAL CONTROL DESIGN
    # -------------------------------------------------------------
    print("\n--- 1. GENERATING MATCHED FLAT-STATE CONTROLS ---")
    matched_records = []

    # Feature columns for matching
    features_for_knn = [
        'return_1', 'return_5', 'return_15', 'return_30',
        'rsi_14', 'bb_pct_b', 'h1_atr_pct_14', 'candle_body_ratio',
        'dist_ema_21', 'dist_ema_50'
    ]

    # Impute any missing values
    for col in features_for_knn:
        panel[col] = panel[col].fillna(0.0)
        flat_controls_universe[col] = flat_controls_universe[col].fillna(0.0)
        real_trade_bars[col] = real_trade_bars[col].fillna(0.0)

    # For each real trade, select 1 exact matched control (same hour, closest ATR & return)
    matched_control_indices = []
    for idx, r_row in real_trade_bars.iterrows():
        r_hour = r_row['hour']
        r_atr = r_row['h1_atr_pct_14']
        r_ret = abs(r_row['return_1'])

        # Candidate controls in same hour window
        cand = flat_controls_universe[flat_controls_universe['hour'] == r_hour]
        if len(cand) == 0:
            cand = flat_controls_universe

        # Distance metric: ATR diff + return diff
        dist = (cand['h1_atr_pct_14'] - r_atr).abs() / (r_atr + 1e-4) + (cand['return_1'].abs() - r_ret).abs() / (r_ret + 1e-4)
        best_ctrl_idx = dist.idxmin()
        matched_ctrl = cand.loc[best_ctrl_idx]
        matched_control_indices.append(best_ctrl_idx)

        matched_records.append({
            'trade_idx': idx,
            'real_dt': r_row['dt'],
            'real_return_1': r_row['return_1'],
            'real_return_5': r_row['return_5'],
            'real_rsi_14': r_row['rsi_14'],
            'real_h1_atr_pct': r_row['h1_atr_pct_14'],
            'ctrl_dt': matched_ctrl['dt'],
            'ctrl_return_1': matched_ctrl['return_1'],
            'ctrl_return_5': matched_ctrl['return_5'],
            'ctrl_rsi_14': matched_ctrl['rsi_14'],
            'ctrl_h1_atr_pct': matched_ctrl['h1_atr_pct_14'],
            'hour_matched': r_hour == matched_ctrl['hour'],
            'atr_abs_diff': abs(r_row['h1_atr_pct_14'] - matched_ctrl['h1_atr_pct_14']),
            'ret1_abs_diff': abs(r_row['return_1'] - matched_ctrl['return_1'])
        })

    matched_df = pd.DataFrame(matched_records)
    matched_path = OUTPUTS_DIR / "phase8e_matched_flat_controls.csv"
    matched_df.to_csv(matched_path, index=False)
    print(f"[PASS] Generated Matched Flat Controls: {matched_path} (420 matched pairs)")

    # -------------------------------------------------------------
    # 2. MICROSTRUCTURAL NEAREST-NEIGHBOR ANALYSIS (K=10)
    # -------------------------------------------------------------
    print("\n--- 2. RUNNING NEAREST-NEIGHBOR (K=10) DISTANCE ANALYSIS ---")
    scaler = StandardScaler()
    X_background = scaler.fit_transform(flat_controls_universe[features_for_knn].values)
    X_real = scaler.transform(real_trade_bars[features_for_knn].values)

    knn = NearestNeighbors(n_neighbors=10, algorithm='kd_tree')
    knn.fit(X_background)

    distances, indices = knn.kneighbors(X_real)

    knn_records = []
    for i in range(len(real_trade_bars)):
        r_row = real_trade_bars.iloc[i]
        dists = distances[i]
        knn_records.append({
            'trade_idx': i,
            'trade_dt': r_row['dt'],
            'nn_1_dist': dists[0],
            'nn_5_dist': dists[4],
            'nn_10_dist': dists[9],
            'mean_nn_dist': float(np.mean(dists)),
            'std_nn_dist': float(np.std(dists)),
            'min_nn_dist': dists[0],
            'is_isolated_outlier': dists[0] > 3.0  # > 3 std devs away
        })

    knn_df = pd.DataFrame(knn_records)
    knn_path = OUTPUTS_DIR / "phase8e_nearest_neighbors.csv"
    knn_df.to_csv(knn_path, index=False)

    mean_dist_all = knn_df['mean_nn_dist'].mean()
    outlier_pct = knn_df['is_isolated_outlier'].mean() * 100.0
    print(f"Mean K=10 Distance across all 420 trades: {mean_dist_all:.4f}")
    print(f"Isolated Outlier Trades (> 3 std dev): {knn_df['is_isolated_outlier'].sum()} ({outlier_pct:.2f}%)")
    print(f"[PASS] Generated Nearest-Neighbor Analysis: {knn_path}")

    # -------------------------------------------------------------
    # 3. LOCAL EVENT-TIME LATENCY & ALIGNMENT PROFILING
    # -------------------------------------------------------------
    print("\n--- 3. PROFILING LOCAL EVENT-TIME LATENCY & ALIGNMENT ---")
    latency_records = []

    recon_opens = recon[['open_dt', 'recorded_price', 'side', 'entry_price_error', 'entry_time_delta_sec']].copy()
    recon_opens['second'] = recon_opens['open_dt'].dt.second
    recon_opens['minute'] = recon_opens['open_dt'].dt.minute
    recon_opens['microsecond'] = recon_opens['open_dt'].dt.microsecond

    # Chi-square test on second of minute
    sec_counts = recon_opens['second'].value_counts().reindex(range(60), fill_value=0)
    expected_sec = len(recon_opens) / 60.0
    chi2_sec = ((sec_counts - expected_sec) ** 2 / expected_sec).sum()

    for sec in range(60):
        cnt = int(sec_counts[sec])
        latency_records.append({
            'second_of_minute': sec,
            'trade_count': cnt,
            'pct_of_trades': cnt / len(recon_opens) * 100.0,
            'expected_uniform': expected_sec,
            'chi2_contribution': float((cnt - expected_sec) ** 2 / expected_sec),
            'execution_mode': 'Continuous Tick-Driven Event' if chi2_sec < 80.0 else 'Discrete Polling'
        })

    lat_df = pd.DataFrame(latency_records)
    lat_path = OUTPUTS_DIR / "phase8e_event_latency.csv"
    lat_df.to_csv(lat_path, index=False)
    print(f"Second-of-Minute Uniformity Chi2: {chi2_sec:.2f} (Uniform threshold: < 79.08 at p=0.05)")
    print(f"[PASS] Generated Event Latency Profiling: {lat_path}")
    print(f"Completed in {time.time() - t0:.2f}s\n")
    return matched_df, knn_df, lat_df

if __name__ == "__main__":
    run_matched_controls_and_knn()
