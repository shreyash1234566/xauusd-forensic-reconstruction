"""
Phase 8E - Stage 3: Trigger Crossings, Debounce Mechanisms, State Reset, and First-Passage Dynamics
Covers:
- Section 5: True Tick-Trigger Signal-to-Noise Ratio (SNR) and Candidate Explosion Audit
- Section 9: Threshold Crossings vs Persistent State Conditions
- Section 10: Event Debounce and State-Reset Mechanisms
- Section 11: First-Passage Time & Trigger Latency
- Generates:
    outputs/strategy_reconstruction/phase8e_threshold_crossings.csv
    outputs/strategy_reconstruction/phase8e_event_debounce.csv
    outputs/strategy_reconstruction/phase8e_state_machine.csv
"""

from pathlib import Path
import time
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT / "outputs" / "strategy_reconstruction"
PANEL_PATH = ROOT / "data" / "processed" / "decision_panel.parquet"
RECON_PATH = OUTPUTS_DIR.parent / "market_reconstruction" / "phase7c_trade_reconciliation.csv"

def run_trigger_and_debounce_analysis():
    print("=================================================================")
    print("PHASE 8E - STAGE 03: TRIGGER CROSSINGS, DEBOUNCE & FSM AUDIT")
    print("=================================================================")
    t0 = time.time()

    panel = pd.read_parquet(PANEL_PATH)
    recon = pd.read_csv(RECON_PATH)

    recon['open_dt'] = pd.to_datetime(recon['open_time_utc'])
    recon['close_dt'] = pd.to_datetime(recon['close_time_utc'])
    recon = recon.sort_values('open_dt').reset_index(drop=True)
    real_trade_dts = recon['open_dt'].values
    total_real_trades = len(recon)

    panel['dt'] = pd.to_datetime(panel['dt'])
    panel['hour'] = panel['dt'].dt.hour
    panel['dayofweek'] = panel['dt'].dt.dayofweek

    # Base session & volatility eligibility
    in_session = (panel['hour'] >= 5) & (panel['hour'] <= 16) & ~((panel['dayofweek'] == 4) & (panel['hour'] >= 20))
    vol_eligible = panel['h1_atr_pct_14'] >= 0.25
    base_mask = in_session & vol_eligible

    # Helper matching function
    def evaluate_match_indices(indices, max_diff_min=5.0):
        if len(indices) == 0:
            return 0, 0.0, 0.0
        exec_dts = panel.iloc[indices]['dt'].values
        matched = 0
        for r_dt in real_trade_dts:
            diffs = np.abs((exec_dts - r_dt).astype('timedelta64[m]').astype(float))
            if len(diffs) > 0 and np.min(diffs) <= max_diff_min:
                matched += 1
        rec = (matched / total_real_trades * 100.0)
        prec = (matched / len(indices) * 100.0)
        return matched, rec, prec

    # -------------------------------------------------------------
    # 1. THRESHOLD CROSSINGS VS PERSISTENT STATE CONDITIONS
    # -------------------------------------------------------------
    print("\n--- 1. EVALUATING THRESHOLD CROSSING MODES ---")
    thresholds = [0.10, 0.20, 0.30, 0.40, 0.50, 0.75, 1.00]
    crossing_records = []

    ret1 = panel['return_1'].abs().values

    for th in thresholds:
        # Mode A: Persistent State Condition (|return_1| >= th)
        state_cond = base_mask.values & (ret1 >= th)
        state_idx = np.where(state_cond)[0]
        st_matched, st_rec, st_prec = evaluate_match_indices(state_idx)

        crossing_records.append({
            'trigger_type': 'Persistent State (Level Trigger)',
            'threshold_val': th,
            'description': f'|return_1| >= ${th:.2f} while eligible',
            'event_count': len(state_idx),
            'event_pct_of_bars': len(state_idx) / len(panel) * 100.0,
            'real_trades_matched': st_matched,
            'recall_pct': st_rec,
            'precision_pct': st_prec,
            'snr_ratio': st_prec / (100.0 - st_prec + 1e-6)
        })

        # Mode B: Rising Edge / First Crossing (|return_1|_t >= th AND |return_1|_{t-1} < th)
        prev_ret1 = np.roll(ret1, 1)
        prev_ret1[0] = 0.0
        edge_cond = base_mask.values & (ret1 >= th) & (prev_ret1 < th)
        edge_idx = np.where(edge_cond)[0]
        ed_matched, ed_rec, ed_prec = evaluate_match_indices(edge_idx)

        crossing_records.append({
            'trigger_type': 'Rising Edge (First Crossing)',
            'threshold_val': th,
            'description': f'|return_1|_t >= ${th:.2f} and |return_1|_(t-1) < ${th:.2f}',
            'event_count': len(edge_idx),
            'event_pct_of_bars': len(edge_idx) / len(panel) * 100.0,
            'real_trades_matched': ed_matched,
            'recall_pct': ed_rec,
            'precision_pct': ed_prec,
            'snr_ratio': ed_prec / (100.0 - ed_prec + 1e-6)
        })

        print(f"Threshold ${th:.2f} | Level: {len(state_idx):>6} events (Rec: {st_rec:>5.2f}%, Prec: {st_prec:>5.2f}%) | Edge: {len(edge_idx):>6} events (Rec: {ed_rec:>5.2f}%, Prec: {ed_prec:>5.2f}%)")

    cross_df = pd.DataFrame(crossing_records)
    cross_path = OUTPUTS_DIR / "phase8e_threshold_crossings.csv"
    cross_df.to_csv(cross_path, index=False)
    print(f"[PASS] Generated Threshold Crossings: {cross_path}")

    # -------------------------------------------------------------
    # 2. EVENT DEBOUNCE AND STATE-RESET MECHANISMS
    # -------------------------------------------------------------
    print("\n--- 2. EVALUATING DEBOUNCE & STATE-RESET MECHANISMS ---")
    debounce_records = []

    # Use baseline trigger: Edge crossing at $0.30 return
    baseline_edge = base_mask.values & (ret1 >= 0.30) & (np.roll(ret1, 1) < 0.30)
    base_indices = np.where(baseline_edge)[0]

    # Mechanism 0: Raw Edge (No Debounce)
    m0_match, m0_rec, m0_prec = evaluate_match_indices(base_indices)
    debounce_records.append({
        'mechanism_name': 'No Debounce (Raw Edge)',
        'mechanism_type': 'Baseline',
        'parameter_val': 'None',
        'generated_events': len(base_indices),
        'reduction_pct': 0.0,
        'matched_real_trades': m0_match,
        'recall_pct': m0_rec,
        'precision_pct': m0_prec
    })

    # Mechanism 1: Time-based Debounce Lockout (N minutes post-event)
    lockout_windows = [1, 2, 3, 5, 8, 10, 15, 20, 30]
    for w in lockout_windows:
        deb_idx = []
        last_t = -9999
        for idx in base_indices:
            if idx >= last_t + w:
                deb_idx.append(idx)
                last_t = idx
        d_match, d_rec, d_prec = evaluate_match_indices(deb_idx)
        red = (len(base_indices) - len(deb_idx)) / len(base_indices) * 100.0
        debounce_records.append({
            'mechanism_name': f'Time Debounce ({w}m Lockout)',
            'mechanism_type': 'Temporal Lockout',
            'parameter_val': f'{w} minutes',
            'generated_events': len(deb_idx),
            'reduction_pct': red,
            'matched_real_trades': d_match,
            'recall_pct': d_rec,
            'precision_pct': d_prec
        })
        print(f"Time Lockout ({w:>2}m)   | Events: {len(deb_idx):>6} (Red: {red:>5.2f}%) | Matched: {d_match:>3} ({d_rec:>5.2f}%) | Prec: {d_prec:>5.2f}%")

    # Mechanism 2: Directional Flip Reset (Signal only triggers if direction alternates Buy <-> Sell)
    dir_signals = np.sign(panel['return_1'].values)
    flip_idx = []
    last_dir = 0
    for idx in base_indices:
        curr_dir = dir_signals[idx]
        if curr_dir != 0 and curr_dir != last_dir:
            flip_idx.append(idx)
            last_dir = curr_dir
    f_match, f_rec, f_prec = evaluate_match_indices(flip_idx)
    f_red = (len(base_indices) - len(flip_idx)) / len(base_indices) * 100.0
    debounce_records.append({
        'mechanism_name': 'Directional Flip Reset',
        'mechanism_type': 'State Transition',
        'parameter_val': 'Sign Alternation',
        'generated_events': len(flip_idx),
        'reduction_pct': f_red,
        'matched_real_trades': f_match,
        'recall_pct': f_rec,
        'precision_pct': f_prec
    })
    print(f"Directional Flip  | Events: {len(flip_idx):>6} (Red: {f_red:>5.2f}%) | Matched: {f_match:>3} ({f_rec:>5.2f}%) | Prec: {f_prec:>5.2f}%")

    # Mechanism 3: Volatility Compression Reset (RSI or ATR cycle reset)
    # Require RSI to cycle through neutral (40-60) before next trigger
    rsi = panel['rsi_14'].values
    rsi_idx = []
    has_reset = True
    for idx in base_indices:
        if has_reset:
            rsi_idx.append(idx)
            has_reset = False
        else:
            # Check if RSI returned to neutral zone [45, 55] since last signal
            if 45 <= rsi[idx] <= 55:
                has_reset = True
    r_match, r_rec, r_prec = evaluate_match_indices(rsi_idx)
    r_red = (len(base_indices) - len(rsi_idx)) / len(base_indices) * 100.0
    debounce_records.append({
        'mechanism_name': 'Oscillator Neutral Reset (RSI 45-55)',
        'mechanism_type': 'Oscillator Reset',
        'parameter_val': 'RSI in [45, 55]',
        'generated_events': len(rsi_idx),
        'reduction_pct': r_red,
        'matched_real_trades': r_match,
        'recall_pct': r_rec,
        'precision_pct': r_prec
    })
    print(f"RSI Neutral Reset | Events: {len(rsi_idx):>6} (Red: {r_red:>5.2f}%) | Matched: {r_match:>3} ({r_rec:>5.2f}%) | Prec: {r_prec:>5.2f}%")

    deb_df = pd.DataFrame(debounce_records)
    deb_path = OUTPUTS_DIR / "phase8e_event_debounce.csv"
    deb_df.to_csv(deb_path, index=False)
    print(f"[PASS] Generated Event Debounce: {deb_path}")

    # -------------------------------------------------------------
    # 3. FORMAL FINITE STATE MACHINE (FSM) AUDIT
    # -------------------------------------------------------------
    print("\n--- 3. FORMAL FINITE STATE MACHINE (FSM) AUDIT ---")
    # States:
    # 0: S_OUTSIDE_HOURS (Outside 05:00-16:00 UTC or Friday post-20:00)
    # 1: S_FLAT_SCANNING (In session, PositionsTotal == 0, Cooldown clear)
    # 2: S_IN_POSITION (Holding active simulated trade, ~8 min)
    # 3: S_COOLDOWN (2 minutes post-exit)

    fsm_state = np.zeros(len(panel), dtype=int)
    state_names = {
        0: 'S_OUTSIDE_HOURS',
        1: 'S_FLAT_SCANNING',
        2: 'S_IN_POSITION',
        3: 'S_COOLDOWN'
    }

    holding_duration = 8
    cooldown_duration = 2

    current_state = 0
    timer = 0
    executed_trades = []

    # Run FSM over the 402,151 bars
    for i in range(len(panel)):
        hour = panel['hour'].iloc[i]
        dow = panel['dayofweek'].iloc[i]
        is_sess = (5 <= hour <= 16) and not (dow == 4 and hour >= 20)

        if not is_sess:
            current_state = 0
            timer = 0
        elif current_state == 2:  # In Position
            timer -= 1
            if timer <= 0:
                current_state = 3  # Transition to Cooldown
                timer = cooldown_duration
        elif current_state == 3:  # In Cooldown
            timer -= 1
            if timer <= 0:
                current_state = 1  # Transition to Flat Scanning
        else:  # Scanning (State 1) or entering session
            current_state = 1
            # Check for trigger: baseline edge crossing + ATR
            if baseline_edge[i]:
                executed_trades.append(i)
                current_state = 2  # Transition to In Position
                timer = holding_duration

        fsm_state[i] = current_state

    fsm_counts = pd.Series(fsm_state).value_counts().to_dict()
    fsm_matched, fsm_rec, fsm_prec = evaluate_match_indices(executed_trades)

    fsm_records = []
    for s_code, s_name in state_names.items():
        cnt = fsm_counts.get(s_code, 0)
        pct = cnt / len(panel) * 100.0
        fsm_records.append({
            'state_code': s_code,
            'state_name': s_name,
            'bars_in_state': cnt,
            'pct_of_history': pct,
            'trades_initiated': len(executed_trades) if s_code == 1 else 0,
            'trades_matched': fsm_matched if s_code == 1 else 0,
            'recall_pct': fsm_rec if s_code == 1 else 0.0,
            'precision_pct': fsm_prec if s_code == 1 else 0.0
        })
        print(f"FSM State [{s_name:<16}]: {cnt:>7} bars ({pct:>5.2f}%)")

    print(f"FSM Executed Trades: {len(executed_trades):>6} | Matched: {fsm_matched:>3} / 423 ({fsm_rec:>5.2f}%) | Precision: {fsm_prec:>5.2f}%")

    fsm_df = pd.DataFrame(fsm_records)
    fsm_path = OUTPUTS_DIR / "phase8e_state_machine.csv"
    fsm_df.to_csv(fsm_path, index=False)
    print(f"[PASS] Generated State Machine Audit: {fsm_path}")
    print(f"Completed in {time.time() - t0:.2f}s\n")
    return cross_df, deb_df, fsm_df

if __name__ == "__main__":
    run_trigger_and_debounce_analysis()
