"""
Phase 8B - Stage 8: 5-Fold Walk-Forward Expanding Window Validation
Evaluates strategy rule stability, precision, recall, and ROC-AUC on purged folds.
Statistical / ML stage (~5-10 seconds).
"""

from pathlib import Path
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import precision_score, recall_score, roc_auc_score, precision_recall_curve, auc

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUTS_DIR = ROOT / "outputs"
PANEL_PATH = DATA_DIR / "processed" / "decision_panel.parquet"
OUTPUT_DIR = OUTPUTS_DIR / "strategy_reconstruction"

def main():
    print("=================================================================")
    print("PHASE 8B - STAGE 08: WALK-FORWARD EXPANDING WINDOW VALIDATION")
    print("=================================================================")

    df = pd.read_parquet(PANEL_PATH)
    df['dt'] = pd.to_datetime(df['dt'])
    df = df.sort_values('dt').reset_index(drop=True)

    feature_cols = [c for c in df.columns if c not in ['dt', 'is_trade', 'trade_dir', 'hour_eet']]
    df[feature_cols] = df[feature_cols].fillna(0.0)

    print(f"Dataset: {len(df):,} bars, {df['is_trade'].sum()} trade entries")

    n_splits = 5
    split_size = len(df) // (n_splits + 1)
    purge_bars = 60 # 60-minute purge window between train and test

    fold_results = []
    print("\nRunning 5 Purged Expanding Folds for Entry Detection:")
    for i in range(1, n_splits + 1):
        train_end = split_size * i
        test_start = train_end + purge_bars
        test_end = split_size * (i + 1) if i < n_splits else len(df)

        train_df = df.iloc[:train_end]
        test_df = df.iloc[test_start:test_end]

        X_train, y_train = train_df[feature_cols], train_df['is_trade']
        X_test, y_test = test_df[feature_cols], test_df['is_trade']

        rf = RandomForestClassifier(n_estimators=100, max_depth=6, class_weight='balanced', random_state=42, n_jobs=-1)
        rf.fit(X_train, y_train)

        probs = rf.predict_proba(X_test)[:, 1]
        roc = roc_auc_score(y_test, probs)
        precision, recall, _ = precision_recall_curve(y_test, probs)
        pr_auc = auc(recall, precision)

        thresh = np.percentile(probs, 99.5)
        preds = (probs >= thresh).astype(int)
        prec = precision_score(y_test, preds, zero_division=0)
        rec = recall_score(y_test, preds, zero_division=0)

        print(f"  Fold {i}: Train={len(train_df):,} (Pos={y_train.sum()}), Test={len(test_df):,} (Pos={y_test.sum()}) | ROC-AUC={roc:.4f}, PR-AUC={pr_auc:.6f}, Prec@99.5%={prec*100:.2f}%, Recall={rec*100:.2f}%")

        fold_results.append({
            'fold': i,
            'train_bars': len(train_df),
            'test_bars': len(test_df),
            'test_positive_trades': int(y_test.sum()),
            'roc_auc': roc,
            'pr_auc': pr_auc,
            'precision_top_0.5pct': prec,
            'recall_top_0.5pct': rec
        })

    wf_df = pd.DataFrame(fold_results)
    out_wf_path = OUTPUT_DIR / "phase8b_walkforward_results.csv"
    wf_df.to_csv(out_wf_path, index=False)
    print(f"\n[PASS] Saved walk-forward results: {out_wf_path}")

    print(f"\nMean Walk-Forward ROC-AUC: {wf_df['roc_auc'].mean():.4f}")
    print(f"Mean Walk-Forward PR-AUC:  {wf_df['pr_auc'].mean():.6f}")

    print("\nSTAGE 08 COMPLETE.\n")

if __name__ == "__main__":
    main()
