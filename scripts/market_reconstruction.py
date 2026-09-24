"""Exploratory external-market comparison pipeline: phases A–H.

Phases:
B. Reference-feed alignment and entry-state comparison
B. MFE/MAE excursion paths
C. Feature matrix generation (full counterfactual panel)
D. No-trade baseline characterization
E. Candidate rule testing (univariate threshold sweeps)
F. Symbolic rule discovery (decision tree induction)
G. Walk-forward out-of-sample validation
H. Reference-feed diagnostics (not an identified strategy reconstruction)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.metrics import (
    classification_report,
    roc_auc_score,
    precision_recall_curve,
)
from sklearn.preprocessing import LabelEncoder

from reverse_trade.market import (
    load_market_bars,
    add_market_features,
    align_entries,
    calculate_excursions,
    build_counterfactual_decision_panel,
)
from reverse_trade.pipeline import load_trades

ROOT = Path(__file__).resolve().parents[1]
MARKET_PATH = ROOT / "data" / "market" / "normalized" / "xauusd_m1.csv"
TRADES_PATH = ROOT / "data" / "raw" / "trades_raw.tsv"
OUT_DIR = ROOT / "outputs" / "market_reconstruction"
TABLES_DIR = OUT_DIR / "tables"
FIGURES_DIR = OUT_DIR / "figures"

TABLES_DIR.mkdir(parents=True, exist_ok=True)
FIGURES_DIR.mkdir(parents=True, exist_ok=True)


def save_csv(df: pd.DataFrame, name: str) -> None:
    path = TABLES_DIR / f"{name}.csv"
    df.to_csv(path, index=False)
    print(f"  → {path.name} ({len(df)} rows)")


def main() -> None:  # noqa: C901
    print("=" * 68)
    print("MARKET RECONSTRUCTION PIPELINE")
    print("=" * 68)

    # ------------------------------------------------------------------ #
    # A. Load data                                                         #
    # ------------------------------------------------------------------ #
    print("\n[A] Loading market bars and trades …")
    bars = load_market_bars(MARKET_PATH)
    trades, _ = load_trades(TRADES_PATH)

    print(f"  Market bars: {len(bars):,} rows  "
          f"({bars['timestamp'].min().date()} → {bars['timestamp'].max().date()})")
    print(f"  Trades:      {len(trades)} rows  "
          f"({trades['open_time'].min().date()} → {trades['open_time'].max().date()})")

    # ------------------------------------------------------------------ #
    # A. Feature engineering (full bar series)                            #
    # ------------------------------------------------------------------ #
    print("\n[A] Computing multi-scale market features …")
    featured = add_market_features(bars)
    print(f"  Feature columns: {len(featured.columns)}")

    # ------------------------------------------------------------------ #
    # A. Entry-state alignment                                             #
    # ------------------------------------------------------------------ #
    print("\n[A] Aligning trade entries to market bars …")
    aligned = align_entries(trades, featured, tolerance=pd.Timedelta("3min"))
    n_matched = aligned["timestamp"].notna().sum()
    print(f"  Trades matched to bars: {n_matched}/{len(trades)}")
    print(f"  Median lag to bar:      "
          f"{aligned['market_match_lag_seconds'].median():.1f} s")
    save_csv(aligned, "entry_states")

    # Price discrepancy between trade and Dukascopy bid
    if "price_diff_vs_bar_close" in aligned.columns:
        pq = aligned["price_diff_vs_bar_close"].dropna()
        print(f"  Price vs bar-close:     median={pq.median():.3f}, "
              f"std={pq.std():.3f}, max={pq.abs().max():.3f}")

    # ------------------------------------------------------------------ #
    # B. MFE / MAE excursion paths                                        #
    # ------------------------------------------------------------------ #
    print("\n[B] Computing MFE / MAE excursions …")
    excursions = calculate_excursions(trades, bars)
    print(f"  MFE mean:   {excursions['mfe_price'].mean():.3f} "
          f"({excursions['mfe_pips'].mean():.1f} pips)")
    print(f"  MAE mean:   {excursions['mae_price'].mean():.3f} "
          f"({excursions['mae_pips'].mean():.1f} pips)")
    print(f"  Time-to-MFE mean: {excursions['time_to_mfe_minutes'].mean():.1f} min")
    print(f"  Time-to-MAE mean: {excursions['time_to_mae_minutes'].mean():.1f} min")
    save_csv(excursions, "excursions")

    # MFE/MAE by direction
    for side in ["Buy", "Sell"]:
        sub = excursions[excursions["side"] == side]
        print(f"  {side}: MFE={sub['mfe_price'].mean():.3f}  "
              f"MAE={sub['mae_price'].mean():.3f}  "
              f"PnL={sub['final_pnl'].mean():.2f}")

    # Excursion vs outcome
    exc_summary = excursions.groupby("side").agg(
        mean_mfe=("mfe_price", "mean"),
        mean_mae=("mae_price", "mean"),
        mean_mfe_pips=("mfe_pips", "mean"),
        mean_mae_pips=("mae_pips", "mean"),
        mean_ttmfe_min=("time_to_mfe_minutes", "mean"),
        mean_ttmae_min=("time_to_mae_minutes", "mean"),
        mean_pnl=("final_pnl", "mean"),
        n=("ticket", "count"),
    ).reset_index()
    save_csv(exc_summary, "excursions_by_side")

    # ------------------------------------------------------------------ #
    # C. Counterfactual Decision Panel                                     #
    # ------------------------------------------------------------------ #
    print("\n[C] Building counterfactual decision panel …")
    panel = build_counterfactual_decision_panel(featured, trades)
    n_buy = (panel["target_action"] == 1).sum()
    n_sell = (panel["target_action"] == -1).sum()
    n_notrade = (panel["target_action"] == 0).sum()
    total_mins = len(panel)
    print(f"  Panel rows:    {total_mins:,}")
    print(f"  Buy  entries:  {n_buy} ({n_buy/total_mins*100:.4f}%)")
    print(f"  Sell entries:  {n_sell} ({n_sell/total_mins*100:.4f}%)")
    print(f"  No-trade:      {n_notrade:,} ({n_notrade/total_mins*100:.2f}%)")

    # ------------------------------------------------------------------ #
    # D. Feature profile at entries vs. non-entries                       #
    # ------------------------------------------------------------------ #
    print("\n[D] Computing entry-state feature profiles …")

    # Select robust feature columns (drop raw OHLCV and panel columns)
    panel_cols = {"target_action", "matched_ticket", "matched_side",
                  "timestamp", "forward_return_1", "forward_return_5",
                  "forward_return_15"}
    raw_cols = {"open", "high", "low", "close", "volume"}

    feat_cols = [c for c in panel.columns
                 if c not in panel_cols | raw_cols
                 and panel[c].dtype in (np.float64, np.int64, float, int)]

    entry_mask = panel["target_action"] != 0
    entry_panel = panel[entry_mask]
    notrade_panel = panel[~entry_mask]

    # Compare feature means at entries vs non-entries
    comparison_rows = []
    for feat in feat_cols:
        entry_vals = entry_panel[feat].dropna()
        notrade_vals = notrade_panel[feat].dropna()
        if len(entry_vals) < 5 or len(notrade_vals) < 5:
            continue
        comparison_rows.append({
            "feature": feat,
            "entry_mean": entry_vals.mean(),
            "notrade_mean": notrade_vals.mean(),
            "entry_median": entry_vals.median(),
            "notrade_median": notrade_vals.median(),
            "entry_std": entry_vals.std(),
            "notrade_std": notrade_vals.std(),
            "normalized_diff": (entry_vals.mean() - notrade_vals.mean()) / (notrade_vals.std() + 1e-9),
        })

    feat_comparison = pd.DataFrame(comparison_rows)
    feat_comparison = feat_comparison.sort_values("normalized_diff", key=abs, ascending=False)
    save_csv(feat_comparison, "feature_entry_vs_notrade")
    print(f"  Top discriminating features (|normalized_diff|):")
    for _, row in feat_comparison.head(15).iterrows():
        print(f"    {row['feature']:<35} Δ={row['normalized_diff']:+.3f}")

    # ------------------------------------------------------------------ #
    # E. Univariate threshold sweep: candidate entry rules                #
    # ------------------------------------------------------------------ #
    print("\n[E] Univariate threshold sweep for candidate entry rules …")

    # Binary label: 1 = entry bar, 0 = no trade
    panel["any_entry"] = (panel["target_action"] != 0).astype(int)

    sweep_results = []
    for feat in feat_cols[:40]:  # top 40 features to constrain compute time
        vals = panel[feat].dropna()
        if len(vals) < 100:
            continue
        pcts = np.percentile(vals.values, [10, 20, 30, 40, 50, 60, 70, 80, 90])
        feat_series = panel[feat]
        label_series = panel["any_entry"]

        for p, thresh in zip([10, 20, 30, 40, 50, 60, 70, 80, 90], pcts):
            for direction in ["above", "below"]:
                if direction == "above":
                    pred_mask = feat_series >= thresh
                else:
                    pred_mask = feat_series <= thresh
                pred = pred_mask.astype(int)
                valid = feat_series.notna()
                TP = (pred[valid] & label_series[valid]).sum()
                FP = (pred[valid] & ~label_series[valid]).sum()
                FN = (~pred[valid] & label_series[valid]).sum()
                precision = TP / (TP + FP + 1e-9)
                recall = TP / (TP + FN + 1e-9)
                base_rate = label_series[valid].mean()
                lift = precision / (base_rate + 1e-9)
                sweep_results.append({
                    "feature": feat,
                    "percentile": p,
                    "threshold": thresh,
                    "direction": direction,
                    "precision": precision,
                    "recall": recall,
                    "lift": lift,
                    "TP": int(TP),
                    "FP": int(FP),
                    "FN": int(FN),
                })

    sweep_df = pd.DataFrame(sweep_results).sort_values("lift", ascending=False)
    save_csv(sweep_df, "univariate_threshold_sweep")
    print(f"  Top 10 single-threshold rules by lift:")
    for _, row in sweep_df.head(10).iterrows():
        print(f"    {row['feature']:<30} {row['direction']} {row['threshold']:.4f}"
              f"  lift={row['lift']:.2f} prec={row['precision']:.4f} recall={row['recall']:.3f}")

    # ------------------------------------------------------------------ #
    # F. Symbolic rule discovery via Decision Tree                         #
    # ------------------------------------------------------------------ #
    print("\n[F] Decision tree induction (entry detection) …")

    # Prepare feature matrix on aligned entry bars + 5× random sample no-trade
    np.random.seed(42)
    entry_df = panel[panel["target_action"] != 0].copy()
    notrade_sample = panel[panel["target_action"] == 0].sample(
        min(len(entry_df) * 5, n_notrade), random_state=42
    ).copy()
    ml_df = pd.concat([entry_df, notrade_sample], ignore_index=True)

    available_feats = [c for c in feat_cols if ml_df[c].notna().mean() > 0.7]
    X = ml_df[available_feats].fillna(0)
    y = (ml_df["target_action"] != 0).astype(int)

    # Use a shallow tree to extract symbolic rules (not overfit)
    dt = DecisionTreeClassifier(max_depth=4, min_samples_leaf=5, random_state=42)
    dt.fit(X, y)
    train_acc = (dt.predict(X) == y).mean()
    print(f"  Tree depth used: {dt.get_depth()}")
    print(f"  Train accuracy:  {train_acc:.4f}")

    # Export human-readable rules
    tree_rules = export_text(dt, feature_names=list(available_feats), max_depth=4)
    rules_path = OUT_DIR / "decision_tree_rules.txt"
    rules_path.write_text(tree_rules, encoding="utf-8")
    print(f"  Tree rules saved: {rules_path.name}")

    # Feature importances
    importance_df = pd.DataFrame({
        "feature": available_feats,
        "importance": dt.feature_importances_,
    }).sort_values("importance", ascending=False)
    save_csv(importance_df, "decision_tree_importances")
    print(f"  Top 10 decision-tree features:")
    for _, row in importance_df.head(10).iterrows():
        print(f"    {row['feature']:<35} {row['importance']:.4f}")

    # Direction classification: Buy vs Sell (on trade bars only)
    print("\n[F] Direction classification (Buy vs Sell) …")
    trade_df = panel[panel["target_action"] != 0].copy()
    X_dir = trade_df[available_feats].fillna(0)
    y_dir = (trade_df["target_action"] == 1).astype(int)  # 1 = Buy, 0 = Sell

    if y_dir.nunique() == 2:
        dt_dir = DecisionTreeClassifier(max_depth=4, min_samples_leaf=3, random_state=42)
        dt_dir.fit(X_dir, y_dir)
        dir_acc = (dt_dir.predict(X_dir) == y_dir).mean()
        dir_tree_rules = export_text(dt_dir, feature_names=list(available_feats))
        dir_rules_path = OUT_DIR / "direction_tree_rules.txt"
        dir_rules_path.write_text(dir_tree_rules, encoding="utf-8")
        print(f"  Direction tree train accuracy: {dir_acc:.4f}")

        dir_importance_df = pd.DataFrame({
            "feature": available_feats,
            "importance": dt_dir.feature_importances_,
        }).sort_values("importance", ascending=False)
        save_csv(dir_importance_df, "direction_tree_importances")
        print(f"  Top 10 direction features:")
        for _, row in dir_importance_df.head(10).iterrows():
            print(f"    {row['feature']:<35} {row['importance']:.4f}")

    # ------------------------------------------------------------------ #
    # G. Walk-forward out-of-sample validation                             #
    # ------------------------------------------------------------------ #
    print("\n[G] Walk-forward out-of-sample validation …")

    # Sort panel by timestamp, expand 5-fold walk-forward
    panel_sorted = panel.sort_values("timestamp").reset_index(drop=True)
    X_all = panel_sorted[available_feats].fillna(0)
    y_all = (panel_sorted["target_action"] != 0).astype(int)

    n = len(panel_sorted)
    fold_size = n // 6  # 5 train/test splits, train grows

    wf_results = []
    for fold in range(5):
        train_end = fold_size * (fold + 1)
        test_start = train_end
        test_end = min(train_end + fold_size, n)

        X_train = X_all.iloc[:train_end]
        y_train = y_all.iloc[:train_end]
        X_test = X_all.iloc[test_start:test_end]
        y_test = y_all.iloc[test_start:test_end]

        if y_train.sum() < 5 or y_test.sum() < 2:
            continue

        clf = DecisionTreeClassifier(max_depth=4, min_samples_leaf=5, random_state=42)
        clf.fit(X_train, y_train)

        y_pred = clf.predict(X_test)
        y_prob = clf.predict_proba(X_test)[:, 1]

        tp = ((y_pred == 1) & (y_test == 1)).sum()
        fp = ((y_pred == 1) & (y_test == 0)).sum()
        fn = ((y_pred == 0) & (y_test == 1)).sum()
        prec = tp / (tp + fp + 1e-9)
        rec = tp / (tp + fn + 1e-9)
        try:
            auc = roc_auc_score(y_test, y_prob)
        except Exception:
            auc = np.nan

        train_dates = panel_sorted["timestamp"].iloc[[0, train_end - 1]]
        test_dates = panel_sorted["timestamp"].iloc[[test_start, test_end - 1]]

        wf_results.append({
            "fold": fold + 1,
            "train_from": train_dates.iloc[0],
            "train_to": train_dates.iloc[1],
            "test_from": test_dates.iloc[0],
            "test_to": test_dates.iloc[1],
            "train_entries": int(y_train.sum()),
            "test_entries": int(y_test.sum()),
            "precision": prec,
            "recall": rec,
            "roc_auc": auc,
            "lift": prec / (y_test.mean() + 1e-9),
        })

    wf_df = pd.DataFrame(wf_results)
    save_csv(wf_df, "walk_forward_validation")
    print(f"  Walk-forward results (5 folds):")
    for _, row in wf_df.iterrows():
        print(f"    Fold {int(row['fold'])}: "
              f"{str(row['train_to'])[:10]} | test {str(row['test_from'])[:10]}-{str(row['test_to'])[:10]} "
              f" prec={row['precision']:.3f} rec={row['recall']:.3f} auc={row['roc_auc']:.3f}")

    # Null / baseline comparison: random classifier at observed entry rate
    base_rate = y_all.mean()
    null_prec = base_rate
    print(f"\n  Baseline (random) precision: {null_prec:.4f}  "
          f"  Model mean OOS precision: {wf_df['precision'].mean():.4f}")
    print(f"  Mean OOS lift over null:    {wf_df['lift'].mean():.2f}×")

    # ------------------------------------------------------------------ #
    # H. Summarize reference-feed excursion paths                         #
    # ------------------------------------------------------------------ #
    print("\n[H] Reference-feed excursion summary (not SL/TP inference) …")

    exc2 = excursions.copy()
    # These are reference-feed path extrema.  A loss's adverse excursion is
    # not a stop distance, and a winner's favorable excursion is not a target:
    # the broker bid/ask path, exit price, and order modifications are absent.
    losses = exc2[exc2["final_pnl"] < 0].copy()
    wins = exc2[exc2["final_pnl"] >= 0].copy()

    # Pip values
    print(f"  Loss trades ({len(losses)}): MAE (pip) mean={losses['mae_pips'].mean():.1f}  "
          f"median={losses['mae_pips'].median():.1f}  std={losses['mae_pips'].std():.1f}")
    print(f"  Win trades ({len(wins)}): MFE (pip) mean={wins['mfe_pips'].mean():.1f}  "
          f"median={wins['mfe_pips'].median():.1f}")

    # Distributional reference-feed summaries, retained for auditability.
    loss_mae_pip = losses["mae_pips"].abs().dropna()
    pcts_sl = np.percentile(loss_mae_pip.values, [25, 50, 75, 90, 95])
    print(f"  Loss MAE pip percentiles [25,50,75,90,95]: "
          f"{[f'{p:.1f}' for p in pcts_sl]}")

    # Reference-feed favorable-excursion percentiles.
    win_mfe_pip = wins["mfe_pips"].dropna()
    pcts_tp = np.percentile(win_mfe_pip.values, [25, 50, 75, 90, 95])
    print(f"  Win MFE pip percentiles [25,50,75,90,95]: "
          f"{[f'{p:.1f}' for p in pcts_tp]}")

    # A descriptive ratio of two selected extrema, not a risk/reward ratio.
    rr = np.median(win_mfe_pip) / np.median(loss_mae_pip)
    print(f"  Implied R:R (median MFE win / median MAE loss): {rr:.2f}")

    geometry_df = pd.DataFrame({
        "metric": [
            "loss_mae_pip_mean", "loss_mae_pip_median", "loss_mae_pip_p75", "loss_mae_pip_p90",
            "win_mfe_pip_mean", "win_mfe_pip_median", "win_mfe_pip_p75", "win_mfe_pip_p90",
            "implied_rr_median",
        ],
        "value": [
            loss_mae_pip.mean(), loss_mae_pip.median(),
            np.percentile(loss_mae_pip, 75), np.percentile(loss_mae_pip, 90),
            win_mfe_pip.mean(), win_mfe_pip.median(),
            np.percentile(win_mfe_pip, 75), np.percentile(win_mfe_pip, 90),
            rr,
        ]
    })
    save_csv(geometry_df, "reference_feed_excursion_summary")

    # ------------------------------------------------------------------ #
    # Save analysis metrics                                                #
    # ------------------------------------------------------------------ #
    print("\n[H] Saving market reconstruction metrics …")

    metrics: dict[str, Any] = {
        "data_source": "Dukascopy bid (M1, UTC+3 shifted)",
        "market_bars": int(len(bars)),
        "trades": int(len(trades)),
        "entry_match_rate": n_matched / len(trades),
        "median_lag_seconds": float(aligned["market_match_lag_seconds"].median()),
        "panel_rows": int(total_mins),
        "entry_rate_pct": float(n_buy + n_sell) / total_mins * 100,
        "mfe_mean_pips": float(excursions["mfe_pips"].mean()),
        "mae_mean_pips": float(excursions["mae_pips"].mean()),
        "reference_excursion_ratio_median": float(rr),
        "wf_mean_precision": float(wf_df["precision"].mean()),
        "wf_mean_auc": float(wf_df["roc_auc"].mean()),
        "wf_mean_lift": float(wf_df["lift"].mean()),
        "null_precision": float(null_prec),
    }
    with open(OUT_DIR / "market_reconstruction_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print("\n" + "=" * 68)
    print("MARKET RECONSTRUCTION COMPLETE")
    print(f"  Outputs: {OUT_DIR}")
    print("=" * 68)


if __name__ == "__main__":
    main()
