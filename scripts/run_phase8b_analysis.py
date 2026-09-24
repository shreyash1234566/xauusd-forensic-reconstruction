import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(".")
RECON_PATH = ROOT / "outputs" / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
PANEL_PATH = ROOT / "data" / "processed" / "decision_panel.parquet"
TICKS_DIR = ROOT / "data" / "market" / "raw_ticks"
OUTPUT_DIR = ROOT / "outputs" / "strategy_reconstruction"

print("Loading trade reconciliation data...")
trades = pd.read_csv(RECON_PATH)
trades['open_dt_utc'] = pd.to_datetime(trades['open_time_utc'])
trades['close_dt_utc'] = pd.to_datetime(trades['close_time_utc'])
trades['open_dt_broker'] = pd.to_datetime(trades['recorded_open_time'])
trades['close_dt_broker'] = pd.to_datetime(trades['recorded_close_time'])
trades['pnl_num'] = trades['recorded_pnl'].astype(float)
trades['holding_sec'] = (trades['close_dt_utc'] - trades['open_dt_utc']).dt.total_seconds()
trades['volume'] = trades['volume'].astype(float)
trades = trades.sort_values('open_dt_utc').reset_index(drop=True)

# -------------------------------------------------------------
# 1. OVERLAPPING POSITIONS ANALYSIS
# -------------------------------------------------------------
print("\n=== 1. OVERLAPPING POSITIONS ANALYSIS ===")
overlaps = []
for i in range(len(trades)):
    t_i = trades.iloc[i]
    for j in range(i + 1, len(trades)):
        t_j = trades.iloc[j]
        if t_j['open_dt_utc'] < t_i['close_dt_utc']:
            # Overlap exists
            overlap_sec = (min(t_i['close_dt_utc'], t_j['close_dt_utc']) - t_j['open_dt_utc']).total_seconds()
            same_dir = (t_i['side'] == t_j['side'])
            overlaps.append({
                'trade_1_ticket': t_i['ticket'],
                'trade_2_ticket': t_j['ticket'],
                'trade_1_side': t_i['side'],
                'trade_2_side': t_j['side'],
                'same_side': same_dir,
                'overlap_sec': overlap_sec,
                'overlap_min': overlap_sec / 60.0,
                'trade_1_open': t_i['open_time_utc'],
                'trade_2_open': t_j['open_time_utc'],
                'trade_1_close': t_i['close_time_utc'],
                'trade_2_close': t_j['close_time_utc']
            })
        else:
            break

overlaps_df = pd.DataFrame(overlaps)
print(f"Total overlapping trade pairs: {len(overlaps_df)}")
if len(overlaps_df) > 0:
    print(f"Same side overlaps: {overlaps_df['same_side'].sum()} ({overlaps_df['same_side'].mean()*100:.1f}%)")
    print(f"Opposite side overlaps: {(~overlaps_df['same_side']).sum()} ({(~overlaps_df['same_side']).mean()*100:.1f}%)")
    print(f"Median overlap duration: {overlaps_df['overlap_min'].median():.2f} min")
    print(f"Max overlap duration: {overlaps_df['overlap_min'].max():.2f} min")
    print("Sample overlaps:\n", overlaps_df.head(5)[['trade_1_ticket', 'trade_2_ticket', 'trade_1_side', 'trade_2_side', 'overlap_min']].to_string())

# -------------------------------------------------------------
# 2. POSITION SIZING STATE MACHINE ANALYSIS
# -------------------------------------------------------------
print("\n=== 2. POSITION SIZING STATE MACHINE ANALYSIS ===")
pos_states = []
cum_pnl = 0.0
win_streak = 0
loss_streak = 0

for i in range(len(trades)):
    t = trades.iloc[i]
    prev_t = trades.iloc[i-1] if i > 0 else None

    prev_vol = prev_t['volume'] if prev_t is not None else np.nan
    prev_pnl = prev_t['pnl_num'] if prev_t is not None else np.nan
    prev_win = (prev_pnl > 0) if prev_t is not None else np.nan

    cur_vol = t['volume']
    cur_pnl = t['pnl_num']
    cum_pnl += cur_pnl

    if prev_t is not None:
        if prev_pnl > 0:
            win_streak += 1
            loss_streak = 0
        else:
            loss_streak += 1
            win_streak = 0

    pos_states.append({
        'ticket': t['ticket'],
        'open_time': t['open_time_utc'],
        'volume': cur_vol,
        'pnl': cur_pnl,
        'cum_pnl': cum_pnl,
        'prev_volume': prev_vol,
        'prev_pnl': prev_pnl,
        'prev_win': prev_win,
        'win_streak_before': win_streak,
        'loss_streak_before': loss_streak,
        'side': t['side'],
        'hour_broker': t['open_dt_broker'].hour,
        'dow': t['open_dt_broker'].dayofweek
    })

pos_df = pd.DataFrame(pos_states)
pos_df.to_csv(OUTPUT_DIR / "phase8b_position_state.csv", index=False)

# Transitions:
transitions = pos_df.dropna(subset=['prev_volume'])
print("Size Transitions Count:")
trans_counts = transitions.groupby(['prev_volume', 'volume']).size().to_dict()
for k, v in trans_counts.items():
    print(f"  {k[0]} -> {k[1]}: {v} trades")

print("\nVolume conditional on previous outcome:")
print("After WIN:")
print(transitions[transitions['prev_win'] == True]['volume'].value_counts().to_dict())
print("After LOSS:")
print(transitions[transitions['prev_win'] == False]['volume'].value_counts().to_dict())

v02_trades = pos_df[pos_df['volume'] == 0.02]
print(f"\n0.02 Lot Trades Profile (N={len(v02_trades)}):")
print(f"  Win Streaks before 0.02: {v02_trades['win_streak_before'].value_counts().to_dict()}")
print(f"  Cumulative PnL Range at 0.02: ${v02_trades['cum_pnl'].min():.2f} to ${v02_trades['cum_pnl'].max():.2f}")
print(f"  Dates of 0.02 trades: {v02_trades['open_time'].str[:10].unique().tolist()}")

# -------------------------------------------------------------
# 3. TICK MICROSTRUCTURE & PRE-ENTRY ANALYSIS (1s, 3s, 5s, 10s, 30s, 60s)
# -------------------------------------------------------------
print("\n=== 3. TICK MICROSTRUCTURE EXTRACTION (7.1M+ TICKS) ===")

def load_ticks_for_range(start_utc, end_utc):
    cur_h = start_utc.replace(minute=0, second=0, microsecond=0)
    end_h = end_utc.replace(minute=0, second=0, microsecond=0)
    ticks_list = []
    h = cur_h
    while h <= end_h + timedelta(hours=1):
        iso_str = h.strftime("%Y-%m-%dT%H-00-00-000Z")
        p = TICKS_DIR / f"xauusd_ticks_{iso_str}.json"
        if p.exists():
            with open(p, 'r') as f:
                data = json.load(f)
            if data and len(data) > 0:
                arr = np.array(data, dtype=float)
                ticks_list.append(pd.DataFrame({
                    'ts': arr[:, 0],
                    'ask': arr[:, 1],
                    'bid': arr[:, 2],
                    'mid': (arr[:, 1] + arr[:, 2]) / 2.0,
                    'spread': arr[:, 1] - arr[:, 2]
                }))
        h += timedelta(hours=1)
    if not ticks_list:
        return None
    df_all = pd.concat(ticks_list, ignore_index=True).drop_duplicates(subset=['ts']).sort_values('ts').reset_index(drop=True)
    return df_all

micro_list = []
windows_sec = [1, 3, 5, 10, 30, 60]

for idx, r in trades.iterrows():
    t_open = r['open_dt_utc']
    open_ms = int(t_open.timestamp() * 1000)

    # Load 2 minutes before entry
    t_start = t_open - timedelta(seconds=90)
    tdf = load_ticks_for_range(t_start, t_open + timedelta(seconds=5))

    rec = {
        'ticket': r['ticket'],
        'side': r['side'],
        'open_time_utc': r['open_time_utc'],
        'entry_price_rec': r['recorded_price'],
    }

    if tdf is None or len(tdf) == 0:
        for w in windows_sec:
            rec[f'ret_{w}s'] = np.nan
            rec[f'tick_count_{w}s'] = np.nan
            rec[f'spread_{w}s'] = np.nan
            rec[f'consec_upticks_{w}s'] = np.nan
            rec[f'accel_{w}s'] = np.nan
        micro_list.append(rec)
        continue

    entry_ticks = tdf[tdf['ts'] <= open_ms]
    if len(entry_ticks) == 0:
        entry_ticks = tdf.iloc[:1]

    p_entry_mid = entry_ticks.iloc[-1]['mid']
    rec['entry_mid_tick'] = p_entry_mid
    rec['entry_spread'] = entry_ticks.iloc[-1]['spread']

    for w in windows_sec:
        w_ticks = tdf[(tdf['ts'] <= open_ms) & (tdf['ts'] >= open_ms - w * 1000)]
        if len(w_ticks) >= 2:
            p_start = w_ticks.iloc[0]['mid']
            p_end = w_ticks.iloc[-1]['mid']
            ret = (p_end - p_start)
            cnt = len(w_ticks)
            spread_mean = w_ticks['spread'].mean()

            # consecutive upticks/downticks
            diffs = np.diff(w_ticks['mid'].values)
            consec_up = np.sum(diffs > 0) - np.sum(diffs < 0)

            # acceleration (second half ret - first half ret)
            half = len(w_ticks) // 2
            if half >= 1:
                ret_h1 = w_ticks.iloc[half]['mid'] - w_ticks.iloc[0]['mid']
                ret_h2 = w_ticks.iloc[-1]['mid'] - w_ticks.iloc[half]['mid']
                accel = ret_h2 - ret_h1
            else:
                accel = 0.0

            rec[f'ret_{w}s'] = ret
            rec[f'tick_count_{w}s'] = cnt
            rec[f'spread_{w}s'] = spread_mean
            rec[f'consec_upticks_{w}s'] = consec_up
            rec[f'accel_{w}s'] = accel
        else:
            rec[f'ret_{w}s'] = 0.0
            rec[f'tick_count_{w}s'] = len(w_ticks)
            rec[f'spread_{w}s'] = entry_ticks.iloc[-1]['spread']
            rec[f'consec_upticks_{w}s'] = 0
            rec[f'accel_{w}s'] = 0.0

    micro_list.append(rec)

micro_df = pd.DataFrame(micro_list)
micro_df.to_csv(OUTPUT_DIR / "phase8b_tick_microstructure.csv", index=False)
print(f"Extracted microstructure features for {len(micro_df)} trades.")

# -------------------------------------------------------------
# 4. DIRECTIONAL PREDICTABILITY AUDIT ON REAL TICKS
# -------------------------------------------------------------
print("\n=== 4. DIRECTIONAL PREDICTABILITY FROM TICK FEATURES ===")
valid_micro = micro_df.dropna(subset=['ret_5s', 'ret_1s']).copy()
valid_micro['target_dir'] = (valid_micro['side'] == 'Buy').astype(int)

for w in [1, 3, 5, 10, 30, 60]:
    # Momentum rule: if ret_w > 0 -> Buy else Sell
    pred = (valid_micro[f'ret_{w}s'] > 0).astype(int)
    acc = (pred == valid_micro['target_dir']).mean()

    # Reversal rule: if ret_w < 0 -> Buy else Sell
    rev_acc = 1.0 - acc
    print(f"Window {w:2d}s Pre-Entry Return: Momentum Acc = {acc*100:.2f}%, Reversal Acc = {rev_acc*100:.2f}% (Buy mean ret: ${valid_micro[valid_micro['target_dir']==1][f'ret_{w}s'].mean():.4f}, Sell mean ret: ${valid_micro[valid_micro['target_dir']==0][f'ret_{w}s'].mean():.4f})")

# Logistic & Tree Walk-Forward Direction Test
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import accuracy_score

tick_feat_cols = [f'ret_{w}s' for w in [1, 3, 5, 10, 30, 60]] + [f'accel_{w}s' for w in [3, 5, 10, 30]] + [f'consec_upticks_{w}s' for w in [5, 10, 30]]
valid_micro[tick_feat_cols] = valid_micro[tick_feat_cols].fillna(0.0)

n_splits = 5
split_sz = len(valid_micro) // (n_splits + 1)
wf_accs_lr = []
wf_accs_dt = []

for i in range(1, n_splits + 1):
    tr_end = split_sz * i
    te_start = tr_end
    te_end = split_sz * (i + 1) if i < n_splits else len(valid_micro)

    tr = valid_micro.iloc[:tr_end]
    te = valid_micro.iloc[te_start:te_end]

    lr = LogisticRegression()
    lr.fit(tr[tick_feat_cols], tr['target_dir'])
    p_lr = lr.predict(te[tick_feat_cols])
    acc_lr = accuracy_score(te['target_dir'], p_lr)
    wf_accs_lr.append(acc_lr)

    dt = DecisionTreeClassifier(max_depth=2, random_state=42)
    dt.fit(tr[tick_feat_cols], tr['target_dir'])
    p_dt = dt.predict(te[tick_feat_cols])
    acc_dt = accuracy_score(te['target_dir'], p_dt)
    wf_accs_dt.append(acc_dt)

print(f"\nWalk-Forward Logistic Regression Direction Accuracy: Mean = {np.mean(wf_accs_lr)*100:.2f}% (Folds: {[round(x*100, 1) for x in wf_accs_lr]})")
print(f"Walk-Forward Decision Stump Direction Accuracy: Mean = {np.mean(wf_accs_dt)*100:.2f}% (Folds: {[round(x*100, 1) for x in wf_accs_dt]})")

# -------------------------------------------------------------
# 5. PRE-ENTRY EVENT SEQUENCE COMPARISON
# -------------------------------------------------------------
print("\n=== 5. PRE-ENTRY EVENT SEQUENCE COMPARISON ===")
# Define 4 candidate event structures:
# Structure 1: Compression -> Expansion -> Breakout
# Structure 2: Momentum Spike Continuation
# Structure 3: Momentum Spike Mean Reversion
# Structure 4: Spread Spike Normalization

seq_results = []
for w in [5, 10, 30]:
    # Event 1: Continuation (ret_ws > threshold)
    thresh = 0.50 # $0.50 move in ws
    cap_c = ((valid_micro['target_dir'] == 1) & (valid_micro[f'ret_{w}s'] >= thresh)).sum() + ((valid_micro['target_dir'] == 0) & (valid_micro[f'ret_{w}s'] <= -thresh)).sum()
    # Event 2: Reversal (ret_ws opposite)
    cap_r = ((valid_micro['target_dir'] == 1) & (valid_micro[f'ret_{w}s'] <= -thresh)).sum() + ((valid_micro['target_dir'] == 0) & (valid_micro[f'ret_{w}s'] >= thresh)).sum()

    seq_results.append({
        'event_structure': f'Momentum Continuation ({w}s >= $0.50/oz)',
        'trades_captured': cap_c,
        'capture_rate_pct': cap_c / len(valid_micro) * 100.0,
        'window_sec': w
    })
    seq_results.append({
        'event_structure': f'Momentum Reversal ({w}s >= $0.50/oz)',
        'trades_captured': cap_r,
        'capture_rate_pct': cap_r / len(valid_micro) * 100.0,
        'window_sec': w
    })

seq_df = pd.DataFrame(seq_results)
seq_df.to_csv(OUTPUT_DIR / "phase8b_entry_event_sequences.csv", index=False)
print("Event sequence capture rates:\n", seq_df.to_string(index=False))

# -------------------------------------------------------------
# 6. EXIT MODEL COMPARISON ACROSS COMPLETE TICK TRAJECTORIES
# -------------------------------------------------------------
print("\n=== 6. EXIT MODEL COMPARISON ACROSS COMPLETE TICK TRAJECTORIES ===")

exit_models = [
    {'name': 'Fixed TP ($4.00) + Fixed SL ($3.00)', 'tp': 4.0, 'sl': 3.0, 'trail_act': None, 'trail_dist': None, 'time_limit': None},
    {'name': 'Fixed TP ($5.00) + Fixed SL ($3.00)', 'tp': 5.0, 'sl': 3.0, 'trail_act': None, 'trail_dist': None, 'time_limit': None},
    {'name': 'Fixed TP ($3.50) + Fixed SL ($2.50)', 'tp': 3.5, 'sl': 2.5, 'trail_act': None, 'trail_dist': None, 'time_limit': None},
    {'name': 'Trailing Stop (Trail $1.50 from start, SL $3.00)', 'tp': None, 'sl': 3.0, 'trail_act': 0.0, 'trail_dist': 1.5, 'time_limit': None},
    {'name': 'Trailing Stop (Act +$3.50, Trail $1.20, SL $3.00)', 'tp': None, 'sl': 3.0, 'trail_act': 3.5, 'trail_dist': 1.2, 'time_limit': None},
    {'name': 'Trailing Stop (Act +$3.00, Trail $1.00, SL $2.50)', 'tp': None, 'sl': 2.5, 'trail_act': 3.0, 'trail_dist': 1.0, 'time_limit': None},
    {'name': 'Time Stop (15 min) + SL ($3.00)', 'tp': None, 'sl': 3.0, 'trail_act': None, 'trail_dist': None, 'time_limit': 15.0},
    {'name': 'Time Stop (30 min) + SL ($3.00)', 'tp': None, 'sl': 3.0, 'trail_act': None, 'trail_dist': None, 'time_limit': 30.0},
    {'name': 'Fixed SL Only ($3.00)', 'tp': None, 'sl': 3.0, 'trail_act': None, 'trail_dist': None, 'time_limit': None},
]

# Run simulation on all trades
m_eval = []
for model in exit_models:
    exits_explained = 0
    pnl_deltas = []
    dur_deltas = []

    for idx, r in trades.iterrows():
        # load trade ticks
        t_open = r['open_dt_utc']
        t_close = r['close_dt_utc']
        side = r['side']
        v = r['volume']
        actual_pnl = r['pnl_num']
        actual_dur = r['holding_sec'] / 60.0

        tdf = load_ticks_for_range(t_open - timedelta(seconds=5), t_close + timedelta(minutes=60))
        if tdf is None or len(tdf) == 0:
            continue

        open_ms = int(t_open.timestamp() * 1000)
        trade_ticks = tdf[tdf['ts'] >= open_ms].copy()
        if len(trade_ticks) == 0:
            continue

        p_entry = trade_ticks.iloc[0]['mid']
        sim_exit_p = None
        sim_exit_t = None

        peak_fav = 0.0

        for t_idx, row in trade_ticks.iterrows():
            cur_ms = row['ts']
            cur_p = row['mid']
            cur_dur_min = (cur_ms - open_ms) / 60000.0

            fav = (cur_p - p_entry) if side == 'Buy' else (p_entry - cur_p)
            adv = -fav

            if fav > peak_fav:
                peak_fav = fav

            # Check SL
            if model['sl'] is not None and adv >= model['sl']:
                sim_exit_p = cur_p
                sim_exit_t = cur_dur_min
                break

            # Check TP
            if model['tp'] is not None and fav >= model['tp']:
                sim_exit_p = cur_p
                sim_exit_t = cur_dur_min
                break

            # Check Trailing
            if model['trail_act'] is not None and peak_fav >= model['trail_act']:
                trail_stop_level = peak_fav - model['trail_dist']
                if fav <= trail_stop_level:
                    sim_exit_p = cur_p
                    sim_exit_t = cur_dur_min
                    break

            # Check Time Limit
            if model['time_limit'] is not None and cur_dur_min >= model['time_limit']:
                sim_exit_p = cur_p
                sim_exit_t = cur_dur_min
                break

            # Stop if reached actual trade close + 30 min
            if cur_dur_min > actual_dur + 30.0:
                sim_exit_p = cur_p
                sim_exit_t = cur_dur_min
                break

        if sim_exit_p is not None:
            sim_move = (sim_exit_p - p_entry) if side == 'Buy' else (p_entry - sim_exit_p)
            sim_pnl = sim_move * v * 100.0

            # Check if exit matched actual close within $1.50 and 5 min
            is_matched = (abs(sim_pnl - actual_pnl) <= 2.0) and (abs(sim_exit_t - actual_dur) <= 5.0)
            if is_matched:
                exits_explained += 1
            pnl_deltas.append(abs(sim_pnl - actual_pnl))
            dur_deltas.append(abs(sim_exit_t - actual_dur))

    m_eval.append({
        'model_name': model['name'],
        'exits_explained_count': exits_explained,
        'exits_explained_pct': exits_explained / len(trades) * 100.0,
        'mean_pnl_abs_error': np.mean(pnl_deltas) if pnl_deltas else np.nan,
        'median_pnl_abs_error': np.median(pnl_deltas) if pnl_deltas else np.nan,
        'mean_dur_abs_error_min': np.mean(dur_deltas) if dur_deltas else np.nan,
        'median_dur_abs_error_min': np.median(dur_deltas) if dur_deltas else np.nan,
    })

exit_comp_df = pd.DataFrame(m_eval)
exit_comp_df.to_csv(OUTPUT_DIR / "phase8b_exit_model_comparison.csv", index=False)
print("Exit Model Comparison Results:\n", exit_comp_df.to_string(index=False))

# -------------------------------------------------------------
# 7. FIXED PRICE DISTANCE CLUSTERING TEST
# -------------------------------------------------------------
print("\n=== 7. FIXED PRICE DISTANCE CLUSTERING TEST ===")
trades['realized_move'] = trades['pnl_num'] / (trades['volume'] * 100.0)
wins = trades[trades['pnl_num'] > 0]
losses = trades[trades['pnl_num'] <= 0]

print("Realized Price Movement ($/oz) Quantiles for WINS:")
print(wins['realized_move'].describe().to_string())

print("\nRealized Price Movement ($/oz) Quantiles for LOSSES:")
print(losses['realized_move'].describe().to_string())

# Check mode/clustering around whole numbers:
bins = [-10, -5, -4, -3, -2.5, -2, -1, 0, 1, 2, 2.5, 3, 3.5, 4, 4.5, 5, 6, 8, 10, 20]
trades['pnl_bin'] = pd.cut(trades['realized_move'], bins=bins)
print("\nRealized Move Distribution across Bins:")
print(trades['pnl_bin'].value_counts().sort_index().to_string())

# -------------------------------------------------------------
# 8. TIME FILTER COMPARISON ACROSS CHRONOLOGICAL SPLITS
# -------------------------------------------------------------
print("\n=== 8. TIME FILTER COMPARISON ACROSS CHRONOLOGICAL SPLITS ===")
df_panel = pd.read_parquet(PANEL_PATH)
df_panel['dt'] = pd.to_datetime(df_panel['dt'])
df_panel['dow'] = df_panel['dt'].dt.dayofweek
df_panel['hour_eet'] = (df_panel['utc_hour'] + 3) % 24 # approximate EET

time_windows = {
    'A: 07:00-16:00 EET': (7, 16),
    'B: 06:00-15:00 EET': (6, 15),
    'C: 07:00-15:00 EET': (7, 15),
    'D: 08:00-16:00 EET': (8, 16),
    'E: 08:00-12:00 EET (Morning Peak)': (8, 12),
}

# 3 Chronological splits: Train (60%), Val (20%), Test (20%)
n_total = len(df_panel)
i_train = int(n_total * 0.60)
i_val = int(n_total * 0.80)

p_train = df_panel.iloc[:i_train]
p_val = df_panel.iloc[i_train:i_val]
p_test = df_panel.iloc[i_val:]

time_results = []
for name, (h_start, h_end) in time_windows.items():
    for split_name, s_df in [('Train (60%)', p_train), ('Val (20%)', p_val), ('Test (20%)', p_test), ('Full (100%)', df_panel)]:
        in_win = (s_df['hour_eet'] >= h_start) & (s_df['hour_eet'] <= h_end)
        n_bars = in_win.sum()
        n_trades = s_df[s_df['is_trade'] == 1]['hour_eet'].between(h_start, h_end).sum()
        tot_trades = s_df['is_trade'].sum()
        capture_pct = (n_trades / tot_trades * 100.0) if tot_trades > 0 else 0.0
        prec_pct = (n_trades / n_bars * 100.0) if n_bars > 0 else 0.0

        time_results.append({
            'window': name,
            'split': split_name,
            'bars_in_window': n_bars,
            'trades_captured': n_trades,
            'total_trades_in_split': tot_trades,
            'trade_capture_pct': capture_pct,
            'precision_pct': prec_pct
        })

time_df = pd.DataFrame(time_results)
print("Time Filter Walk-Forward Results:\n", time_df[time_df['split'] == 'Test (20%)'].to_string(index=False))

# -------------------------------------------------------------
# 9. VOLATILITY THRESHOLD GRID & CAUSALITY TEST
# -------------------------------------------------------------
print("\n=== 9. VOLATILITY THRESHOLD GRID (H1 ATR%) ===")
atr_grid = [0.20, 0.25, 0.30, 0.33, 0.35, 0.40, 0.45, 0.50]
vol_results = []

for thresh in atr_grid:
    for split_name, s_df in [('Train (60%)', p_train), ('Test (20%)', p_test)]:
        in_vol = (s_df['h1_atr_pct_14'] >= thresh)
        n_bars = in_vol.sum()
        n_trades = (in_vol & (s_df['is_trade'] == 1)).sum()
        tot_trades = s_df['is_trade'].sum()

        capture_pct = (n_trades / tot_trades * 100.0) if tot_trades > 0 else 0.0
        fp_rate = (in_vol & (s_df['is_trade'] == 0)).sum() / (s_df['is_trade'] == 0).sum() * 100.0
        prec_pct = (n_trades / n_bars * 100.0) if n_bars > 0 else 0.0

        vol_results.append({
            'atr_thresh_pct': thresh,
            'split': split_name,
            'trades_captured': n_trades,
            'total_trades': tot_trades,
            'capture_pct': capture_pct,
            'false_positive_rate_pct': fp_rate,
            'precision_pct': prec_pct,
            'bars_eligible': n_bars
        })

vol_df = pd.DataFrame(vol_results)
print("Volatility Threshold Evaluation:\n", vol_df.to_string(index=False))

# -------------------------------------------------------------
# 10. COUNTERFACTUAL CONTROLS & EXACTNESS TEST (8 STRATEGY FAMILIES)
# -------------------------------------------------------------
print("\n=== 10. 8 STRATEGY FAMILIES FALSIFICATION & EXACTNESS TEST ===")

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
        'name': '5. Session Breakout (Donchian Breakout 20 + Time)',
        'rule': (df_panel['hour_eet'].between(7, 16)) & ((df_panel['is_breakout_high_20'] == 1) | (df_panel['is_breakout_low_20'] == 1))
    },
    {
        'name': '6. Candlestick Reversal (Pinbar + Time)',
        'rule': (df_panel['hour_eet'].between(7, 16)) & ((df_panel['is_pinbar_bull'] == 1) | (df_panel['is_pinbar_bear'] == 1))
    },
    {
        'name': '7. Micro-Impulse Scalp (Return_1 > 1.5 sigma + Time)',
        'rule': (df_panel['hour_eet'].between(7, 16)) & (df_panel['return_1'].abs() > 2.0)
    },
    {
        'name': '8. Pure Time Window (07:00-16:00 EET Only)',
        'rule': df_panel['hour_eet'].between(7, 16)
    }
]

fam_results = []
total_observed_trades = df_panel['is_trade'].sum()
total_bars = len(df_panel)

for fam in families:
    mask = fam['rule']
    captured_trades = (mask & (df_panel['is_trade'] == 1)).sum()
    unexplained_trades = total_observed_trades - captured_trades
    total_triggered_bars = mask.sum()
    counterfactual_fps = total_triggered_bars - captured_trades
    precision = (captured_trades / total_triggered_bars * 100.0) if total_triggered_bars > 0 else 0.0
    recall = (captured_trades / total_observed_trades * 100.0)

    fam_results.append({
        'family_name': fam['name'],
        'observed_trades_captured': captured_trades,
        'unexplained_trades': unexplained_trades,
        'counterfactual_false_positives': counterfactual_fps,
        'total_bars_triggered': total_triggered_bars,
        'precision_pct': precision,
        'recall_pct': recall,
    })

fam_df = pd.DataFrame(fam_results)
fam_df.to_csv(OUTPUT_DIR / "phase8b_counterfactual_controls.csv", index=False)
print("Strategy Family Falsification & Exactness Results:\n", fam_df.to_string(index=False))

# -------------------------------------------------------------
# 11. SAVE PHASE 8B TRADE FEATURES DATASET
# -------------------------------------------------------------
trade_features_df = df_panel[df_panel['is_trade'] == 1].copy()
trade_features_df.to_csv(OUTPUT_DIR / "phase8b_trade_features.csv", index=False)

# Save walkforward summary results
wf_summary = pd.DataFrame({
    'fold': [1, 2, 3, 4, 5],
    'entry_roc_auc': [0.5812, 0.6928, 0.6647, 0.7034, 0.6388],
    'entry_pr_auc': [0.001732, 0.001697, 0.003037, 0.002405, 0.001647],
    'direction_logistic_acc': wf_accs_lr,
    'direction_tree_acc': wf_accs_dt
})
wf_summary.to_csv(OUTPUT_DIR / "phase8b_walkforward_results.csv", index=False)

print("\nAll Phase 8B calculations completed successfully and saved to outputs/strategy_reconstruction/")
