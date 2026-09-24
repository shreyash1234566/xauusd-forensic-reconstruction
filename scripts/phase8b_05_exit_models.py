"""
Phase 8B - Stage 5: Exit Model Simulation & Trajectory Deconvolution
Simulates 9 competing exit models on complete raw tick paths across all 423 trades.
Deterministic Medium stage (~10 seconds).
"""

from pathlib import Path
from datetime import timedelta
import json
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUTS_DIR = ROOT / "outputs"
RECON_PATH = OUTPUTS_DIR / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
TICKS_DIR = DATA_DIR / "market" / "raw_ticks"
OUTPUT_DIR = OUTPUTS_DIR / "strategy_reconstruction"

class TickCache:
    def __init__(self, ticks_dir):
        self.ticks_dir = Path(ticks_dir)
        self.cache = {}

    def get_hour_ticks(self, dt_utc):
        iso_str = dt_utc.strftime("%Y-%m-%dT%H-00-00-000Z")
        if iso_str in self.cache:
            return self.cache[iso_str]

        p = self.ticks_dir / f"xauusd_ticks_{iso_str}.json"
        if not p.exists():
            self.cache[iso_str] = None
            return None

        try:
            with open(p, 'r') as f:
                data = json.load(f)
            if not data or len(data) == 0:
                self.cache[iso_str] = None
                return None
            arr = np.array(data, dtype=float)
            df = pd.DataFrame({
                'ts': arr[:, 0],
                'ask': arr[:, 1],
                'bid': arr[:, 2],
                'mid': (arr[:, 1] + arr[:, 2]) / 2.0,
            })
            self.cache[iso_str] = df
            return df
        except Exception:
            self.cache[iso_str] = None
            return None

    def get_range_ticks(self, start_utc, end_utc):
        cur_h = start_utc.replace(minute=0, second=0, microsecond=0)
        end_h = end_utc.replace(minute=0, second=0, microsecond=0)
        ticks = []
        h = cur_h
        while h <= end_h + timedelta(hours=1):
            tdf = self.get_hour_ticks(h)
            if tdf is not None and len(tdf) > 0:
                ticks.append(tdf)
            h += timedelta(hours=1)
        if not ticks:
            return None
        return pd.concat(ticks, ignore_index=True).drop_duplicates(subset=['ts']).sort_values('ts').reset_index(drop=True)

def main():
    print("=================================================================")
    print("PHASE 8B - STAGE 05: EXIT MODEL TRAJECTORY SIMULATION")
    print("=================================================================")

    trades = pd.read_csv(RECON_PATH)
    trades['open_dt_utc'] = pd.to_datetime(trades['open_time_utc'])
    trades['close_dt_utc'] = pd.to_datetime(trades['close_time_utc'])
    trades['pnl_num'] = trades['recorded_pnl'].astype(float)
    trades['holding_min'] = (trades['close_dt_utc'] - trades['open_dt_utc']).dt.total_seconds() / 60.0

    print(f"Simulating exit models across {len(trades)} trade tick trajectories...")

    exit_models = [
        {'name': '1. Fixed TP ($4.00) + Fixed SL ($3.00)', 'tp': 4.0, 'sl': 3.0, 'trail_act': None, 'trail_dist': None, 'time_limit': None},
        {'name': '2. Fixed TP ($5.00) + Fixed SL ($3.00)', 'tp': 5.0, 'sl': 3.0, 'trail_act': None, 'trail_dist': None, 'time_limit': None},
        {'name': '3. Fixed TP ($3.50) + Fixed SL ($2.50)', 'tp': 3.5, 'sl': 2.5, 'trail_act': None, 'trail_dist': None, 'time_limit': None},
        {'name': '4. Trailing Stop (Trail $1.50 from start, SL $3.00)', 'tp': None, 'sl': 3.0, 'trail_act': 0.0, 'trail_dist': 1.5, 'time_limit': None},
        {'name': '5. Trailing Stop (Act +$3.50, Trail $1.20, SL $3.00)', 'tp': None, 'sl': 3.0, 'trail_act': 3.5, 'trail_dist': 1.2, 'time_limit': None},
        {'name': '6. Trailing Stop (Act +$3.00, Trail $1.00, SL $2.50)', 'tp': None, 'sl': 2.5, 'trail_act': 3.0, 'trail_dist': 1.0, 'time_limit': None},
        {'name': '7. Time Stop (15 min) + SL ($3.00)', 'tp': None, 'sl': 3.0, 'trail_act': None, 'trail_dist': None, 'time_limit': 15.0},
        {'name': '8. Time Stop (30 min) + SL ($3.00)', 'tp': None, 'sl': 3.0, 'trail_act': None, 'trail_dist': None, 'time_limit': 30.0},
        {'name': '9. Fixed SL Only ($3.00)', 'tp': None, 'sl': 3.0, 'trail_act': None, 'trail_dist': None, 'time_limit': None},
    ]

    tick_cache = TickCache(TICKS_DIR)

    # Pre-cache trade tick trajectories
    trade_tick_trajectories = {}
    for idx, r in trades.iterrows():
        t_open = r['open_dt_utc']
        t_close = r['close_dt_utc']
        tdf = tick_cache.get_range_ticks(t_open - timedelta(seconds=5), t_close + timedelta(minutes=60))
        if tdf is not None and len(tdf) > 0:
            open_ms = int(t_open.timestamp() * 1000)
            trade_ticks = tdf[tdf['ts'] >= open_ms].copy()
            if len(trade_ticks) > 0:
                trade_tick_trajectories[r['ticket']] = trade_ticks

    print(f"Cached {len(trade_tick_trajectories)} valid trade trajectories.")

    model_evals = []
    for model in exit_models:
        exits_explained = 0
        pnl_deltas = []
        dur_deltas = []

        for idx, r in trades.iterrows():
            ticket = r['ticket']
            if ticket not in trade_tick_trajectories:
                continue

            trade_ticks = trade_tick_trajectories[ticket]
            side = r['side']
            v = r['volume']
            actual_pnl = r['pnl_num']
            actual_dur = r['holding_min']

            # Extract numpy arrays for ultra-fast processing
            ts_arr = trade_ticks['ts'].values
            mids_arr = trade_ticks['mid'].values
            open_ms = int(r['open_dt_utc'].timestamp() * 1000)
            p_entry = mids_arr[0]
            favs = (mids_arr - p_entry) if side == 'Buy' else (p_entry - mids_arr)
            advs = -favs
            dur_mins = (ts_arr - open_ms) / 60000.0

            sim_exit_p = None
            sim_exit_t = None

            # Fast evaluation using numpy
            sl_val = model['sl']
            tp_val = model['tp']
            trail_act = model['trail_act']
            trail_dist = model['trail_dist']
            time_lim = model['time_limit']

            peak_fav = 0.0
            n_pts = len(favs)

            for k in range(n_pts):
                fav = favs[k]
                adv = advs[k]
                cur_dur = dur_mins[k]
                cur_p = mids_arr[k]

                if fav > peak_fav:
                    peak_fav = fav

                # Check SL
                if sl_val is not None and adv >= sl_val:
                    sim_exit_p = cur_p
                    sim_exit_t = cur_dur
                    break

                # Check TP
                if tp_val is not None and fav >= tp_val:
                    sim_exit_p = cur_p
                    sim_exit_t = cur_dur
                    break

                # Check Trailing Stop
                if trail_act is not None and peak_fav >= trail_act:
                    if fav <= (peak_fav - trail_dist):
                        sim_exit_p = cur_p
                        sim_exit_t = cur_dur
                        break

                # Check Time Stop
                if time_lim is not None and cur_dur >= time_lim:
                    sim_exit_p = cur_p
                    sim_exit_t = cur_dur
                    break

                # Fallback boundary
                if cur_dur > actual_dur + 30.0:
                    sim_exit_p = cur_p
                    sim_exit_t = cur_dur
                    break

            if sim_exit_p is not None:
                sim_move = (sim_exit_p - p_entry) if side == 'Buy' else (p_entry - sim_exit_p)
                sim_pnl = sim_move * v * 100.0

                # Tolerance matching: within $2.00 PnL and 5 min duration
                is_matched = (abs(sim_pnl - actual_pnl) <= 2.0) and (abs(sim_exit_t - actual_dur) <= 5.0)
                if is_matched:
                    exits_explained += 1
                pnl_deltas.append(abs(sim_pnl - actual_pnl))
                dur_deltas.append(abs(sim_exit_t - actual_dur))

        model_evals.append({
            'model_name': model['name'],
            'exits_explained_count': exits_explained,
            'exits_explained_pct': exits_explained / len(trades) * 100.0,
            'mean_pnl_abs_error': np.mean(pnl_deltas) if pnl_deltas else np.nan,
            'median_pnl_abs_error': np.median(pnl_deltas) if pnl_deltas else np.nan,
            'mean_dur_abs_error_min': np.mean(dur_deltas) if dur_deltas else np.nan,
            'median_dur_abs_error_min': np.median(dur_deltas) if dur_deltas else np.nan,
        })

    eval_df = pd.DataFrame(model_evals)
    out_exit_path = OUTPUT_DIR / "phase8b_exit_model_comparison.csv"
    eval_df.to_csv(out_exit_path, index=False)
    print(f"[PASS] Saved exit model evaluation: {out_exit_path}")

    print("\nExit Model Trajectory Simulation Results:")
    print(eval_df.to_string(index=False))

    print("\nSTAGE 05 COMPLETE.\n")

if __name__ == "__main__":
    main()
