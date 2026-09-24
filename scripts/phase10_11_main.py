"""
Phase 10/11 — Main Analysis Pipeline
=====================================
Orchestrates the full entry-selection analysis:

  M0  Null (intercept-only / within-stratum constant)
  M1  Clock/timing features only
  M2  Clock + M1 bar features (LAGGED — previous completed bar)
  M3  Clock + tick features
  M4  Clock + M1 (lagged) + tick features

All exploration uses DISCOVERY SET ONLY (chronologically first 320 trades).
The 102-trade lockbox is NOT touched.

Outputs (all to outputs/strategy_reconstruction/):
  phase10_11_entry_logic_audit.md
  phase10_11_risk_sets.json
  phase10_11_features.parquet
  phase10_11_model_results.json
  phase10_11_permutation_results.json
  phase10_11_planted_truth.json
  phase10_11_entry_mechanism_report.md

Lockbox evaluation:
  phase10_11_lockbox_results.json   ← written ONLY in final step, ONCE
"""

import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from clockfix10 import load_trades_from_recon, build_decision_epochs
from tickfeat10 import (
    TickStore,
    compute_hour_baselines_streaming,
    extract_tick_features_streaming,
    compute_hour_baselines_from_raw_features,
    rescale_tick_features_for_baselines,
    IndexedTickControls,
)
from model_lib10b import (
    fit_conditional_logit,
    select_lambda_cv,
    permutation_test,
    standardize,
    ConditionalLogitResult,
    _conditional_log_lik_and_grad,
)

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
RECON_PATH = ROOT / "outputs" / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
PANEL_PATH = ROOT / "data" / "processed" / "decision_panel.parquet"
OUTPUT_DIR = ROOT / "outputs" / "strategy_reconstruction"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
N_RECORDS_TOTAL = 423
N_RECORDS_LOCKBOX = 102
N_RECORDS_DISCOVERY = 320
N_RECORDS_BUFFER = N_RECORDS_TOTAL - N_RECORDS_LOCKBOX - N_RECORDS_DISCOVERY
N_EPOCHS_TOTAL = 420
N_EPOCHS_LOCKBOX = 102
N_EPOCHS_DISCOVERY = 317
N_EPOCHS_BUFFER = 1
N_PERM       = 499                    # permutation reps per model
SEED         = 42
SESSION_HOUR_MIN = 5
SESSION_HOUR_MAX = 16
# M1 features to use (LAGGED — previous completed bar)
M1_FEATURES  = [
    "return_1", "return_5", "return_15", "return_30",
    "rsi_14", "bb_pct_b", "atr_pct_14", "candle_body_ratio",
    "dist_ema_21", "dist_ema_50",
    "h1_rsi_14", "h1_atr_pct_14",
]
# Tick features from tickfeat10
TICK_FEATURES = [
    "jump_z", "disp30", "tick_rate_30", "tick_rate_ratio",
    "spread_now", "spread_ratio", "ret5", "n_ticks_300",
]
# Clock features (derived from open_utc)
CLOCK_FEATURES = ["utc_hour", "utc_minute", "day_of_week", "is_monday", "is_friday"]


# ─────────────────────────────────────────────────────────────────────────────
# 1. LOAD & SPLIT
# ─────────────────────────────────────────────────────────────────────────────
def load_and_split():
    print("\n[1] Loading data, deriving epochs, and performing chronological split...")
    recon = load_trades_from_recon(str(RECON_PATH))
    records, epochs = build_decision_epochs(recon)

    lock_start = N_RECORDS_TOTAL - N_RECORDS_LOCKBOX
    records["record_partition"] = "buffer"
    records.loc[records["record_seq"] < N_RECORDS_DISCOVERY, "record_partition"] = "discovery"
    records.loc[records["record_seq"] >= lock_start, "record_partition"] = "lockbox"

    partition_counts = records.groupby("epoch_id")["record_partition"].nunique()
    if not partition_counts.eq(1).all():
        raise AssertionError("A decision epoch crosses the frozen record partition boundary")
    epoch_partition = records.groupby("epoch_id")["record_partition"].first()
    epochs["record_partition"] = epochs["epoch_id"].map(epoch_partition)

    disc_records = records[records["record_partition"] == "discovery"].copy()
    buffer_records = records[records["record_partition"] == "buffer"].copy()
    lock_records = records[records["record_partition"] == "lockbox"].copy()
    disc_epochs = epochs[epochs["record_partition"] == "discovery"].copy().reset_index(drop=True)
    buffer_epochs = epochs[epochs["record_partition"] == "buffer"].copy().reset_index(drop=True)
    lock_epochs = epochs[epochs["record_partition"] == "lockbox"].copy().reset_index(drop=True)

    assert len(records) == N_RECORDS_TOTAL
    assert len(disc_records) == N_RECORDS_DISCOVERY
    assert len(buffer_records) == N_RECORDS_BUFFER
    assert len(lock_records) == N_RECORDS_LOCKBOX
    assert len(epochs) == N_EPOCHS_TOTAL
    assert len(disc_epochs) == N_EPOCHS_DISCOVERY
    assert len(buffer_epochs) == N_EPOCHS_BUFFER
    assert len(lock_epochs) == N_EPOCHS_LOCKBOX

    print(f"    Discovery: {len(disc_records)} records / {len(disc_epochs)} epochs")
    print(f"    Buffer:    {len(buffer_records)} records / {len(buffer_epochs)} epochs")
    print(f"    Lockbox:   {len(lock_records)} records / {len(lock_epochs)} epochs")

    partition_certificate = {
        "records": {"total": len(records), "discovery": len(disc_records), "buffer": len(buffer_records), "lockbox": len(lock_records)},
        "epochs": {"total": len(epochs), "discovery": len(disc_epochs), "buffer": len(buffer_epochs), "lockbox": len(lock_epochs)},
        "record_boundary": {"discovery_stop_exclusive": N_RECORDS_DISCOVERY, "lockbox_start": lock_start},
        "cross_partition_epochs": [],
    }
    (OUTPUT_DIR / "phase10_11_decision_epoch_map.csv").parent.mkdir(parents=True, exist_ok=True)
    records.to_csv(OUTPUT_DIR / "phase10_11_decision_epoch_map.csv", index=False)
    with open(OUTPUT_DIR / "phase10_11_epoch_partition.json", "w") as fh:
        json.dump(partition_certificate, fh, indent=2)

    panel = pd.read_parquet(PANEL_PATH)
    panel["dt"] = pd.to_datetime(panel["dt"])

    return disc_epochs, lock_epochs, panel, records, epochs


# ─────────────────────────────────────────────────────────────────────────────
# 2. BUILD PANEL LOOKUP — lagged M1 features
# ─────────────────────────────────────────────────────────────────────────────
def build_lagged_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """
    For each M1 bar at time B, we want the features of bar B-1 (last completed bar).
    Apply panel.shift(1) so that the row at time B holds B-1's feature values.
    Keep the original 'dt', 'is_trade', 'utc_hour', 'utc_minute' intact.
    """
    panel = panel.sort_values("dt").reset_index(drop=True)

    # Columns that stay at current bar (not lagged)
    meta_cols = ["dt", "is_trade", "trade_dir", "utc_hour", "utc_minute"]

    # Lag the M1 feature columns
    shift_cols = [c for c in M1_FEATURES if c in panel.columns]
    lag = panel[shift_cols].shift(1)
    lag.columns = [f"{c}_lag1" for c in shift_cols]

    result = pd.concat([panel[meta_cols], lag], axis=1)
    result = result.dropna(subset=[f"{c}_lag1" for c in shift_cols])
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 3. BUILD RISK SETS (BROAD + LOCAL)
# ─────────────────────────────────────────────────────────────────────────────
def build_risk_sets(
    epochs: pd.DataFrame,
    records_for_eligibility: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    output_path: Path | None = None,
) -> dict:
    """Build exact-resolution broad and local risk sets for decision epochs.

    ``records_for_eligibility`` must be confined to the permitted information
    boundary.  Discovery invokes this with discovery records only; that avoids
    looking into buffer/lockbox position timing.  A candidate M1 minute receives
    the case's within-minute phase and is eligible only when that exact decision
    timestamp is outside every half-open record interval ``[open, close)``.
    """
    print("\n[3] Building epoch risk sets (broad + local)...")
    required_epoch_cols = {"epoch_id", "decision_epoch_utc", "decision_time_utc", "anchor_open_utc"}
    if missing := required_epoch_cols.difference(epochs.columns):
        raise ValueError(f"Epoch table missing columns: {sorted(missing)}")

    panel_sorted = panel.sort_values("dt").reset_index(drop=True).copy()
    panel_sorted["_hour"] = panel_sorted["dt"].dt.hour
    panel_sorted["_date"] = panel_sorted["dt"].dt.date
    in_session = (panel_sorted["_hour"] >= SESSION_HOUR_MIN) & (panel_sorted["_hour"] <= SESSION_HOUR_MAX)
    candidate_minutes = panel_sorted[in_session].copy()

    intervals = [
        (open_ts.tz_localize(None), close_ts.tz_localize(None))
        for open_ts, close_ts in zip(records_for_eligibility["open_utc"], records_for_eligibility["close_utc"])
    ]

    def is_eligible_at(exact_time: pd.Timestamp) -> bool:
        return not any(open_ts <= exact_time < close_ts for open_ts, close_ts in intervals)

    risk_sets: dict[str, dict] = {}
    broad_counts, local_counts = [], []
    for epoch in epochs.sort_values("epoch_id", kind="mergesort").itertuples():
        case_time = pd.Timestamp(epoch.decision_time_utc).tz_localize(None)
        case_floor = pd.Timestamp(epoch.decision_epoch_utc).tz_localize(None)
        phase = case_time - case_floor
        if phase < pd.Timedelta(0) or phase >= pd.Timedelta("1min"):
            raise AssertionError(f"Invalid within-minute phase for epoch {epoch.epoch_id}")

        def build_controls(frame: pd.DataFrame) -> list[dict]:
            controls = []
            for minute in frame["dt"]:
                minute = pd.Timestamp(minute)
                if minute == case_floor:
                    continue
                exact_time = minute + phase
                if is_eligible_at(exact_time):
                    controls.append({
                        "bar_open_utc": str(minute),
                        "decision_time_utc": str(exact_time),
                    })
            return controls

        broad = build_controls(candidate_minutes[candidate_minutes["_date"] == case_time.date()])
        local = build_controls(candidate_minutes[
            (candidate_minutes["_hour"] == case_time.hour)
            & (candidate_minutes["_date"] != case_time.date())
        ])
        key = str(int(epoch.epoch_id))
        risk_sets[key] = {
            "epoch_id": int(epoch.epoch_id),
            "decision_epoch_utc": str(case_floor),
            "case_decision_time_utc": str(case_time),
            "anchor_open_utc": str(pd.Timestamp(epoch.anchor_open_utc)),
            "record_count": int(epoch.record_count),
            "tickets": epoch.tickets,
            "within_minute_phase_ms": int(phase / pd.Timedelta(milliseconds=1)),
            "broad": broad,
            "local": local,
        }
        broad_counts.append(len(broad))
        local_counts.append(len(local))

    print(f"    Broad risk set  — mean controls/epoch: {np.mean(broad_counts):.1f}  min: {np.min(broad_counts)}  max: {np.max(broad_counts)}")
    print(f"    Local risk set  — mean controls/epoch: {np.mean(local_counts):.1f}  min: {np.min(local_counts)}  max: {np.max(local_counts)}")
    if output_path is not None:
        with open(output_path, "w") as fh:
            json.dump({"n_epochs": len(epochs), "risk_sets": risk_sets}, fh, indent=2)
        print(f"    Saved: {output_path}")
    return risk_sets


# ─────────────────────────────────────────────────────────────────────────────
# 4 & 5. EXTRACT TICK FEATURES (cases + controls)
# ─────────────────────────────────────────────────────────────────────────────
def extract_all_tick_features_streaming(
    epochs: pd.DataFrame,
    risk_sets: dict,
    baselines: dict | None = None,
    output_parquet: Path | str | None = None,
) -> tuple[dict, dict]:
    """Fetch causal tick features for every unique exact event timestamp.

    If `baselines` is not provided, computes them from ALL provided timestamps (which
    must be the discovery set).
    If `output_parquet` is provided, streams the features directly to Parquet and
    indexes them in-memory via IndexedTickControls, bounded to ~425MB memory.

    Returns (tick_data, baselines).
    """
    print("\n[4/5] Extracting causal tick features (streaming)...")
    store = TickStore()

    case_times = {}
    for epoch in epochs.sort_values("epoch_id", kind="mergesort").itertuples():
        case_times[str(int(epoch.epoch_id))] = pd.Timestamp(epoch.decision_time_utc).tz_localize(None)

    exact_control_times = {
        control["decision_time_utc"]
        for risk_set in risk_sets.values()
        for design in ("broad", "local")
        for control in risk_set[design]
    }

    all_ts = sorted(list(set(case_times.values()) | {pd.Timestamp(t) for t in exact_control_times}))

    if baselines is None:
        print(f"\n[4] Computing per-hour tick baselines from {len(all_ts):,} events (streaming Pass 1)...")
        baselines = compute_hour_baselines_streaming(store, all_ts, progress_interval=50000)
        for h in sorted(baselines.keys()):
            bl = baselines[h]
            if bl["n_obs"] > 0:
                print(f"    Hour {h:02d} UTC: n={bl['n_obs']:4d}  "
                      f"abs_move_std={bl['abs_move_std']:.4f}  "
                      f"spread_mean={bl['spread_mean']:.4f}")
    else:
        print("\n[4] Using provided baselines (skipping Pass 1)...")

    print(f"\n[5] Extracting tick features for {len(all_ts):,} events (streaming Pass 2)...")
    if output_parquet is not None:
        extract_tick_features_streaming(
            store=store,
            timestamps=all_ts,
            baselines=baselines,
            batch_size=10000,
            output_path=output_parquet,
            progress_interval=50000,
        )
        indexed_store = IndexedTickControls(output_parquet)

        cases_feats = {}
        for epoch_key, ts in case_times.items():
            cases_feats[epoch_key] = indexed_store.get(ts)

        controls_feats = indexed_store
    else:
        feature_dict = extract_tick_features_streaming(
            store=store,
            timestamps=all_ts,
            baselines=baselines,
            batch_size=10000,
            output_path=None,
            progress_interval=50000,
        )

        cases_feats = {}
        for epoch_key, ts in case_times.items():
            ts_str = str(ts)
            f_dict = feature_dict.get(ts_str, {})
            target_ms = int(ts.timestamp() * 1000)
            cases_feats[epoch_key] = {"target_ms": target_ms, "features": f_dict}

        controls_feats = {}
        for ts_str in exact_control_times:
            ts = pd.Timestamp(ts_str)
            f_dict = feature_dict.get(str(ts), {})
            target_ms = int(ts.timestamp() * 1000)
            controls_feats[ts_str] = {"target_ms": target_ms, "features": f_dict}

    tick_data = {"cases": cases_feats, "controls": controls_feats}
    return tick_data, baselines

def _feature_vector(feats: dict | list | np.ndarray | None, names: list[str]) -> np.ndarray | None:
    """Return a complete feature vector, or None for unavailable data."""
    if feats is None:
        return None
    if isinstance(feats, np.ndarray):
        return None if np.isnan(feats).any() else feats.astype(np.float64)
    if isinstance(feats, list):
        arr = np.asarray(feats, dtype=np.float64)
        return None if np.isnan(arr).any() else arr
    if isinstance(feats, dict):
        values = [feats.get(name, np.nan) for name in names]
        if any(pd.isna(v) for v in values):
            return None
        return np.asarray(values, dtype=np.float64)
    return None

# ─────────────────────────────────────────────────────────────────────────────
# 6. ASSEMBLE FEATURE MATRIX FOR MODEL FITTING
# ─────────────────────────────────────────────────────────────────────────────
def assemble_feature_matrix(
    disc: pd.DataFrame,
    risk_sets: dict,
    tick_data: dict,
    baselines: dict,
    lagged_panel: pd.DataFrame,
    design: str = "broad",   # "broad" or "local"
) -> tuple:
    """
    Build X (N_obs, D), y (N_obs,), groups (N_obs,) for conditional logit.
    Each case forms one stratum with its risk-set controls.

    Returns (X_clock, X_m1, X_tick, y, groups, feature_names_clock,
             feature_names_m1, feature_names_tick)
    """
    print(f"\n[6] Assembling feature matrix (design={design})...")

    # Build panel lookup: dt -> lagged M1 feature row
    lag_cols = [f"{c}_lag1" for c in M1_FEATURES if f"{c}_lag1" in lagged_panel.columns]
    panel_lut = lagged_panel.set_index("dt")[lag_cols]

    epoch_by_id = disc.set_index("epoch_id")

    rows_clock = []
    rows_m1    = []
    rows_tick  = []
    y_list     = []
    g_list     = []

    stratum_id = 0
    n_skipped  = 0

    for case_key, rs in risk_sets.items():
        ctrl_key = "broad" if design == "broad" else "local"
        ctrl_list = rs[ctrl_key]
        epoch_id = int(rs["epoch_id"])
        case_open = pd.Timestamp(rs["case_decision_time_utc"])
        case_floor = pd.Timestamp(rs["decision_epoch_utc"])
        case_prev = case_floor - pd.Timedelta("1min")

        if len(ctrl_list) < 5 or epoch_id not in epoch_by_id.index:
            n_skipped += 1
            continue

        # Clock features for case
        def clock_feats(dt_naive: pd.Timestamp) -> list:
            return [
                float(dt_naive.hour),
                float(dt_naive.minute),
                float(dt_naive.dayofweek),
                float(1 if dt_naive.dayofweek == 0 else 0),
                float(1 if dt_naive.dayofweek == 4 else 0),
            ]

        case_clock = clock_feats(case_open)

        # Lagged M1 features for case (from previous bar)
        if case_floor in panel_lut.index:
            case_m1_values = panel_lut.loc[case_floor, lag_cols].values
        else:
            case_m1_values = np.full(len(lag_cols), np.nan)
        if np.isnan(case_m1_values.astype(float)).any():
            n_skipped += 1
            continue
        case_m1 = case_m1_values.astype(float).tolist()

        # Tick features for case
        ctd = tick_data["cases"].get(str(epoch_id), {})
        case_tick_feats = ctd.get("features", {})
        case_tick_row = _feature_vector(case_tick_feats, TICK_FEATURES)
        if case_tick_row is None:
            n_skipped += 1
            continue
        case_tick_row = case_tick_row.tolist()

        rows_clock.append(case_clock)
        rows_m1.append(case_m1)
        rows_tick.append(case_tick_row)
        y_list.append(1)
        g_list.append(stratum_id)

        # ── Control rows ──
        for ctrl_dt_str in ctrl_list:
            ctrl_record = ctrl_dt_str
            ctrl_dt = pd.Timestamp(ctrl_record["decision_time_utc"])
            ctrl_bar = pd.Timestamp(ctrl_record["bar_open_utc"])

            ctrl_clock = clock_feats(ctrl_dt)

            if ctrl_bar in panel_lut.index:
                ctrl_m1_values = panel_lut.loc[ctrl_bar, lag_cols].values
            else:
                ctrl_m1_values = np.full(len(lag_cols), np.nan)
            if np.isnan(ctrl_m1_values.astype(float)).any():
                continue
            ctrl_m1 = ctrl_m1_values.astype(float).tolist()

            ctrl_exact = ctrl_record["decision_time_utc"]
            ctd_c = tick_data["controls"].get(ctrl_exact, {})
            ctrl_tick_feats = ctd_c.get("features", {})
            ctrl_tick_row = _feature_vector(ctrl_tick_feats, TICK_FEATURES)
            if ctrl_tick_row is None:
                continue
            ctrl_tick_row = ctrl_tick_row.tolist()

            rows_clock.append(ctrl_clock)
            rows_m1.append(ctrl_m1)
            rows_tick.append(ctrl_tick_row)
            y_list.append(0)
            g_list.append(stratum_id)

        stratum_id += 1

    print(f"    Strata assembled: {stratum_id}  (skipped {n_skipped} with <5 controls)")
    print(f"    Total observations: {len(y_list)}  (cases: {sum(y_list)}, controls: {sum(1-v for v in y_list)})")

    X_clock = np.array(rows_clock, dtype=np.float64)
    X_m1    = np.array(rows_m1,    dtype=np.float64)
    X_tick  = np.array(rows_tick,  dtype=np.float64)
    y       = np.array(y_list,     dtype=int)
    groups  = np.array(g_list,     dtype=int)

    return X_clock, X_m1, X_tick, y, groups, CLOCK_FEATURES, lag_cols, TICK_FEATURES


# ─────────────────────────────────────────────────────────────────────────────
# 7. FIT MODEL LADDER
# ─────────────────────────────────────────────────────────────────────────────
def fit_model_ladder(X_clock, X_m1, X_tick, y, groups,
                     names_clock, names_m1, names_tick, design_label: str) -> dict:
    print(f"\n[7] Fitting model ladder (design={design_label})...")

    results = {}

    def fit_with_cv(X, names, label):
        print(f"    [{label}] Selecting lambda by LOGO-CV...")
        X_std, mu, sd = standardize(X)
        t0 = time.time()
        best_lam, cv_lls = select_lambda_cv(X_std, y, groups)
        t1 = time.time()
        print(f"    [{label}] Best λ={best_lam:.4f}  CV-LL={cv_lls[best_lam]:.4f}  ({t1-t0:.1f}s)")

        result = fit_conditional_logit(X_std, y, groups, lam=best_lam, feature_names=names)
        print(f"    [{label}] LL={result.log_lik:.4f}  null_LL={result.null_log_lik:.4f}  "
              f"pseudo_R2={result.pseudo_r2:.4f}  converged={result.converged}")
        return result, best_lam, mu, sd

    # M0: exact conditional null, with no feature optimization
    X_null = np.zeros((len(y), 0), dtype=np.float64)
    r_m0, lam_m0, mu_m0, sd_m0 = fit_with_cv(X_null, ["intercept_proxy"], "M0-null")
    results["M0"] = {
        "log_lik": r_m0.log_lik, "null_log_lik": r_m0.null_log_lik,
        "pseudo_r2": r_m0.pseudo_r2, "lam": lam_m0,
        "converged": r_m0.converged, "design": design_label,
    }

    # M1: clock only
    X_clk = X_clock.copy()
    r_m1, lam_m1, mu_m1, sd_m1 = fit_with_cv(X_clk, names_clock, "M1-clock")
    results["M1"] = {
        "log_lik": r_m1.log_lik, "null_log_lik": r_m1.null_log_lik,
        "pseudo_r2": r_m1.pseudo_r2, "lam": lam_m1,
        "converged": r_m1.converged, "design": design_label,
        "summary": r_m1.summary(),
    }

    # M2: clock + M1 (lagged)
    X_m2 = np.hstack([X_clock, X_m1])
    r_m2, lam_m2, mu_m2, sd_m2 = fit_with_cv(X_m2, names_clock + names_m1, "M2-clock+M1")
    results["M2"] = {
        "log_lik": r_m2.log_lik, "null_log_lik": r_m2.null_log_lik,
        "pseudo_r2": r_m2.pseudo_r2, "lam": lam_m2,
        "converged": r_m2.converged, "design": design_label,
        "summary": r_m2.summary(),
    }

    # M3: clock + tick
    X_m3 = np.hstack([X_clock, X_tick])
    r_m3, lam_m3, mu_m3, sd_m3 = fit_with_cv(X_m3, names_clock + names_tick, "M3-clock+tick")
    results["M3"] = {
        "log_lik": r_m3.log_lik, "null_log_lik": r_m3.null_log_lik,
        "pseudo_r2": r_m3.pseudo_r2, "lam": lam_m3,
        "converged": r_m3.converged, "design": design_label,
        "summary": r_m3.summary(),
        "beta": r_m3.beta.tolist(),
        "feature_names": r_m3.feature_names,
    }

    # M4: clock + M1 + tick
    X_m4 = np.hstack([X_clock, X_m1, X_tick])
    r_m4, lam_m4, mu_m4, sd_m4 = fit_with_cv(X_m4, names_clock + names_m1 + names_tick, "M4-full")
    results["M4"] = {
        "log_lik": r_m4.log_lik, "null_log_lik": r_m4.null_log_lik,
        "pseudo_r2": r_m4.pseudo_r2, "lam": lam_m4,
        "converged": r_m4.converged, "design": design_label,
        "summary": r_m4.summary(),
        "beta": r_m4.beta.tolist(),
        "feature_names": r_m4.feature_names,
    }

    # Store fitted objects for permutation test
    results["_fitted"] = {
        "M1": (r_m1, X_clk, lam_m1),
        "M3": (r_m3, X_m3, lam_m3),
        "M4": (r_m4, X_m4, lam_m4),
    }

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 8. PERMUTATION TESTS
# ─────────────────────────────────────────────────────────────────────────────
def run_permutation_tests(model_results: dict, y: np.ndarray,
                          groups: np.ndarray, design_label: str, n_perm: int = N_PERM) -> dict:
    print(f"\n[8] Running permutation tests (n_perm={n_perm}, design={design_label})...")
    perm_results = {}
    fitted = model_results.pop("_fitted", {})

    for model_label, (result, X_std, lam) in fitted.items():
        print(f"    [{model_label}] Running {n_perm} permutations...")
        t0 = time.time()
        ptest = permutation_test(
            X_std, y, groups,
            lam=lam,
            observed_ll=result.log_lik,
            n_perm=n_perm,
            seed=SEED,
            feature_names=result.feature_names,
        )
        t1 = time.time()
        print(f"    [{model_label}] p-value={ptest['p_value']:.4f}  "
              f"null_mean={ptest['null_ll_mean']:.4f}  ({t1-t0:.1f}s)")
        perm_results[model_label] = ptest

    return perm_results


# ─────────────────────────────────────────────────────────────────────────────
# 9. PLANTED-TRUTH RECOVERY TEST
# ─────────────────────────────────────────────────────────────────────────────
def run_planted_truth_test(X_clock, X_tick, y, groups) -> dict:
    """
    Inject a synthetic signal with known true_beta, verify recovery.
    This validates the model's ability to find a real signal before trusting
    inference on the unknown true signal.
    """
    print("\n[9] Planted-truth recovery test...")
    rng = np.random.RandomState(SEED + 1)

    # Plant a signal in the first 2 tick features
    true_beta_tick = np.zeros(X_tick.shape[1])
    true_beta_tick[0] = 2.0   # jump_z → cases have larger jumps
    true_beta_tick[1] = 1.5   # disp30 → cases have larger displacement

    # Modify y within each group to follow the planted signal
    planted_y = y.copy()
    unique_groups = np.unique(groups)

    from scipy.special import logsumexp as _lse

    for g in unique_groups:
        mask_g = groups == g
        idx_g  = np.where(mask_g)[0]
        X_g    = X_tick[mask_g]
        eta_g  = X_g @ true_beta_tick
        probs_g = np.exp(eta_g - _lse(eta_g))
        # Assign case to the highest-prob member
        case_pos = rng.choice(len(idx_g), p=probs_g)
        planted_y[mask_g] = 0
        planted_y[idx_g[case_pos]] = 1

    # Fit M3 on planted data
    X_m3_plant = np.hstack([X_clock, X_tick])
    X_std, mu, sd = standardize(X_m3_plant)
    best_lam, _ = select_lambda_cv(X_std, planted_y, groups)
    result_plant = fit_conditional_logit(X_std, planted_y, groups, lam=best_lam,
                                         feature_names=CLOCK_FEATURES + TICK_FEATURES)

    # Check recovery: first 2 tick features should have the largest positive betas
    # within the tick feature sub-vector
    n_clock = len(CLOCK_FEATURES)
    tick_betas = result_plant.beta[n_clock:]
    top2_idx   = np.argsort(tick_betas)[-2:]
    recovered  = sorted(top2_idx.tolist()) == [0, 1]

    print(f"    True beta[0..1]: {true_beta_tick[0]:.2f}, {true_beta_tick[1]:.2f}")
    print(f"    Recovered tick betas: {tick_betas.round(3)}")
    print(f"    Top-2 tick features: {[TICK_FEATURES[i] for i in top2_idx]}")
    print(f"    Planted-truth RECOVERED: {recovered}")

    return {
        "true_beta": true_beta_tick.tolist(),
        "recovered_betas": tick_betas.tolist(),
        "top2_recovered": recovered,
        "pseudo_r2": result_plant.pseudo_r2,
        "p_value_vs_null": float((result_plant.log_lik - result_plant.null_log_lik) / abs(result_plant.null_log_lik)),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 10. CHRONOLOGICAL WALK-FORWARD VALIDATION
# ─────────────────────────────────────────────────────────────────────────────
def chronological_validation(disc: pd.DataFrame, risk_sets: dict,
                              tick_data: dict, baselines: dict,
                              lagged_panel: pd.DataFrame) -> dict:
    """Chronological walk-forward validation within the discovery epoch set.

    Evaluates candidate lambda values across 4 expanding walk-forward folds
    for both M3 (Clock + Tick) and M4 (Clock + Lagged M1 + Tick).
    At each fold, hourly baselines and feature standardization are computed
    strictly from the training strata observations of that fold, eliminating
    future baseline leakage.
    """
    print("\n[10] Chronological walk-forward validation (4 expanding folds, M3 and M4, multi-lambda)...")
    disc_sorted = disc.sort_values("epoch_id", kind="mergesort").reset_index(drop=True)
    ordered_epoch_ids = disc_sorted["epoch_id"].tolist()

    lag_cols = [f"{c}_lag1" for c in M1_FEATURES if f"{c}_lag1" in lagged_panel.columns]
    panel_lut = lagged_panel.set_index("dt")[lag_cols]

    candidate_lambdas = [1e-4, 1e-3, 5e-3, 1e-2, 5e-2, 1e-1, 5e-1, 1.0]

    folds_def = [
        (1, 0, 64, 64, 127),
        (2, 0, 127, 127, 190),
        (3, 0, 190, 190, 253),
        (4, 0, 253, 253, 317),
    ]

    fold_results_m3 = []
    fold_results_m4 = []

    def cf(dt):
        return [float(dt.hour), float(dt.minute), float(dt.dayofweek),
                float(dt.dayofweek == 0), float(dt.dayofweek == 4)]

    for fold_k, tr_start, tr_end, te_start, te_end in folds_def:
        tr_epoch_ids = ordered_epoch_ids[tr_start:tr_end]
        te_epoch_ids = ordered_epoch_ids[te_start:te_end]

        print(f"\n    Fold {fold_k}: train=[{tr_start},{tr_end}) ({len(tr_epoch_ids)} epochs), "
              f"test=[{te_start},{te_end}) ({len(te_epoch_ids)} epochs)")

        # 1. Collect raw training feature dictionaries from valid risk set observations
        train_raw_feats = []
        for eid in tr_epoch_ids:
            key = str(int(eid))
            if key not in risk_sets:
                continue
            rs = risk_sets[key]
            ctrl_list = rs.get("broad", [])
            if len(ctrl_list) < 5:
                continue
            ctd = tick_data["cases"].get(key, {})
            ctf = ctd.get("features")
            if ctf is not None:
                train_raw_feats.append(ctf)
            for ctrl in ctrl_list:
                c_dt_str = ctrl["decision_time_utc"]
                ctd_c = tick_data["controls"].get(c_dt_str, {})
                ctf_c = ctd_c.get("features")
                if ctf_c is not None:
                    train_raw_feats.append(ctf_c)

        # 2. Compute fold-specific hourly baselines strictly from training observations
        fold_baselines = compute_hour_baselines_from_raw_features(train_raw_feats)

        # 3. Helper to assemble fold matrix with fold baselines
        def build_matrices(epoch_id_slice):
            rows_clock, rows_m1, rows_tick, y_l, g_l = [], [], [], [], []
            stratum = 0
            for eid in epoch_id_slice:
                key = str(int(eid))
                if key not in risk_sets:
                    continue
                rs = risk_sets[key]
                ctrl_list = rs.get("broad", [])
                if len(ctrl_list) < 5:
                    continue
                epoch_decision_time = pd.Timestamp(rs["case_decision_time_utc"])
                epoch_floor = pd.Timestamp(rs["decision_epoch_utc"])

                # Lagged M1 for case
                if epoch_floor in panel_lut.index:
                    case_m1v = panel_lut.loc[epoch_floor, lag_cols].values.astype(float)
                else:
                    case_m1v = np.full(len(lag_cols), np.nan)
                if np.isnan(case_m1v).any():
                    continue

                ctd = tick_data["cases"].get(key, {})
                if ctd.get("target_ms") is None:
                    continue
                ctf = ctd.get("features", {})
                rescaled_ctf = rescale_tick_features_for_baselines(ctf, fold_baselines)
                case_tick_row = _feature_vector(rescaled_ctf, TICK_FEATURES)
                if case_tick_row is None:
                    continue

                rows_clock.append(cf(epoch_decision_time))
                rows_m1.append(case_m1v.tolist())
                rows_tick.append(case_tick_row.tolist())
                y_l.append(1)
                g_l.append(stratum)

                ctrl_added = 0
                for ctrl in ctrl_list:
                    ctrl_exact = ctrl["decision_time_utc"]
                    ctrl_dt = pd.Timestamp(ctrl_exact)
                    ctrl_bar = pd.Timestamp(ctrl["bar_open_utc"])

                    if ctrl_bar in panel_lut.index:
                        ctrl_m1v = panel_lut.loc[ctrl_bar, lag_cols].values.astype(float)
                    else:
                        ctrl_m1v = np.full(len(lag_cols), np.nan)
                    if np.isnan(ctrl_m1v).any():
                        continue

                    ctd_c = tick_data["controls"].get(ctrl_exact, {})
                    if ctd_c.get("target_ms") is None:
                        continue
                    ctf_c = ctd_c.get("features", {})
                    rescaled_ctf_c = rescale_tick_features_for_baselines(ctf_c, fold_baselines)
                    ctrl_tick_row = _feature_vector(rescaled_ctf_c, TICK_FEATURES)
                    if ctrl_tick_row is None:
                        continue

                    rows_clock.append(cf(ctrl_dt))
                    rows_m1.append(ctrl_m1v.tolist())
                    rows_tick.append(ctrl_tick_row.tolist())
                    y_l.append(0)
                    g_l.append(stratum)
                    ctrl_added += 1

                if ctrl_added < 5:
                    for _ in range(ctrl_added + 1):
                        rows_clock.pop()
                        rows_m1.pop()
                        rows_tick.pop()
                        y_l.pop()
                        g_l.pop()
                    continue

                stratum += 1

            X_clk_arr = np.array(rows_clock, dtype=np.float64)
            X_m1_arr  = np.array(rows_m1,    dtype=np.float64)
            X_t_arr   = np.array(rows_tick,  dtype=np.float64)
            y_arr = np.array(y_l, dtype=int)
            g_arr = np.array(g_l, dtype=int)
            return X_clk_arr, X_m1_arr, X_t_arr, y_arr, g_arr

        X_c_tr, X_m_tr, X_t_tr, y_tr, g_tr = build_matrices(tr_epoch_ids)
        X_c_te, X_m_te, X_t_te, y_te, g_te = build_matrices(te_epoch_ids)

        if len(np.unique(g_tr)) < 5 or len(np.unique(g_te)) < 2:
            print(f"    Fold {fold_k}: insufficient data, skipping")
            continue

        # M3 matrices (clock + tick)
        X_m3_tr = np.hstack([X_c_tr, X_t_tr])
        X_m3_te = np.hstack([X_c_te, X_t_te])
        X_m3_tr_std, mu_m3_tr, sd_m3_tr = standardize(X_m3_tr)
        X_m3_te_std, _, _ = standardize(X_m3_te, mu_m3_tr, sd_m3_tr)

        # M4 matrices (clock + m1 + tick)
        X_m4_tr = np.hstack([X_c_tr, X_m_tr, X_t_tr])
        X_m4_te = np.hstack([X_c_te, X_m_te, X_t_te])
        X_m4_tr_std, mu_m4_tr, sd_m4_tr = standardize(X_m4_tr)
        X_m4_te_std, _, _ = standardize(X_m4_te, mu_m4_tr, sd_m4_tr)

        # Assemble test groups for M3 and M4
        test_groups_m3 = []
        test_groups_m4 = []
        for gg in np.unique(g_te):
            mask = g_te == gg
            cm_g = y_te[mask] == 1
            if cm_g.sum() == 0:
                continue
            test_groups_m3.append((X_m3_te_std[mask], cm_g))
            test_groups_m4.append((X_m4_te_std[mask], cm_g))

        null_ll_te = sum(float(m.sum()) * (-np.log(len(xg))) for xg, m in test_groups_m3)
        null_ll_per_case = null_ll_te / max(len(test_groups_m3), 1)

        # Grid search over candidate lambdas for M3 and M4
        fnames_m3 = CLOCK_FEATURES + TICK_FEATURES
        fnames_m4 = CLOCK_FEATURES + lag_cols + TICK_FEATURES

        for lam in candidate_lambdas:
            # Fit M3
            r_m3 = fit_conditional_logit(X_m3_tr_std, y_tr, g_tr, lam=lam, feature_names=fnames_m3)
            neg_ll_m3, _ = _conditional_log_lik_and_grad(r_m3.beta, test_groups_m3, lam=0.0)
            oos_ll_m3 = -neg_ll_m3 / max(len(test_groups_m3), 1)

            fold_results_m3.append({
                "fold": fold_k,
                "lam": float(lam),
                "n_train_cases": int(y_tr.sum()),
                "n_test_cases": int(y_te.sum()),
                "train_ll": float(r_m3.log_lik),
                "train_pseudo_r2": float(r_m3.pseudo_r2),
                "test_ll_per_case": float(oos_ll_m3),
                "null_ll_per_case": float(null_ll_per_case),
                "improvement": float(oos_ll_m3 - null_ll_per_case),
            })

            # Fit M4
            r_m4 = fit_conditional_logit(X_m4_tr_std, y_tr, g_tr, lam=lam, feature_names=fnames_m4)
            neg_ll_m4, _ = _conditional_log_lik_and_grad(r_m4.beta, test_groups_m4, lam=0.0)
            oos_ll_m4 = -neg_ll_m4 / max(len(test_groups_m4), 1)

            fold_results_m4.append({
                "fold": fold_k,
                "lam": float(lam),
                "n_train_cases": int(y_tr.sum()),
                "n_test_cases": int(y_te.sum()),
                "train_ll": float(r_m4.log_lik),
                "train_pseudo_r2": float(r_m4.pseudo_r2),
                "test_ll_per_case": float(oos_ll_m4),
                "null_ll_per_case": float(null_ll_per_case),
                "improvement": float(oos_ll_m4 - null_ll_per_case),
            })

    # Summary table across candidate lambdas
    summary_m3 = {}
    for lam in candidate_lambdas:
        items = [f for f in fold_results_m3 if abs(f["lam"] - lam) < 1e-9]
        if items:
            mean_oos = float(np.mean([x["test_ll_per_case"] for x in items]))
            mean_null = float(np.mean([x["null_ll_per_case"] for x in items]))
            summary_m3[str(lam)] = {
                "lambda": float(lam),
                "mean_test_ll_per_case": mean_oos,
                "mean_null_ll_per_case": mean_null,
                "mean_improvement": mean_oos - mean_null,
            }

    summary_m4 = {}
    for lam in candidate_lambdas:
        items = [f for f in fold_results_m4 if abs(f["lam"] - lam) < 1e-9]
        if items:
            mean_oos = float(np.mean([x["test_ll_per_case"] for x in items]))
            mean_null = float(np.mean([x["null_ll_per_case"] for x in items]))
            summary_m4[str(lam)] = {
                "lambda": float(lam),
                "mean_test_ll_per_case": mean_oos,
                "mean_null_ll_per_case": mean_null,
                "mean_improvement": mean_oos - mean_null,
            }

    # Best lambda for M3 and M4
    best_m3_lam = max(summary_m3.keys(), key=lambda k: summary_m3[k]["mean_test_ll_per_case"])
    best_m4_lam = max(summary_m4.keys(), key=lambda k: summary_m4[k]["mean_test_ll_per_case"])

    best_m3_val = summary_m3[best_m3_lam]["mean_test_ll_per_case"]
    best_m4_val = summary_m4[best_m4_lam]["mean_test_ll_per_case"]

    print("\n    === Chronological Walk-Forward Multi-Lambda Summary ===")
    print("    [M3 - Clock + Tick]")
    for lam_str, s in summary_m3.items():
        mark = " (BEST)" if lam_str == best_m3_lam else ""
        print(f"      lam={float(lam_str):<8.4g}  OOS LL/case={s['mean_test_ll_per_case']:.4f}  "
              f"Null={s['mean_null_ll_per_case']:.4f}  Impr={s['mean_improvement']:+.4f}{mark}")

    print("    [M4 - Clock + Lagged M1 + Tick]")
    for lam_str, s in summary_m4.items():
        mark = " (BEST)" if lam_str == best_m4_lam else ""
        print(f"      lam={float(lam_str):<8.4g}  OOS LL/case={s['mean_test_ll_per_case']:.4f}  "
              f"Null={s['mean_null_ll_per_case']:.4f}  Impr={s['mean_improvement']:+.4f}{mark}")

    # Select overall model and lambda
    if best_m4_val > best_m3_val:
        selected_model = "M4"
        selected_lam = float(best_m4_lam)
        selected_oos_ll = best_m4_val
    else:
        selected_model = "M3"
        selected_lam = float(best_m3_lam)
        selected_oos_ll = best_m3_val

    print(f"\n    >>> Chronological Model Selection: {selected_model} (lambda={selected_lam}) with OOS LL/case={selected_oos_ll:.4f}")

    return {
        "m3": {
            "fold_results": fold_results_m3,
            "lambda_summary": summary_m3,
            "best_lambda": float(best_m3_lam),
            "best_oos_ll_per_case": float(best_m3_val),
        },
        "m4": {
            "fold_results": fold_results_m4,
            "lambda_summary": summary_m4,
            "best_lambda": float(best_m4_lam),
            "best_oos_ll_per_case": float(best_m4_val),
        },
        "m3_best_mean_oos_ll": float(best_m3_val),
        "m4_best_mean_oos_ll": float(best_m4_val),
        "m3_best_lambda": float(best_m3_lam),
        "m4_best_lambda": float(best_m4_lam),
        "selected_model": selected_model,
        "selected_lambda": selected_lam,
        "selected_oos_ll_per_case": float(selected_oos_ll),
        "mean_test_ll": float(selected_oos_ll),
        "candidate_lambdas": candidate_lambdas,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 11. FROZEN LOCKBOX EVALUATION
# ─────────────────────────────────────────────────────────────────────────────
def evaluate_lockbox(
    lock: pd.DataFrame,
    all_records: pd.DataFrame,
    tick_data_lock: dict,
    lock_risk_sets: dict,
    baselines: dict,
    lagged_panel: pd.DataFrame,
    freeze: dict,
) -> dict:
    """
    Single final evaluation on the 102-epoch frozen lockbox.

    Uses the frozen model beta, standardisation parameters, feature names,
    and risk-set design from ``freeze`` (phase10_11_model_freeze.json).
    Controls must have their tick data already extracted in tick_data_lock
    before this function is called — no lockbox tick extraction happens here.

    Parameters
    ----------
    lock            : 102-epoch lockbox epoch table
    all_records     : full 423-record table (used for freeze-check display only)
    tick_data_lock  : {"cases": {epoch_key: {...}}, "controls": {exact_ts: {...}}}
    lock_risk_sets  : risk sets for lockbox epochs, same format as discovery
    baselines       : hour baselines fitted on discovery only
    lagged_panel    : shifted M1 panel (row at B holds B-1 features)
    freeze          : dict from phase10_11_model_freeze.json
    """
    print("\n[11] FROZEN LOCKBOX EVALUATION (single evaluation, no tuning after this)")

    # ── Unpack frozen model ──
    best_model_id = freeze["selected_model_id"]
    best_beta = np.array(freeze["beta"])
    best_mu   = np.array(freeze["feature_mean"])
    best_sd   = np.array(freeze["feature_std"])
    best_fnames = freeze["feature_names"]
    print(f"    Frozen model: {best_model_id}  features: {len(best_fnames)}  beta_norm: {np.linalg.norm(best_beta):.4f}")

    lag_cols = [f"{c}_lag1" for c in M1_FEATURES if f"{c}_lag1" in lagged_panel.columns]
    panel_lut = lagged_panel.set_index("dt")[lag_cols]

    from model_lib10b import _conditional_log_lik_and_grad

    def make_row(clock_dt: pd.Timestamp, bar_dt: pd.Timestamp,
                 tick_entry: dict) -> np.ndarray | None:
        """Return a standardised feature row, or None on missing data."""
        tick_feats = tick_entry.get("features", {})
        tick_row = _feature_vector(tick_feats, TICK_FEATURES)
        if tick_row is None:
            return None

        clock_row = np.array([
            float(clock_dt.hour), float(clock_dt.minute),
            float(clock_dt.dayofweek),
            float(clock_dt.dayofweek == 0),
            float(clock_dt.dayofweek == 4),
        ], dtype=np.float64)

        if best_model_id.startswith("M4") or "m1" in best_model_id.lower():
            if bar_dt in panel_lut.index:
                m1_raw = panel_lut.loc[bar_dt, lag_cols].values.astype(float)
            else:
                m1_raw = np.full(len(lag_cols), np.nan)
            if np.isnan(m1_raw).any():
                return None
            raw = np.concatenate([clock_row, m1_raw, tick_row])
        else:
            raw = np.concatenate([clock_row, tick_row])

        if len(raw) != len(best_mu):
            return None

        return (raw - best_mu) / np.where(best_sd < 1e-8, 1.0, best_sd)

    test_groups   = []
    n_excluded    = 0
    coverage_info = []

    for epoch in lock.sort_values("epoch_id").itertuples():
        key = str(int(epoch.epoch_id))
        if key not in lock_risk_sets:
            n_excluded += 1
            continue
        rs = lock_risk_sets[key]
        ctrl_list = rs["broad"]

        case_dt  = pd.Timestamp(rs["case_decision_time_utc"])
        case_bar = pd.Timestamp(rs["decision_epoch_utc"])

        ctd_case = tick_data_lock["cases"].get(key, {})
        case_row = make_row(case_dt, case_bar, ctd_case)
        if case_row is None:
            n_excluded += 1
            continue

        ctrl_rows = []
        for ctrl in ctrl_list:
            ctrl_exact = ctrl["decision_time_utc"]
            ctrl_dt    = pd.Timestamp(ctrl_exact)
            ctrl_bar   = pd.Timestamp(ctrl["bar_open_utc"])
            ctd_c = tick_data_lock["controls"].get(ctrl_exact, {})
            row = make_row(ctrl_dt, ctrl_bar, ctd_c)
            if row is not None:
                ctrl_rows.append(row)

        if len(ctrl_rows) < 5:
            n_excluded += 1
            continue

        X_g = np.vstack([case_row[np.newaxis], np.vstack(ctrl_rows)])
        y_g = np.zeros(len(X_g), dtype=int)
        y_g[0] = 1
        test_groups.append((X_g, y_g == 1))
        coverage_info.append({"epoch_id": int(epoch.epoch_id), "n_controls": len(ctrl_rows)})

    if not test_groups:
        print("    ERROR: No lockbox strata assembled")
        return {}

    neg_ll, _ = _conditional_log_lik_and_grad(best_beta, test_groups, lam=0.0)
    lockbox_ll = -neg_ll

    null_ll = sum(float(m.sum()) * (-np.log(len(xg))) for xg, m in test_groups)
    n_strata     = len(test_groups)
    ll_per_case  = lockbox_ll / n_strata
    null_per_case = null_ll / n_strata

    print(f"    Lockbox epochs evaluated: {n_strata} / {len(lock)}  (excluded: {n_excluded})")
    print(f"    Lockbox LL/case:   {ll_per_case:.4f}")
    print(f"    Null LL/case:      {null_per_case:.4f}")
    print(f"    Improvement:       {ll_per_case - null_per_case:.4f}")

    result = {
        "record_count": N_RECORDS_LOCKBOX,
        "epoch_count":  N_EPOCHS_LOCKBOX,
        "n_strata_evaluated": n_strata,
        "n_excluded": n_excluded,
        "selected_model_id": best_model_id,
        "model_freeze_hash": freeze.get("freeze_hash", ""),
        "lockbox_ll": float(lockbox_ll),
        "null_ll": float(null_ll),
        "ll_per_case": float(ll_per_case),
        "null_per_case": float(null_per_case),
        "oos_improvement": float(ll_per_case - null_per_case),
        "stratum_coverage": coverage_info,
    }

    path = OUTPUT_DIR / "phase10_11_lockbox_results.json"
    with open(path, "w") as fh:
        json.dump(result, fh, indent=2)
    print(f"    Saved lockbox results: {path}")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main(discovery_only: bool = False, skip_permutations: bool = False, n_perm: int = 499):
    t_start = time.time()
    print("=" * 70)
    print("PHASE 10/11 — ENTRY-SELECTION ANALYSIS" + (" [DISCOVERY-ONLY]" if discovery_only else ""))
    print("=" * 70)

    # ── Step 1: Load & split ──
    disc, lock, panel, all_records, all_epochs = load_and_split()

    # ── Step 2: Build lagged panel ──
    print("\n[2] Building lagged M1 panel (shift(1) for causal features)...")
    lagged_panel = build_lagged_panel(panel)
    print(f"    Lagged panel rows: {len(lagged_panel)}")

    # ── Step 3: Build risk sets (discovery only) ──
    # Eligibility boundary: exactly the 320 discovery records.
    # Pre-registered design: the buffer and lockbox must not contribute to
    # discovery busy masks, risk sets, baselines, scalers, or model fitting.
    # The buffer is a chronological separation boundary only; it carries no
    # eligibility role in the discovery phase.
    discovery_records = all_records[
        all_records["record_partition"] == "discovery"
    ].copy()
    risk_sets = build_risk_sets(
        disc,
        discovery_records,
        panel,
        output_path=OUTPUT_DIR / "phase10_11_risk_sets.json",
    )

    # ── Step 4 & 5: Extract tick features and compute hour baselines (streaming) ──
    tick_parquet = OUTPUT_DIR / "phase10_11_tick_features.parquet"
    tick_data, baselines = extract_all_tick_features_streaming(
        disc, risk_sets, output_parquet=tick_parquet
    )

    # Save baselines
    bl_path = OUTPUT_DIR / "phase10_11_hour_baselines.json"
    with open(bl_path, "w") as fh:
        json.dump({str(k): v for k, v in baselines.items()}, fh, indent=2)

    # ── Step 6: Assemble feature matrices (broad + local) ──
    X_clk_b, X_m1_b, X_tick_b, y_b, g_b, n_clk, n_m1, n_tck = assemble_feature_matrix(
        disc, risk_sets, tick_data, baselines, lagged_panel, design="broad"
    )

    X_clk_l, X_m1_l, X_tick_l, y_l, g_l, _, _, _ = assemble_feature_matrix(
        disc, risk_sets, tick_data, baselines, lagged_panel, design="local"
    )

    # Save feature matrix
    feat_path = OUTPUT_DIR / "phase10_11_features.parquet"
    feat_df = pd.DataFrame(
        np.hstack([X_clk_b, X_m1_b, X_tick_b]),
        columns=n_clk + n_m1 + n_tck,
    )
    feat_df["y"]      = y_b
    feat_df["groups"] = g_b
    feat_df.to_parquet(feat_path, index=False)
    print(f"\n    Saved feature matrix: {feat_path}  shape={feat_df.shape}")

    # ── Step 7: Fit model ladder ──
    model_results_broad = fit_model_ladder(X_clk_b, X_m1_b, X_tick_b, y_b, g_b,
                                           n_clk, n_m1, n_tck, "broad")
    model_results_local = fit_model_ladder(X_clk_l, X_m1_l, X_tick_l, y_l, g_l,
                                           n_clk, n_m1, n_tck, "local")

    # ── Step 8: Permutation tests ──
    if not discovery_only and not skip_permutations and n_perm > 0:
        perm_broad = run_permutation_tests(model_results_broad, y_b, g_b, "broad", n_perm=n_perm)
        perm_local = run_permutation_tests(model_results_local, y_l, g_l, "local", n_perm=n_perm)
    else:
        print("\n[8] Permutation tests SKIPPED")
        perm_broad = {}
        perm_local = {}

    # ── Step 9: Planted truth ──
    if not discovery_only:
        planted = run_planted_truth_test(X_clk_b, X_tick_b, y_b, g_b)
    else:
        print("\n[9] Planted truth test SKIPPED (discovery-only mode)")
        planted = {}

    # ── Step 10: Chronological validation ──
    chrono = chronological_validation(disc, risk_sets, tick_data, baselines, lagged_panel)

    # ── Save all results ──
    def _strip(d):
        """Remove non-serializable fitted objects and normalize numpy values."""
        out = {}
        for k, v in d.items():
            if k == "_fitted" or isinstance(v, ConditionalLogitResult):
                continue
            out[k] = v
        return out

    all_model_results = {
        "broad": _strip(model_results_broad),
        "local": _strip(model_results_local),
    }
    mr_path = OUTPUT_DIR / "phase10_11_model_results.json"
    with open(mr_path, "w") as fh:
        json.dump(all_model_results, fh, indent=2)
    print(f"\n    Saved model results: {mr_path}")

    if perm_broad or perm_local:
        perm_all = {"broad": perm_broad, "local": perm_local}
        pr_path  = OUTPUT_DIR / "phase10_11_permutation_results.json"
        with open(pr_path, "w") as fh:
            json.dump(perm_all, fh, indent=2)
        print(f"    Saved permutation results: {pr_path}")
    else:
        perm_all = {}

    if planted:
        pt_path = OUTPUT_DIR / "phase10_11_planted_truth.json"
        with open(pt_path, "w") as fh:
            json.dump(planted, fh, indent=2)
        print(f"    Saved planted-truth results: {pt_path}")

    cv_path = OUTPUT_DIR / "phase10_11_chrono_validation.json"
    with open(cv_path, "w") as fh:
        json.dump(chrono, fh, indent=2)
    print(f"    Saved chronological validation: {cv_path}")

    # ── Step 10b: Model freeze (selection and full-discovery fit) ──
    # Select M3 vs M4 by mean chronological OOS log-likelihood per epoch.
    # Broad design is the selection design; local is sensitivity only.
    # In the case of an exact tie, select the lower-dimensional M3.
    # Fit the selected model once on all 317 discovery epochs using chronological lambda.
    freeze_path = OUTPUT_DIR / "phase10_11_model_freeze.json"
    print("\n[10b] Selecting and freezing discovery model...")

    selected_model_id = chrono.get("selected_model", "M3")
    selected_lambda = float(chrono.get("selected_lambda", 1.0))
    m3_mean_ll = float(chrono.get("m3_best_mean_oos_ll", chrono.get("mean_test_ll", float("nan"))))
    m4_mean_ll = float(chrono.get("m4_best_mean_oos_ll", float("nan")))

    print(f"    Chrono OOS LL/case  — M3: {m3_mean_ll:.4f} (λ={chrono.get('m3_best_lambda')})  M4: {m4_mean_ll:.4f} (λ={chrono.get('m4_best_lambda')})")
    print(f"    Selected model: {selected_model_id} with chronological λ* = {selected_lambda}")

    if selected_model_id == "M4":
        X_sel = np.hstack([X_clk_b, X_m1_b, X_tick_b])
        fnames_sel = n_clk + n_m1 + n_tck
    else:
        X_sel = np.hstack([X_clk_b, X_tick_b])
        fnames_sel = n_clk + n_tck

    X_sel_std, mu_sel, sd_sel = standardize(X_sel)
    r_sel = fit_conditional_logit(X_sel_std, y_b, g_b, lam=selected_lambda, feature_names=fnames_sel)

    import hashlib as _hashlib
    freeze_content = {
        "selected_model_id": selected_model_id,
        "beta": r_sel.beta.tolist(),
        "feature_names": fnames_sel,
        "feature_mean": mu_sel.tolist(),
        "feature_std": sd_sel.tolist(),
        "lam": float(selected_lambda),
        "n_discovery_epochs": N_EPOCHS_DISCOVERY,
        "log_lik": float(r_sel.log_lik),
        "null_log_lik": float(r_sel.null_log_lik),
        "pseudo_r2": float(r_sel.pseudo_r2),
        "m3_chrono_oos_ll": float(m3_mean_ll),
        "m4_chrono_oos_ll": float(m4_mean_ll),
        "m3_best_lambda": float(chrono.get("m3_best_lambda", 1.0)),
        "m4_best_lambda": float(chrono.get("m4_best_lambda", 1.0)),
        "selection_rule": "M4 if m4_oos > m3_oos else M3 (M3 wins ties)",
    }
    freeze_str = json.dumps(freeze_content, sort_keys=True)
    freeze_hash = _hashlib.sha256(freeze_str.encode()).hexdigest()
    freeze_content["freeze_hash"] = freeze_hash
    with open(freeze_path, "w") as fh:
        json.dump(freeze_content, fh, indent=2)
    print(f"    Model freeze written: {freeze_path}")
    print(f"    Freeze hash: {freeze_hash}")
    freeze = freeze_content

    if discovery_only:
        print("\n[11] Lockbox evaluation SKIPPED (discovery-only mode)")
        elapsed = time.time() - t_start
        print("\n" + "=" * 70)
        print("PHASE 10/11 DISCOVERY VALIDATION & FREEZE COMPLETE")
        print(f"  Elapsed: {elapsed/60:.1f} min")
        print("=" * 70)

        print("\n  MODEL LADDER (Broad Design):")
        print(f"  {'Model':<8}  {'LL':>10}  {'NullLL':>10}  {'PseudoR2':>10}  {'λ':>8}")
        for m in ["M0", "M1", "M2", "M3", "M4"]:
            mr = model_results_broad.get(m, {})
            print(f"  {m:<8}  {mr.get('log_lik', float('nan')):>10.4f}  "
                  f"{mr.get('null_log_lik', float('nan')):>10.4f}  "
                  f"{mr.get('pseudo_r2', float('nan')):>10.4f}  "
                  f"{mr.get('lam', float('nan')):>8.4f}")

        return {
            "model_results": all_model_results,
            "chrono_validation": chrono,
            "freeze": freeze,
        }

    # ── Step 11: Lockbox (FINAL, ONCE) ──
    # freeze is guaranteed to be populated by Step 10b (either newly written
    # or loaded from an existing file).  Use it directly without re-reading.
    # Lockbox uses ALL records for eligibility (not discovery-only) because a
    # lockbox control must be truly flat — any open position from discovery or
    # lockbox counts as busy.
    print("\n[11] Building lockbox risk sets (frozen rules, full-record eligibility)...")
    lock_risk_sets = build_risk_sets(
        lock,
        all_records,      # full 423-record eligibility boundary
        panel,
        output_path=OUTPUT_DIR / "phase10_11_lockbox_risk_sets.json",
    )

    print("\n    Extracting tick features for lockbox cases and controls (streaming)...")
    lock_tick_parquet = OUTPUT_DIR / "phase10_11_lockbox_tick_features.parquet"
    tick_data_lock, _ = extract_all_tick_features_streaming(
        lock, lock_risk_sets, baselines=baselines, output_parquet=lock_tick_parquet
    )

    lockbox_res = evaluate_lockbox(
        lock=lock,
        all_records=all_records,
        tick_data_lock=tick_data_lock,
        lock_risk_sets=lock_risk_sets,
        baselines=baselines,
        lagged_panel=lagged_panel,
        freeze=freeze,
    )

    # ── Final report ──
    elapsed = time.time() - t_start
    print("\n" + "=" * 70)
    print("PHASE 10/11 COMPLETE")
    print(f"  Elapsed: {elapsed/60:.1f} min")
    print("=" * 70)

    # Print model comparison table
    print("\n  MODEL LADDER (Broad Design):")
    print(f"  {'Model':<8}  {'LL':>10}  {'NullLL':>10}  {'PseudoR2':>10}  {'λ':>8}")
    for m in ["M0", "M1", "M2", "M3", "M4"]:
        mr = model_results_broad.get(m, {})
        print(f"  {m:<8}  {mr.get('log_lik', float('nan')):>10.4f}  "
              f"{mr.get('null_log_lik', float('nan')):>10.4f}  "
              f"{mr.get('pseudo_r2', float('nan')):>10.4f}  "
              f"{mr.get('lam', float('nan')):>8.4f}")

    if perm_broad:
        print("\n  PERMUTATION P-VALUES (Broad Design):")
        for key, ptest in perm_broad.items():
            print(f"  {key}: p={ptest.get('p_value', float('nan')):.4f}")

    print("\n  PLANTED-TRUTH RECOVERY:", planted.get("top2_recovered", False))
    print(f"  LOCKBOX OOS IMPROVEMENT: {lockbox_res.get('oos_improvement', float('nan')):.4f}")

    return {
        "model_results": all_model_results,
        "permutation": perm_all,
        "planted_truth": planted,
        "chrono_validation": chrono,
        "lockbox": lockbox_res,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Phase 10/11 Forensic Entry-Selection")
    parser.add_argument("--discovery-only", action="store_true", help="Run only discovery validation and freeze (skip permutations and lockbox)")
    parser.add_argument("--skip-permutations", action="store_true", help="Skip permutation tests entirely")
    parser.add_argument("--n-perm", type=int, default=499, help="Number of permutations if run (default 499)")
    args = parser.parse_args()
    main(discovery_only=args.discovery_only, skip_permutations=args.skip_permutations, n_perm=args.n_perm)
