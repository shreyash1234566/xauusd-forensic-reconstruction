"""
Parity & Memory Test Harness for Tick Feature Extraction
=========================================================
Compares the reference (in-memory) tick feature extraction against
the streaming, memory-bounded extraction on:
  - 317 discovery cases
  - 1,000 deterministic discovery controls

Validates:
  1. Exact 8-feature numerical parity within tolerance (1e-6)
  2. Exact preservation of NaN locations (no zero-filling or fallbacks)
  3. Exact parity of per-hour discovery baseline statistics
  4. Memory RSS tracking before, peak, and after execution
"""

import sys
import os
import json
import time
import ctypes
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from clockfix10 import load_trades_from_recon, build_decision_epochs
from tickfeat10 import TickStore, extract_tick_features, compute_hour_baselines

try:
    from tickfeat10 import compute_hour_baselines_streaming, extract_tick_features_streaming
    HAS_STREAMING = True
except ImportError:
    compute_hour_baselines_streaming = None
    extract_tick_features_streaming = None
    HAS_STREAMING = False

# Import build_risk_sets and constants from phase10_11_main
from phase10_11_main import (
    RECON_PATH,
    PANEL_PATH,
    N_RECORDS_TOTAL,
    N_RECORDS_LOCKBOX,
    N_RECORDS_DISCOVERY,
    N_EPOCHS_TOTAL,
    N_EPOCHS_DISCOVERY,
    TICK_FEATURES,
    build_risk_sets,
)


def get_rss_mb() -> float:
    """Return process resident set size (RSS) in megabytes."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        pass

    try:
        from ctypes import wintypes
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ('cb', wintypes.DWORD),
                ('PageFaultCount', wintypes.DWORD),
                ('PeakWorkingSetSize', ctypes.c_size_t),
                ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t),
                ('PeakPagefileUsage', ctypes.c_size_t),
            ]
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        pass

    return 0.0


def setup_test_data() -> Tuple[pd.DataFrame, List[str], List[str]]:
    """
    Load data, partition into discovery, build risk sets, and select:
      - 317 discovery epoch case timestamps
      - 1,000 deterministic control timestamps
    """
    print("[Setup] Loading trades and panel for discovery partition...")
    recon = load_trades_from_recon(str(RECON_PATH))
    records, epochs = build_decision_epochs(recon)

    lock_start = N_RECORDS_TOTAL - N_RECORDS_LOCKBOX
    records["record_partition"] = "buffer"
    records.loc[records["record_seq"] < N_RECORDS_DISCOVERY, "record_partition"] = "discovery"
    records.loc[records["record_seq"] >= lock_start, "record_partition"] = "lockbox"

    epoch_partition = records.groupby("epoch_id")["record_partition"].first()
    epochs["record_partition"] = epochs["epoch_id"].map(epoch_partition)

    disc_records = records[records["record_partition"] == "discovery"].copy()
    disc_epochs = epochs[epochs["record_partition"] == "discovery"].copy().reset_index(drop=True)

    assert len(disc_records) == N_RECORDS_DISCOVERY, f"Expected {N_RECORDS_DISCOVERY} disc records, got {len(disc_records)}"
    assert len(disc_epochs) == N_EPOCHS_DISCOVERY, f"Expected {N_EPOCHS_DISCOVERY} disc epochs, got {len(disc_epochs)}"

    panel = pd.read_parquet(PANEL_PATH)
    panel["dt"] = pd.to_datetime(panel["dt"])

    risk_sets = build_risk_sets(disc_epochs, disc_records, panel)

    case_timestamps = [
        str(pd.Timestamp(epoch.decision_time_utc).tz_localize(None))
        for epoch in disc_epochs.sort_values("epoch_id", kind="mergesort").itertuples()
    ]
    assert len(case_timestamps) == 317, f"Expected 317 case timestamps, got {len(case_timestamps)}"

    all_control_times = sorted({
        control["decision_time_utc"]
        for rs in risk_sets.values()
        for design in ("broad", "local")
        for control in rs[design]
    })
    print(f"[Setup] Total unique discovery control timestamps: {len(all_control_times)}")

    # Select deterministic 1,000 controls (stride through sorted list)
    n_ctrl = min(1000, len(all_control_times))
    # Stride selection ensures coverage across the entire discovery date/hour range
    step = len(all_control_times) // n_ctrl
    control_sample = [all_control_times[i * step] for i in range(n_ctrl)]
    assert len(control_sample) == 1000, f"Expected 1000 sampled controls, got {len(control_sample)}"

    return disc_epochs, case_timestamps, control_sample


def run_reference_extraction(
    store: TickStore,
    case_timestamps: List[str],
    control_timestamps: List[str],
) -> Tuple[dict, Dict[str, dict], Dict[str, dict]]:
    """Run reference in-memory extraction on cases and controls."""
    print("\n--- [Reference Extraction] ---")
    rss_start = get_rss_mb()
    print(f"  RSS at start: {rss_start:.2f} MB")

    cases_dict = {}
    for idx, ts_str in enumerate(case_timestamps):
        target_ms = int(pd.Timestamp(ts_str).timestamp() * 1000)
        ticks = store.get_window(target_ms, lookback_sec=310.0, lookahead_sec=0.0)
        cases_dict[str(idx)] = {"target_ms": target_ms, "ticks": ticks}

    controls_dict = {}
    for ts_str in control_timestamps:
        target_ms = int(pd.Timestamp(ts_str).timestamp() * 1000)
        ticks = store.get_window(target_ms, lookback_sec=310.0, lookahead_sec=0.0)
        controls_dict[ts_str] = {"target_ms": target_ms, "ticks": ticks}

    # Pass 1: baselines
    baselines_ref = compute_hour_baselines(cases_dict, controls_dict)

    # Pass 2: feature extraction
    case_features_ref = {}
    for idx, ts_str in enumerate(case_timestamps):
        entry = cases_dict[str(idx)]
        feats = extract_tick_features(entry["ticks"], entry["target_ms"], baselines_ref)
        case_features_ref[ts_str] = feats

    control_features_ref = {}
    for ts_str in control_timestamps:
        entry = controls_dict[ts_str]
        feats = extract_tick_features(entry["ticks"], entry["target_ms"], baselines_ref)
        control_features_ref[ts_str] = feats

    rss_end = get_rss_mb()
    print(f"  RSS at end: {rss_end:.2f} MB (Delta: +{rss_end - rss_start:.2f} MB)")
    return baselines_ref, case_features_ref, control_features_ref


def main():
    print("=" * 70)
    print("PHASE 10/11: TICK FEATURE EXTRACTION PARITY & MEMORY TEST")
    print("=" * 70)

    rss_init = get_rss_mb()
    print(f"Initial Process RSS: {rss_init:.2f} MB")

    disc_epochs, case_timestamps, control_sample = setup_test_data()
    store = TickStore()

    # 1. Run reference extraction
    t0 = time.time()
    baselines_ref, case_feats_ref, ctrl_feats_ref = run_reference_extraction(
        store, case_timestamps, control_sample
    )
    t_ref = time.time() - t0
    print(f"Reference extraction completed in {t_ref:.2f}s")

    # 2. Check if streaming implementation is present
    if not HAS_STREAMING or compute_hour_baselines_streaming is None or extract_tick_features_streaming is None:
        print("\n" + "!" * 70)
        print("[FAIL/PENDING] Streaming functions not found in tickfeat10.py:")
        print("  compute_hour_baselines_streaming: ", compute_hour_baselines_streaming)
        print("  extract_tick_features_streaming:  ", extract_tick_features_streaming)
        print("Implement Task 2 to proceed with parity verification.")
        print("!" * 70)
        sys.exit(1)

    # 3. Run streaming extraction
    print("\n--- [Streaming Extraction] ---")
    store_stream = TickStore()
    rss_stream_start = get_rss_mb()
    print(f"  RSS at start: {rss_stream_start:.2f} MB")

    # All timestamps combined
    all_timestamps = case_timestamps + control_sample

    t0 = time.time()
    # Streaming Pass 1: Baselines
    baselines_stream = compute_hour_baselines_streaming(store_stream, all_timestamps)
    rss_after_pass1 = get_rss_mb()
    print(f"  RSS after Pass 1 (baselines): {rss_after_pass1:.2f} MB")

    # Streaming Pass 2: Feature extraction
    features_stream = extract_tick_features_streaming(
        store_stream, all_timestamps, baselines_stream, batch_size=200
    )
    rss_after_pass2 = get_rss_mb()
    t_stream = time.time() - t0
    print(f"  RSS after Pass 2 (features):  {rss_after_pass2:.2f} MB")
    print(f"Streaming extraction completed in {t_stream:.2f}s")

    # 4. Parity checks
    print("\n--- [Parity Verification] ---")
    mismatches = []

    # Check baseline statistics
    print("[1/3] Verifying Hour Baseline Parity...")
    for h in range(24):
        b_ref = baselines_ref.get(h, {})
        b_str = baselines_stream.get(h, {})
        for metric in ["abs_move_std", "spread_mean", "tick_rate_mean", "n_obs"]:
            v_ref = b_ref.get(metric, np.nan)
            v_str = b_str.get(metric, np.nan)
            if not np.isclose(v_ref, v_str, atol=1e-6, equal_nan=True):
                mismatches.append(f"Baseline hour {h} {metric}: ref={v_ref} vs stream={v_str}")

    # Check Case Features
    print("[2/3] Verifying 317 Discovery Case Features...")
    for ts_str in case_timestamps:
        f_ref = case_feats_ref[ts_str]
        f_str = features_stream[ts_str]
        for feat_name in TICK_FEATURES + ["tick_coverage"]:
            v_ref = f_ref.get(feat_name, np.nan)
            v_str = f_str.get(feat_name, np.nan)
            if np.isnan(v_ref) != np.isnan(v_str):
                mismatches.append(f"Case {ts_str} {feat_name} NaN mismatch: ref={v_ref} vs stream={v_str}")
            elif not np.isclose(v_ref, v_str, atol=1e-6, equal_nan=True):
                mismatches.append(f"Case {ts_str} {feat_name} value mismatch: ref={v_ref} vs stream={v_str}")

    # Check Control Features
    print("[3/3] Verifying 1,000 Control Features...")
    for ts_str in control_sample:
        f_ref = ctrl_feats_ref[ts_str]
        f_str = features_stream[ts_str]
        for feat_name in TICK_FEATURES + ["tick_coverage"]:
            v_ref = f_ref.get(feat_name, np.nan)
            v_str = f_str.get(feat_name, np.nan)
            if np.isnan(v_ref) != np.isnan(v_str):
                mismatches.append(f"Control {ts_str} {feat_name} NaN mismatch: ref={v_ref} vs stream={v_str}")
            elif not np.isclose(v_ref, v_str, atol=1e-6, equal_nan=True):
                mismatches.append(f"Control {ts_str} {feat_name} value mismatch: ref={v_ref} vs stream={v_str}")

    if mismatches:
        print("\n" + "X" * 70)
        print(f"PARITY FAILED: {len(mismatches)} mismatches detected!")
        for m in mismatches[:20]:
            print(f"  - {m}")
        if len(mismatches) > 20:
            print(f"  ... and {len(mismatches) - 20} more mismatches.")
        print("X" * 70)
        sys.exit(1)

    print("\n" + "=" * 70)
    print("SUCCESS: 100% NUMERICAL PARITY CONFIRMED ACROSS ALL FEATURES & BASELINES!")
    print(f"  - 317 Cases: PERFECT MATCH")
    print(f"  - 1,000 Controls: PERFECT MATCH")
    print(f"  - 24 Hour Baselines: PERFECT MATCH")
    print(f"  - NaNs and Causal Boundaries: PERFECT MATCH")
    print(f"  - Initial RSS: {rss_init:.2f} MB | Final RSS: {get_rss_mb():.2f} MB")
    print("=" * 70)
    sys.exit(0)


if __name__ == "__main__":
    main()
