"""
Phase 8B - Stage 6: Position Sizing State Machine & Concurrency Dynamics
Analyzes lot size transitions (0.01 -> 0.02) and overlapping position concurrency.
Deterministic Cheap stage (< 1 second).
"""

from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT / "outputs"
RECON_PATH = OUTPUTS_DIR / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
OUTPUT_DIR = OUTPUTS_DIR / "strategy_reconstruction"

def main():
    print("=================================================================")
    print("PHASE 8B - STAGE 06: POSITION SIZING & CONCURRENCY AUDIT")
    print("=================================================================")

    trades = pd.read_csv(RECON_PATH)
    trades['open_dt_utc'] = pd.to_datetime(trades['open_time_utc'])
    trades['close_dt_utc'] = pd.to_datetime(trades['close_time_utc'])
    trades['open_dt_broker'] = pd.to_datetime(trades['recorded_open_time'])
    trades['pnl_num'] = trades['recorded_pnl'].astype(float)
    trades['is_win'] = trades['pnl_num'] > 0
    trades = trades.sort_values('open_dt_utc').reset_index(drop=True)

    print(f"Total trades analyzed (chronologically sorted): {len(trades)}")

    # 1. Overlapping / Concurrent Positions
    overlaps = []
    for i in range(len(trades)):
        t_i = trades.iloc[i]
        for j in range(i + 1, len(trades)):
            t_j = trades.iloc[j]
            if t_j['open_dt_utc'] < t_i['close_dt_utc']:
                overlap_sec = (min(t_i['close_dt_utc'], t_j['close_dt_utc']) - t_j['open_dt_utc']).total_seconds()
                same_dir = (t_i['side'] == t_j['side'])
                overlaps.append({
                    'trade_1_ticket': t_i['ticket'],
                    'trade_2_ticket': t_j['ticket'],
                    'trade_1_side': t_i['side'],
                    'trade_2_side': t_j['side'],
                    'same_side': same_dir,
                    'overlap_sec': overlap_sec,
                    'overlap_min': overlap_sec / 60.0
                })
            else:
                break

    print(f"\nTotal Overlapping Position Pairs Detected: {len(overlaps)}")
    if len(overlaps) > 0:
        over_df = pd.DataFrame(overlaps)
        print("Overlapping Positions Summary:")
        print(over_df.to_string(index=False))
    else:
        print("No overlapping positions detected (Strict single-position execution policy).")

    # 2. Position Sizing State Machine
    pos_states = []
    cum_pnl = 0.0
    win_streak = 0
    loss_streak = 0

    for i in range(len(trades)):
        t = trades.iloc[i]
        pnl = t['pnl_num']
        v = t['volume']

        prev_pnl = trades.iloc[i-1]['pnl_num'] if i > 0 else np.nan
        prev_win = trades.iloc[i-1]['is_win'] if i > 0 else np.nan
        prev_vol = trades.iloc[i-1]['volume'] if i > 0 else np.nan

        pos_states.append({
            'ticket': t['ticket'],
            'open_time': t['recorded_open_time'],
            'volume': v,
            'pnl': pnl,
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

        cum_pnl += pnl
        if pnl > 0:
            win_streak += 1
            loss_streak = 0
        else:
            loss_streak += 1
            win_streak = 0

    pos_df = pd.DataFrame(pos_states)
    out_pos_path = OUTPUT_DIR / "phase8b_position_state.csv"
    pos_df.to_csv(out_pos_path, index=False)
    print(f"\n[PASS] Saved position sizing state dataset: {out_pos_path}")

    # Markov Transition Analysis
    transitions = pos_df.dropna(subset=['prev_volume'])
    print("\nSize Transition Matrix:")
    trans_counts = transitions.groupby(['prev_volume', 'volume']).size().to_dict()
    for k, v in trans_counts.items():
        print(f"  {k[0]} Lot -> {k[1]} Lot: {v} instances")

    print("\nVolume conditional on previous trade outcome:")
    print("  After WIN:")
    print("   ", transitions[transitions['prev_win'] == True]['volume'].value_counts().to_dict())
    print("  After LOSS:")
    print("   ", transitions[transitions['prev_win'] == False]['volume'].value_counts().to_dict())

    v02_trades = pos_df[pos_df['volume'] == 0.02]
    print(f"\n0.02 Lot Trades Profile (N={len(v02_trades)}):")
    print(f"  Win Streaks Prior to 0.02: {v02_trades['win_streak_before'].value_counts().to_dict()}")
    print(f"  Cumulative PnL Range at 0.02: ${v02_trades['cum_pnl'].min():.2f} to ${v02_trades['cum_pnl'].max():.2f}")
    print(f"  Win Rate of 0.02 Trades: {(v02_trades['pnl'] > 0).mean()*100:.2f}%")

    print("\nSTAGE 06 COMPLETE.\n")

if __name__ == "__main__":
    main()
