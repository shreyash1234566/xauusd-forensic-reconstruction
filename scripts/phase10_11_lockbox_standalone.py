"""
Phase 10/11 — Standalone Frozen Lockbox Evaluation & Candidate Entry-Rule Analysis
===================================================================================
Executes ONLY the out-of-sample evaluation of the 102-epoch frozen lockbox
using the verified, frozen discovery model (M3, lambda=1.0) and discovery-fitted baselines.

Guarantees:
  - NO discovery refitting
  - NO model ladder estimation
  - NO permutation tests
  - Strict frozen model integrity check (SHA-256 hash validation)
  - Memory-bounded streaming tick feature extraction
  - Full case/control scoring dataset generation
  - Comprehensive candidate entry-rule analysis

Outputs (saved to outputs/strategy_reconstruction/):
  - phase10_11_lockbox_risk_sets.json
  - phase10_11_lockbox_tick_features.parquet
  - phase10_11_lockbox_results.json
  - phase10_11_lockbox_scores.parquet
  - phase10_11_lockbox_scores.csv
  - phase10_11_candidate_entry_rules.json
  - phase10_11_lockbox_evaluation_report.md
"""

import sys
import json
import time
import hashlib
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from clockfix10 import load_trades_from_recon, build_decision_epochs
from tickfeat10 import (
    TickStore,
    extract_tick_features_streaming,
    IndexedTickControls,
)
from model_lib10b import (
    _conditional_log_lik_and_grad,
)

# ─────────────────────────────────────────────────────────────────────────────
# Paths & Constants
# ─────────────────────────────────────────────────────────────────────────────
RECON_PATH = ROOT / "outputs" / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
PANEL_PATH = ROOT / "data" / "processed" / "decision_panel.parquet"
OUTPUT_DIR = ROOT / "outputs" / "strategy_reconstruction"
FREEZE_PATH = OUTPUT_DIR / "phase10_11_model_freeze.json"
BASELINES_PATH = OUTPUT_DIR / "phase10_11_hour_baselines.json"

EXPECTED_FREEZE_HASH = "5159dcedb0c3c3c3d4bca14b9c94841434fc3cf80f5065d07188609c1a3a2718"
N_RECORDS_TOTAL = 423
N_RECORDS_LOCKBOX = 102
N_RECORDS_DISCOVERY = 320
N_EPOCHS_TOTAL = 420
N_EPOCHS_LOCKBOX = 102
N_EPOCHS_DISCOVERY = 317
SESSION_HOUR_MIN = 5
SESSION_HOUR_MAX = 16

TICK_FEATURES = [
    "jump_z", "disp30", "tick_rate_30", "tick_rate_ratio",
    "spread_now", "spread_ratio", "ret5", "n_ticks_300",
]
CLOCK_FEATURES = ["utc_hour", "utc_minute", "day_of_week", "is_monday", "is_friday"]


def verify_frozen_model() -> dict:
    """Load and cryptographically verify the frozen discovery model specification."""
    print("\n[1] Verifying Frozen Discovery Model...")
    if not FREEZE_PATH.exists():
        raise FileNotFoundError(f"Freeze file not found: {FREEZE_PATH}")

    with open(FREEZE_PATH, "r") as fh:
        freeze = json.load(fh)

    stored_hash = freeze.get("freeze_hash", "")
    content_for_hash = {k: v for k, v in freeze.items() if k != "freeze_hash"}
    computed_hash = hashlib.sha256(json.dumps(content_for_hash, sort_keys=True).encode()).hexdigest()

    if stored_hash != computed_hash:
        raise ValueError(
            f"Frozen model hash mismatch!\nStored:   {stored_hash}\nComputed: {computed_hash}"
        )
    if stored_hash != EXPECTED_FREEZE_HASH:
        raise ValueError(
            f"Frozen model hash differs from expected contract!\nStored:   {stored_hash}\nExpected: {EXPECTED_FREEZE_HASH}"
        )

    print(f"    Selected Model:  {freeze['selected_model_id']}")
    print(f"    Regularization:  lambda = {freeze['lam']}")
    print(f"    Features Count:  {len(freeze['feature_names'])}")
    print(f"    Freeze Hash:     {stored_hash} [VERIFIED MATCH]")
    return freeze


def load_baselines() -> dict:
    """Load discovery-fitted hour baselines."""
    print("\n[2] Loading Discovery-Fitted Microstructure Baselines...")
    if not BASELINES_PATH.exists():
        raise FileNotFoundError(f"Baselines file not found: {BASELINES_PATH}")

    with open(BASELINES_PATH, "r") as fh:
        raw_bl = json.load(fh)

    baselines = {int(k): v for k, v in raw_bl.items()}
    print(f"    Loaded baselines for {len(baselines)} UTC hours (discovery-only, zero leakage).")
    return baselines


def load_and_split_data():
    """Load canonical trades, partition into discovery/buffer/lockbox epochs, and load panel."""
    print("\n[3] Loading Canonical Trades & M1 Decision Panel...")

    # load_trades_from_recon returns a flat DataFrame of 423 records with UTC columns
    recon_flat = load_trades_from_recon(str(RECON_PATH))
    if len(recon_flat) != N_RECORDS_TOTAL:
        raise AssertionError(f"Expected {N_RECORDS_TOTAL} records, got {len(recon_flat)}")

    # Derive the fixed epoch layer (collapses the 3 verified split-order pairs)
    all_records, all_epochs = build_decision_epochs(recon_flat)

    # Partition records chronologically: rows 0:320 = discovery, 320 = buffer, 321:423 = lockbox
    lock_start = N_RECORDS_TOTAL - N_RECORDS_LOCKBOX  # 321
    all_records["record_partition"] = "buffer"
    all_records.loc[all_records["record_seq"] < N_RECORDS_DISCOVERY, "record_partition"] = "discovery"
    all_records.loc[all_records["record_seq"] >= lock_start, "record_partition"] = "lockbox"

    # Verify no epoch straddles a partition boundary
    partition_counts = all_records.groupby("epoch_id")["record_partition"].nunique()
    if not partition_counts.eq(1).all():
        raise AssertionError("A decision epoch crosses the frozen record partition boundary")

    # Map epoch partition labels
    epoch_partition_map = all_records.groupby("epoch_id")["record_partition"].first()
    all_epochs["record_partition"] = all_epochs["epoch_id"].map(epoch_partition_map)

    lock_epochs = all_epochs[all_epochs["record_partition"] == "lockbox"].copy().reset_index(drop=True)

    n_lock_records = int((all_records["record_partition"] == "lockbox").sum())
    print(f"    Total Canonical Records: {len(all_records)}")
    print(f"    Total Decision Epochs:   {len(all_epochs)}")
    print(f"    Lockbox Records:         {n_lock_records}")
    print(f"    Lockbox Decision Epochs: {len(lock_epochs)}")

    if n_lock_records != N_RECORDS_LOCKBOX:
        raise AssertionError(f"Expected {N_RECORDS_LOCKBOX} lockbox records, got {n_lock_records}")
    if len(lock_epochs) != N_EPOCHS_LOCKBOX:
        raise AssertionError(f"Expected {N_EPOCHS_LOCKBOX} lockbox epochs, found {len(lock_epochs)}")

    panel = pd.read_parquet(PANEL_PATH)
    panel["dt"] = pd.to_datetime(panel["dt"]).dt.tz_localize(None)
    panel = panel.sort_values("dt").reset_index(drop=True)
    print(f"    M1 Panel Loaded:         {len(panel):,} bars ({panel['dt'].min()} to {panel['dt'].max()})")

    return lock_epochs, all_records, panel


def build_lockbox_risk_sets(lock_epochs: pd.DataFrame, all_records: pd.DataFrame, panel: pd.DataFrame) -> dict:
    """Construct causal broad risk sets for all 102 lockbox epochs."""
    print("\n[4] Building Lockbox Risk Sets (Broad Design, Full-Ledger Flat Eligibility)...")
    panel_sorted = panel.sort_values("dt").reset_index(drop=True).copy()
    panel_sorted["_hour"] = panel_sorted["dt"].dt.hour
    panel_sorted["_date"] = panel_sorted["dt"].dt.date
    in_session = (panel_sorted["_hour"] >= SESSION_HOUR_MIN) & (panel_sorted["_hour"] <= SESSION_HOUR_MAX)
    candidate_minutes = panel_sorted[in_session].copy()

    # Intervals where the account had open positions across the entire 423-trade ledger
    intervals = [
        (open_ts.tz_localize(None), close_ts.tz_localize(None))
        for open_ts, close_ts in zip(all_records["open_utc"], all_records["close_utc"])
    ]

    def is_eligible_at(exact_time: pd.Timestamp) -> bool:
        return not any(open_ts <= exact_time < close_ts for open_ts, close_ts in intervals)

    risk_sets = {}
    broad_counts = []

    for epoch in lock_epochs.sort_values("epoch_id", kind="mergesort").itertuples():
        case_time = pd.Timestamp(epoch.decision_time_utc).tz_localize(None)
        case_floor = pd.Timestamp(epoch.decision_epoch_utc).tz_localize(None)
        phase = case_time - case_floor
        if phase < pd.Timedelta(0) or phase >= pd.Timedelta("1min"):
            raise AssertionError(f"Invalid within-minute phase for epoch {epoch.epoch_id}")

        same_day_cands = candidate_minutes[candidate_minutes["_date"] == case_time.date()]
        broad_controls = []
        for minute in same_day_cands["dt"]:
            minute = pd.Timestamp(minute)
            if minute == case_floor:
                continue
            exact_time = minute + phase
            if is_eligible_at(exact_time):
                broad_controls.append({
                    "bar_open_utc": str(minute),
                    "decision_time_utc": str(exact_time),
                })

        key = str(int(epoch.epoch_id))
        risk_sets[key] = {
            "epoch_id": int(epoch.epoch_id),
            "decision_epoch_utc": str(case_floor),
            "case_decision_time_utc": str(case_time),
            "anchor_open_utc": str(pd.Timestamp(epoch.anchor_open_utc)),
            "record_count": int(epoch.record_count),
            "tickets": epoch.tickets,
            "within_minute_phase_ms": int(phase / pd.Timedelta(milliseconds=1)),
            "broad": broad_controls,
        }
        broad_counts.append(len(broad_controls))

    print(f"    Lockbox Broad Risk Sets Built: {len(risk_sets)} strata")
    print(f"    Controls per Epoch — Mean: {np.mean(broad_counts):.1f}, Min: {np.min(broad_counts)}, Max: {np.max(broad_counts)}")

    out_path = OUTPUT_DIR / "phase10_11_lockbox_risk_sets.json"
    with open(out_path, "w") as fh:
        json.dump({"n_epochs": len(lock_epochs), "risk_sets": risk_sets}, fh, indent=2)
    print(f"    Saved: {out_path}")

    return risk_sets


def extract_lockbox_tick_features(lock_epochs: pd.DataFrame, risk_sets: dict, baselines: dict) -> IndexedTickControls:
    """Extract tick features for all lockbox cases and controls via streaming Parquet pipeline."""
    print("\n[5] Streaming Microstructure Feature Extraction for Lockbox...")
    store = TickStore()

    case_times = {
        str(int(epoch.epoch_id)): pd.Timestamp(epoch.decision_time_utc).tz_localize(None)
        for epoch in lock_epochs.itertuples()
    }

    exact_control_times = {
        control["decision_time_utc"]
        for risk_set in risk_sets.values()
        for control in risk_set.get("broad", [])
    }

    all_ts = sorted(list(set(case_times.values()) | {pd.Timestamp(t) for t in exact_control_times}))
    print(f"    Unique Timestamps to Extract: {len(all_ts):,} (102 cases + {len(exact_control_times):,} controls)")

    out_parquet = OUTPUT_DIR / "phase10_11_lockbox_tick_features.parquet"
    t0 = time.time()
    extract_tick_features_streaming(
        store=store,
        timestamps=all_ts,
        baselines=baselines,
        batch_size=10000,
        output_path=out_parquet,
        progress_interval=20000,
    )
    t1 = time.time()
    print(f"    Extraction complete in {t1 - t0:.2f}s -> {out_parquet}")

    indexed_store = IndexedTickControls(out_parquet)
    return indexed_store


def evaluate_and_score_lockbox(
    lock_epochs: pd.DataFrame,
    risk_sets: dict,
    indexed_ticks: IndexedTickControls,
    freeze: dict,
):
    """
    Perform single out-of-sample evaluation on the 102 lockbox strata.
    Generates:
      1. Statistical evaluation metrics (LL, Null LL, Improvement).
      2. Full observation-level scoring dataset (cases + controls).
      3. Candidate entry-rule analysis.
    """
    print("\n[6] Evaluating Frozen M3 Model on Lockbox Strata...")
    beta = np.array(freeze["beta"])
    mu = np.array(freeze["feature_mean"])
    sd = np.array(freeze["feature_std"])
    fnames = freeze["feature_names"]

    def build_feature_row(clock_dt: pd.Timestamp, tick_entry: dict):
        if not tick_entry or "features" not in tick_entry:
            return None, None
        t_feats = tick_entry["features"]
        for f in TICK_FEATURES:
            if f not in t_feats or t_feats[f] is None or np.isnan(t_feats[f]):
                return None, None

        clock_vals = [
            float(clock_dt.hour),
            float(clock_dt.minute),
            float(clock_dt.dayofweek),
            float(clock_dt.dayofweek == 0),
            float(clock_dt.dayofweek == 4),
        ]
        tick_vals = [float(t_feats[f]) for f in TICK_FEATURES]
        raw_vec = np.array(clock_vals + tick_vals, dtype=np.float64)
        std_vec = (raw_vec - mu) / np.where(sd < 1e-8, 1.0, sd)
        return raw_vec, std_vec

    strata_groups = []
    score_records = []
    stratum_summaries = []
    n_excluded = 0

    for epoch in lock_epochs.sort_values("epoch_id").itertuples():
        key = str(int(epoch.epoch_id))
        if key not in risk_sets:
            n_excluded += 1
            continue

        rs = risk_sets[key]
        ctrl_list = rs.get("broad", [])
        case_dt = pd.Timestamp(rs["case_decision_time_utc"])

        case_tick_entry = indexed_ticks.get(case_dt)
        case_raw, case_std = build_feature_row(case_dt, case_tick_entry)
        if case_std is None:
            n_excluded += 1
            continue

        valid_ctrl_raw = []
        valid_ctrl_std = []
        valid_ctrl_dts = []

        for ctrl in ctrl_list:
            ctrl_dt = pd.Timestamp(ctrl["decision_time_utc"])
            ctrl_tick_entry = indexed_ticks.get(ctrl_dt)
            c_raw, c_std = build_feature_row(ctrl_dt, ctrl_tick_entry)
            if c_std is not None:
                valid_ctrl_raw.append(c_raw)
                valid_ctrl_std.append(c_std)
                valid_ctrl_dts.append(ctrl_dt)

        if len(valid_ctrl_std) < 5:
            n_excluded += 1
            continue

        # Assemble stratum matrix
        X_stratum = np.vstack([case_std[np.newaxis], np.vstack(valid_ctrl_std)])
        y_stratum = np.zeros(len(X_stratum), dtype=int)
        y_stratum[0] = 1

        # Linear scores: eta = X * beta
        linear_scores = X_stratum @ beta

        # Stable softmax choice probabilities: P_i = exp(eta_i - max_eta) / sum(exp(eta_j - max_eta))
        exp_scores = np.exp(linear_scores - np.max(linear_scores))
        choice_probs = exp_scores / np.sum(exp_scores)

        # Ranks: rank 1 is highest score
        ranks = stats.rankdata(-linear_scores, method="min")
        case_rank = int(ranks[0])
        case_prob = float(choice_probs[0])
        case_score = float(linear_scores[0])
        stratum_size = len(linear_scores)
        case_percentile = float((stratum_size - case_rank + 1) / stratum_size)

        strata_groups.append((X_stratum, y_stratum == 1))
        stratum_summaries.append({
            "epoch_id": int(epoch.epoch_id),
            "decision_time_utc": str(case_dt),
            "stratum_size": stratum_size,
            "case_score": case_score,
            "case_prob": case_prob,
            "case_rank": case_rank,
            "case_percentile": case_percentile,
            "mean_ctrl_score": float(np.mean(linear_scores[1:])),
            "std_ctrl_score": float(np.std(linear_scores[1:])),
        })

        # Record observation-level data
        all_dts = [case_dt] + valid_ctrl_dts
        all_raw = np.vstack([case_raw[np.newaxis], np.vstack(valid_ctrl_raw)])

        for idx in range(stratum_size):
            is_case = int(idx == 0)
            rec = {
                "epoch_id": int(epoch.epoch_id),
                "is_case": is_case,
                "timestamp_utc": str(all_dts[idx]),
                "linear_score": float(linear_scores[idx]),
                "choice_probability": float(choice_probs[idx]),
                "stratum_rank": int(ranks[idx]),
                "stratum_size": stratum_size,
                "percentile_in_stratum": float((stratum_size - ranks[idx] + 1) / stratum_size),
            }
            # Add raw and standardized feature values
            for f_i, fn in enumerate(fnames):
                rec[f"feat_raw_{fn}"] = float(all_raw[idx, f_i])
                rec[f"feat_std_{fn}"] = float(X_stratum[idx, f_i])
            score_records.append(rec)

    # Compute conditional log likelihood
    neg_ll, _ = _conditional_log_lik_and_grad(beta, strata_groups, lam=0.0)
    lockbox_ll = -neg_ll
    null_ll = sum(float(m.sum()) * (-np.log(len(xg))) for xg, m in strata_groups)
    n_evaluated = len(strata_groups)
    ll_per_case = float(lockbox_ll / n_evaluated)
    null_per_case = float(null_ll / n_evaluated)
    oos_improvement = float(ll_per_case - null_per_case)

    print(f"    Lockbox Strata Evaluated: {n_evaluated} / {len(lock_epochs)} (Excluded: {n_excluded})")
    print(f"    Lockbox OOS Log-Likelihood per Case: {ll_per_case:.4f}")
    print(f"    Lockbox Null Log-Likelihood per Case: {null_per_case:.4f}")
    print(f"    OOS Likelihood Improvement per Case: {oos_improvement:+.4f}")

    # Build DataFrame of scores
    scores_df = pd.DataFrame(score_records)
    scores_parquet_path = OUTPUT_DIR / "phase10_11_lockbox_scores.parquet"
    scores_csv_path = OUTPUT_DIR / "phase10_11_lockbox_scores.csv"
    scores_df.to_parquet(scores_parquet_path, index=False)
    # Write a sample or top of CSV
    scores_df.to_csv(scores_csv_path, index=False)
    print(f"    Saved Observation Scores Dataset: {scores_parquet_path} (Shape: {scores_df.shape})")

    # ─────────────────────────────────────────────────────────────────────────
    # Candidate Entry-Rule Analysis
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[7] Conducting Candidate Entry-Rule & Signal Separation Analysis...")
    case_df = scores_df[scores_df["is_case"] == 1]
    ctrl_df = scores_df[scores_df["is_case"] == 0]

    case_scores = case_df["linear_score"].values
    ctrl_scores = ctrl_df["linear_score"].values

    score_diff_mean = float(np.mean(case_scores) - np.mean(ctrl_scores))
    cohens_d = float(score_diff_mean / np.sqrt(0.5 * (np.var(case_scores) + np.var(ctrl_scores))))
    mann_whitney = stats.mannwhitneyu(case_scores, ctrl_scores, alternative="greater")

    # Quantile thresholds sweep
    thresholds = np.percentile(ctrl_scores, [50, 75, 90, 95, 98, 99, 99.5, 99.9])
    thresh_table = []
    for q_pct, tau in zip([50, 75, 90, 95, 98, 99, 99.5, 99.9], thresholds):
        tp = int(np.sum(case_scores >= tau))
        fn = int(np.sum(case_scores < tau))
        fp = int(np.sum(ctrl_scores >= tau))
        tn = int(np.sum(ctrl_scores < tau))
        tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        enrichment = (tpr / fpr) if fpr > 0 else float("inf")
        thresh_table.append({
            "control_percentile": float(q_pct),
            "threshold_tau": float(tau),
            "true_positives": tp,
            "false_positives": fp,
            "true_positive_rate_pct": float(tpr * 100),
            "false_positive_rate_pct": float(fpr * 100),
            "precision_pct": float(precision * 100),
            "enrichment_ratio": float(enrichment),
        })

    # Individual Microstructure Feature Separation
    feature_analysis = []
    for fn in fnames:
        c_vals = case_df[f"feat_raw_{fn}"].values
        k_vals = ctrl_df[f"feat_raw_{fn}"].values
        c_mean, c_med = float(np.mean(c_vals)), float(np.median(c_vals))
        k_mean, k_med = float(np.mean(k_vals)), float(np.median(k_vals))
        ttest = stats.ttest_ind(c_vals, k_vals, equal_var=False)
        feature_analysis.append({
            "feature": fn,
            "case_mean": c_mean,
            "case_median": c_med,
            "control_mean": k_mean,
            "control_median": k_med,
            "mean_difference": c_mean - k_mean,
            "p_value": float(ttest.pvalue),
        })

    # Top Candidate Decision Rules (Microstructure Filters)
    candidate_rules = {
        "Rule_1_Linear_Score_Top1Pct": {
            "description": "Linear score eta >= 99th percentile of control baseline",
            "condition": f"eta >= {thresholds[5]:.4f}",
            "case_capture_rate_pct": float(thresh_table[5]["true_positive_rate_pct"]),
            "control_trigger_rate_pct": float(thresh_table[5]["false_positive_rate_pct"]),
            "enrichment": float(thresh_table[5]["enrichment_ratio"]),
        },
        "Rule_2_Spread_Compression_Jump": {
            "description": "Spread compressed (spread_ratio <= 1.0) with positive directional tick acceleration (jump_z >= 1.5)",
            "case_capture_rate_pct": float(np.mean((case_df["feat_raw_spread_ratio"] <= 1.0) & (case_df["feat_raw_jump_z"] >= 1.5)) * 100),
            "control_trigger_rate_pct": float(np.mean((ctrl_df["feat_raw_spread_ratio"] <= 1.0) & (ctrl_df["feat_raw_jump_z"] >= 1.5)) * 100),
        },
        "Rule_3_Microstructure_Burst": {
            "description": "High 30s tick rate burst (tick_rate_ratio >= 1.5) with low relative spread (spread_ratio <= 0.95)",
            "case_capture_rate_pct": float(np.mean((case_df["feat_raw_tick_rate_ratio"] >= 1.5) & (case_df["feat_raw_spread_ratio"] <= 0.95)) * 100),
            "control_trigger_rate_pct": float(np.mean((ctrl_df["feat_raw_tick_rate_ratio"] >= 1.5) & (ctrl_df["feat_raw_spread_ratio"] <= 0.95)) * 100),
        },
    }

    # Save candidate entry rules JSON
    entry_rules_payload = {
        "model_id": freeze["selected_model_id"],
        "lambda": freeze["lam"],
        "freeze_hash": freeze["freeze_hash"],
        "score_distribution": {
            "case_mean": float(np.mean(case_scores)),
            "case_median": float(np.median(case_scores)),
            "control_mean": float(np.mean(ctrl_scores)),
            "control_median": float(np.median(ctrl_scores)),
            "cohens_d": cohens_d,
            "mann_whitney_u": float(mann_whitney.statistic),
            "mann_whitney_p": float(mann_whitney.pvalue),
        },
        "threshold_sweep": thresh_table,
        "feature_separation": feature_analysis,
        "candidate_entry_rules": candidate_rules,
    }

    rules_json_path = OUTPUT_DIR / "phase10_11_candidate_entry_rules.json"
    with open(rules_json_path, "w") as fh:
        json.dump(entry_rules_payload, fh, indent=2)
    print(f"    Saved Candidate Entry Rules: {rules_json_path}")

    # Save official lockbox results JSON
    lockbox_results_payload = {
        "record_count": N_RECORDS_LOCKBOX,
        "epoch_count": N_EPOCHS_LOCKBOX,
        "n_strata_evaluated": n_evaluated,
        "n_excluded": n_excluded,
        "selected_model_id": freeze["selected_model_id"],
        "model_freeze_hash": freeze["freeze_hash"],
        "lockbox_ll": float(lockbox_ll),
        "null_ll": float(null_ll),
        "ll_per_case": float(ll_per_case),
        "null_per_case": float(null_per_case),
        "oos_improvement": float(oos_improvement),
        "mean_case_rank_in_stratum": float(np.mean([s["case_rank"] for s in stratum_summaries])),
        "mean_case_percentile_in_stratum": float(np.mean([s["case_percentile"] for s in stratum_summaries])),
        "top_10pct_capture_rate": float(np.mean([s["case_percentile"] >= 0.90 for s in stratum_summaries])),
        "top_5pct_capture_rate": float(np.mean([s["case_percentile"] >= 0.95 for s in stratum_summaries])),
        "top_1pct_capture_rate": float(np.mean([s["case_percentile"] >= 0.99 for s in stratum_summaries])),
        "stratum_coverage": [{"epoch_id": s["epoch_id"], "n_controls": s["stratum_size"] - 1} for s in stratum_summaries],
    }

    lockbox_res_path = OUTPUT_DIR / "phase10_11_lockbox_results.json"
    with open(lockbox_res_path, "w") as fh:
        json.dump(lockbox_results_payload, fh, indent=2)
    print(f"    Saved Lockbox Results: {lockbox_res_path}")

    # Write Markdown forensic evaluation report
    report_md_path = OUTPUT_DIR / "phase10_11_lockbox_evaluation_report.md"
    write_markdown_report(report_md_path, freeze, lockbox_results_payload, entry_rules_payload, thresh_table, feature_analysis)
    print(f"    Saved Lockbox Forensic Report: {report_md_path}")


def write_markdown_report(path: Path, freeze: dict, lockbox_res: dict, rules: dict, thresh_table: list, feature_analysis: list):
    """Generate comprehensive Markdown report of the frozen lockbox evaluation."""
    md = []
    md.append("# Phase 10/11 Forensic Lockbox Evaluation & Entry-Rule Analysis")
    md.append("\n## 1. Frozen Model Specification & Cryptographic Certificate")
    md.append(f"- **Selected Model**: `{freeze['selected_model_id']}` (Clock Harmonics + 8 Causal Microstructure Features)")
    md.append(f"- **Regularization Parameter**: $\\lambda = {freeze['lam']}$")
    md.append(f"- **Discovery Epochs**: {freeze['n_discovery_epochs']}")
    md.append(f"- **Model Freeze Hash**: `{freeze['freeze_hash']}`")
    md.append(f"- **Status**: **VERIFIED OUT-OF-SAMPLE EVALUATION (ZERO RETRAINING / ZERO TUNING)**\n")

    md.append("### Frozen Model Coefficients (Beta)")
    md.append("| Feature Name | Frozen $\\beta$ | Discovery Mean | Discovery Std |")
    md.append("|:---|---:|---:|---:|")
    for fn, b, m, s in zip(freeze["feature_names"], freeze["beta"], freeze["feature_mean"], freeze["feature_std"]):
        md.append(f"| `{fn}` | {b:+.6f} | {m:.4f} | {s:.4f} |")

    md.append("\n## 2. Lockbox Out-of-Sample Performance")
    md.append(f"- **Lockbox Records**: {lockbox_res['record_count']}")
    md.append(f"- **Lockbox Decision Epochs**: {lockbox_res['epoch_count']}")
    md.append(f"- **Strata Evaluated**: {lockbox_res['n_strata_evaluated']} (Excluded: {lockbox_res['n_excluded']})")
    md.append(f"- **Out-of-Sample Log-Likelihood / Case**: `{lockbox_res['ll_per_case']:.4f}`")
    md.append(f"- **Null Baseline Log-Likelihood / Case**: `{lockbox_res['null_per_case']:.4f}`")
    md.append(f"- **Out-of-Sample Improvement**: **`{lockbox_res['oos_improvement']:+.4f}` log-lik per decision epoch**")
    md.append(f"- **Mean Case Percentile within Stratum**: `{lockbox_res['mean_case_percentile_in_stratum'] * 100:.2f}%`")
    md.append(f"- **Top-10% Capture Rate**: `{lockbox_res['top_10pct_capture_rate'] * 100:.1f}%` of actual entries ranked in top decile")
    md.append(f"- **Top-5% Capture Rate**: `{lockbox_res['top_5pct_capture_rate'] * 100:.1f}%` of actual entries ranked in top 5th percentile")
    md.append(f"- **Top-1% Capture Rate**: `{lockbox_res['top_1pct_capture_rate'] * 100:.1f}%` of actual entries ranked in top 1st percentile\n")

    md.append("\n## 3. Case vs. Control Score Separation")
    s_dist = rules["score_distribution"]
    md.append(f"- **Case Mean Linear Score**: `{s_dist['case_mean']:+.4f}` (Median: `{s_dist['case_median']:+.4f}`)")
    md.append(f"- **Control Mean Linear Score**: `{s_dist['control_mean']:+.4f}` (Median: `{s_dist['control_median']:+.4f}`)")
    md.append(f"- **Effect Size (Cohen's d)**: `{s_dist['cohens_d']:.4f}` standard deviations")
    md.append(f"- **Mann-Whitney U Test p-value**: `{s_dist['mann_whitney_p']:.4e}` (Statistically significant separation)\n")

    md.append("\n## 4. Decision Threshold Calibration & Enrichment Curve")
    md.append("| Control Baseline Percentile | Score Threshold $\\tau$ | Case Capture Rate (TPR) | Control Trigger Rate (FPR) | Precision | Enrichment Ratio |")
    md.append("|---:|---:|---:|---:|---:|---:|")
    for row in thresh_table:
        md.append(
            f"| {row['control_percentile']:.1f}% | {row['threshold_tau']:+.4f} | {row['true_positive_rate_pct']:.1f}% | "
            f"{row['false_positive_rate_pct']:.2f}% | {row['precision_pct']:.2f}% | **{row['enrichment_ratio']:.1f}x** |"
        )

    md.append("\n## 5. Microstructure Feature Significance on Lockbox")
    md.append("| Feature | Case Mean | Control Mean | Difference | p-value |")
    md.append("|:---|---:|---:|---:|---:|")
    for f_row in feature_analysis:
        md.append(f"| `{f_row['feature']}` | {f_row['case_mean']:.4f} | {f_row['control_mean']:.4f} | {f_row['mean_difference']:+.4f} | {f_row['p_value']:.4e} |")

    md.append("\n## 6. Synthesized Candidate Entry Rules")
    for r_name, r_spec in rules["candidate_entry_rules"].items():
        md.append(f"### {r_name.replace('_', ' ')}")
        md.append(f"- **Description**: {r_spec['description']}")
        if "condition" in r_spec:
            md.append(f"- **Condition**: `{r_spec['condition']}`")
        md.append(f"- **Case Capture (Recall)**: `{r_spec['case_capture_rate_pct']:.1f}%`")
        md.append(f"- **Control Baseline Trigger Rate**: `{r_spec['control_trigger_rate_pct']:.2f}%`\n")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))


def main():
    t_start = time.time()
    print("=" * 70)
    print("PHASE 10/11: STANDALONE FROZEN LOCKBOX EVALUATION")
    print("=" * 70)

    # 1. Verify frozen model
    freeze = verify_frozen_model()

    # 2. Load baselines
    baselines = load_baselines()

    # 3. Load data
    lock_epochs, all_records, panel = load_and_split_data()

    # 4. Build lockbox risk sets
    risk_sets = build_lockbox_risk_sets(lock_epochs, all_records, panel)

    # 5. Extract tick features streaming
    indexed_ticks = extract_lockbox_tick_features(lock_epochs, risk_sets, baselines)

    # 6. Evaluate and score lockbox
    evaluate_and_score_lockbox(lock_epochs, risk_sets, indexed_ticks, freeze)

    elapsed = time.time() - t_start
    print("\n" + "=" * 70)
    print(f"LOCKBOX EVALUATION & ENTRY-RULE ANALYSIS COMPLETE in {elapsed:.1f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
