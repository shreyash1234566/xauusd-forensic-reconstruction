"""
Phase 8C - Stage 1: Candidate Strategy Autonomous Replayer Engine
Replays the complete 402,151 M1 historical market bars chronologically.
Decides ENTER / DO NOT ENTER using strictly causal information at t.
Simulates position management, exit trailing state, and sizing state machine.
"""

from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUTS_DIR = ROOT / "outputs"
PANEL_PATH = DATA_DIR / "processed" / "decision_panel.parquet"
M1_PATH = DATA_DIR / "market" / "normalized" / "xauusd_m1.csv"
RECON_PATH = OUTPUTS_DIR / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
OUTPUT_DIR = OUTPUTS_DIR / "strategy_reconstruction"

class CandidateStrategyReplayer:
    def __init__(self,
                 session_start_eet=7,
                 session_end_eet=16,
                 min_atr_pct=0.25,
                 min_impulse_dollars=0.30,
                 sl_dollars=2.50,
                 trail_act_dollars=3.00,
                 trail_dist_dollars=1.00,
                 max_hold_minutes=45.0,
                 base_lot=0.01,
                 win_scale_lot=0.02,
                 single_position=True):
        self.session_start_eet = session_start_eet
        self.session_end_eet = session_end_eet
        self.min_atr_pct = min_atr_pct
        self.min_impulse_dollars = min_impulse_dollars
        self.sl_dollars = sl_dollars
        self.trail_act_dollars = trail_act_dollars
        self.trail_dist_dollars = trail_dist_dollars
        self.max_hold_minutes = max_hold_minutes
        self.base_lot = base_lot
        self.win_scale_lot = win_scale_lot
        self.single_position = single_position

    def run_simulation(self, df):
        """
        Runs chronological bar-by-bar simulation across market panel.
        """
        generated_trades = []
        candidate_signals = []

        # State variables
        in_pos = False
        pos_side = None
        pos_entry_price = 0.0
        pos_entry_time = None
        pos_entry_bar_idx = 0
        pos_lot = self.base_lot
        pos_peak_fav = 0.0

        prev_trade_win = False

        # Pre-extract arrays for ultra-fast loop
        dts = df['dt'].values
        opens = df['open'].values
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        hours_eet = df['hour_eet'].values
        atrs = df['h1_atr_pct_14'].values

        n_bars = len(df)

        for i in range(1, n_bars):
            cur_dt = dts[i]
            cur_open = opens[i]
            cur_high = highs[i]
            cur_low = lows[i]
            cur_close = closes[i]
            cur_hour = hours_eet[i]
            cur_atr = atrs[i]

            # 1. Manage Active Position (if any)
            if in_pos:
                hold_min = (pd.to_datetime(cur_dt) - pos_entry_time).total_seconds() / 60.0

                # Check adverse / favorable excursion on current bar
                if pos_side == 'Buy':
                    fav_price = cur_high - pos_entry_price
                    adv_price = pos_entry_price - cur_low
                    exit_price_sl = pos_entry_price - self.sl_dollars
                else:
                    fav_price = pos_entry_price - cur_low
                    adv_price = cur_high - pos_entry_price
                    exit_price_sl = pos_entry_price + self.sl_dollars

                if fav_price > pos_peak_fav:
                    pos_peak_fav = fav_price

                is_exit = False
                exit_reason = None
                exit_price = cur_close

                # Check Stop Loss
                if adv_price >= self.sl_dollars:
                    is_exit = True
                    exit_reason = "Stop Loss ($2.50)"
                    exit_price = exit_price_sl
                # Check Trailing Stop
                elif pos_peak_fav >= self.trail_act_dollars:
                    trail_exit_fav = pos_peak_fav - self.trail_dist_dollars
                    # Current retracement
                    cur_cur_fav = (cur_close - pos_entry_price) if pos_side == 'Buy' else (pos_entry_price - cur_close)
                    if cur_cur_fav <= trail_exit_fav:
                        is_exit = True
                        exit_reason = "Trailing Stop (Act +$3.00, Trail $1.00)"
                        if pos_side == 'Buy':
                            exit_price = pos_entry_price + trail_exit_fav
                        else:
                            exit_price = pos_entry_price - trail_exit_fav
                # Check Time Stop
                elif self.max_hold_minutes is not None and hold_min >= self.max_hold_minutes:
                    is_exit = True
                    exit_reason = f"Time Stop ({self.max_hold_minutes:.0f} min)"
                    exit_price = cur_open

                if is_exit:
                    move = (exit_price - pos_entry_price) if pos_side == 'Buy' else (pos_entry_price - exit_price)
                    pnl = move * pos_lot * 100.0  # 1 lot = 100 oz
                    prev_trade_win = (pnl > 0)

                    generated_trades.append({
                        'gen_ticket': len(generated_trades) + 1,
                        'entry_time': pos_entry_time,
                        'entry_price': pos_entry_price,
                        'side': pos_side,
                        'lot_size': pos_lot,
                        'exit_time': pd.to_datetime(cur_dt),
                        'exit_price': exit_price,
                        'pnl': pnl,
                        'holding_minutes': hold_min,
                        'exit_reason': exit_reason,
                        'peak_favorable': pos_peak_fav
                    })
                    in_pos = False
                    pos_side = None
                    pos_peak_fav = 0.0

            # 2. Check Entry Conditions
            # Filter A: Session Window
            session_ok = (cur_hour >= self.session_start_eet) and (cur_hour <= self.session_end_eet)
            # Filter B: Volatility Filter
            atr_ok = (cur_atr >= self.min_atr_pct)
            # Filter C: Impulse
            # Pre-entry impulse on completed prior bar (closes[i-1] - opens[i-1])
            prev_move = closes[i-1] - opens[i-1]
            impulse_ok = abs(prev_move) >= self.min_impulse_dollars

            signal_active = session_ok and atr_ok and impulse_ok
            signal_side = 'Buy' if prev_move > 0 else 'Sell'

            if signal_active:
                candidate_signals.append({
                    'dt': pd.to_datetime(cur_dt),
                    'side': signal_side,
                    'price': cur_open,
                    'hour_eet': cur_hour,
                    'atr': cur_atr,
                    'impulse': prev_move,
                    'taken': not (self.single_position and in_pos)
                })

                # If position manager allows entry
                if not (self.single_position and in_pos):
                    in_pos = True
                    pos_side = signal_side
                    pos_entry_price = cur_open
                    pos_entry_time = pd.to_datetime(cur_dt)
                    pos_entry_bar_idx = i
                    pos_lot = self.win_scale_lot if prev_trade_win else self.base_lot
                    pos_peak_fav = 0.0

        return pd.DataFrame(generated_trades), pd.DataFrame(candidate_signals)

def main():
    print("=================================================================")
    print("PHASE 8C - STAGE 01: CANDIDATE STRATEGY AUTONOMOUS REPLAYER")
    print("=================================================================")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load decision panel and M1 market bars
    dp = pd.read_parquet(PANEL_PATH)
    m1 = pd.read_csv(M1_PATH)
    dp['dt'] = pd.to_datetime(dp['dt'])
    m1['dt'] = pd.to_datetime(m1['timestamp'])

    df = pd.merge(dp, m1[['dt', 'open', 'high', 'low', 'close']], on='dt', how='inner')
    df = df.sort_values('dt').reset_index(drop=True)
    df['hour_eet'] = (df['utc_hour'] + 3) % 24

    print(f"Loaded merged market panel: {len(df):,} M1 bars ({df['dt'].min()} to {df['dt'].max()})")

    # Run autonomous replayer
    replayer = CandidateStrategyReplayer(
        session_start_eet=7,
        session_end_eet=16,
        min_atr_pct=0.25,
        min_impulse_dollars=0.30,
        sl_dollars=2.50,
        trail_act_dollars=3.00,
        trail_dist_dollars=1.00,
        max_hold_minutes=45.0,
        base_lot=0.01,
        win_scale_lot=0.02,
        single_position=True
    )

    gen_trades, cand_signals = replayer.run_simulation(df)

    # Save generated trades & signals
    out_gen_path = OUTPUT_DIR / "phase8c_generated_trades.csv"
    gen_trades.to_csv(out_gen_path, index=False)
    print(f"[PASS] Saved generated trades: {out_gen_path} ({len(gen_trades):,} trades)")

    out_sig_path = OUTPUT_DIR / "phase8c_candidate_signals.csv"
    cand_signals.to_csv(out_sig_path, index=False)
    print(f"[PASS] Saved candidate signals: {out_sig_path} ({len(cand_signals):,} signals)")

    # Load actual observed trades
    recon = pd.read_csv(RECON_PATH)
    recon['open_dt_utc'] = pd.to_datetime(recon['open_time_utc'])
    recon['close_dt_utc'] = pd.to_datetime(recon['close_time_utc'])

    print("\n--- REPLAY SUMMARY VS OBSERVED TRADES ---")
    print(f"Total Market Opportunity Bars:        {len(df):,}")
    print(f"Total Candidate Signals Generated:    {len(cand_signals):,}")
    print(f"Total Autonomous Trades Taken:        {len(gen_trades):,}")
    print(f"Total Observed Real Trades:           {len(recon):,}")

    # Match analysis: match generated entries to actual entries within tolerance
    gen_dts = gen_trades['entry_time'].values
    rec_dts = recon['open_dt_utc'].values

    # Compute recall on observed trades
    matched_observed = 0
    matched_gen = 0

    for _, r in recon.iterrows():
        t_rec = r['open_dt_utc']
        # Check if any generated trade opened within 5 minutes
        diffs = (gen_trades['entry_time'] - t_rec).abs()
        nearby = gen_trades[diffs <= pd.Timedelta(minutes=5)]
        if len(nearby) > 0:
            matched_observed += 1

    print(f"Observed Trades Near Generated Signals (<= 5 min): {matched_observed} / {len(recon)} ({matched_observed/len(recon)*100:.2f}%)")
    print(f"Observed Trades Completely Missed:                {len(recon) - matched_observed} ({ (len(recon)-matched_observed)/len(recon)*100:.2f}%)")

    # Counterfactual False Positive Rate
    fp_trades = len(gen_trades) - matched_observed
    precision = matched_observed / len(gen_trades) * 100.0 if len(gen_trades) > 0 else 0.0
    print(f"Generated Trades that NEVER Existed (False Pos): {fp_trades:,}")
    print(f"Precision (True Pos / Total Generated):           {precision:.4f}%")
    print(f"Recall (True Pos / Total Observed):              {matched_observed/len(recon)*100:.2f}%")

    print("\nSTAGE 01 COMPLETE.\n")

if __name__ == "__main__":
    main()
