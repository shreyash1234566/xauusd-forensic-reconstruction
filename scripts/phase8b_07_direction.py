"""
Phase 8B - Stage 7: Directional Predictability & Rule Recovery
Tests Buy vs Sell separation using standardized features across walk-forward folds.
Statistical / ML stage (~2-3 seconds).
"""

from pathlib import Path
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT / "outputs"
MICRO_PATH = OUTPUTS_DIR / "strategy_reconstruction" / "phase8b_tick_microstructure.csv"
FEATURES_PATH = OUTPUTS_DIR / "strategy_reconstruction" / "phase8b_trade_features.csv"
OUTPUT_DIR = OUTPUTS_DIR / "strategy_reconstruction"

def main():
    print("=================================================================")
    print("PHASE 8B - STAGE 07: DIRECTIONAL PREDICTABILITY AUDIT")
    print("=================================================================")

    micro_df = pd.read_csv(MICRO_PATH)
    feat_df = pd.read_csv(FEATURES_PATH)

    valid_micro = micro_df.dropna(subset=['ret_5s', 'ret_1s']).copy()
    valid_micro['target_dir'] = (valid_micro['side'] == 'Buy').astype(int)

    print(f"Total valid tick microstructure trades: {len(valid_micro)}")
    print(f"Buy trades: {(valid_micro['target_dir'] == 1).sum()} | Sell trades: {(valid_micro['target_dir'] == 0).sum()}")

    # 1. Simple Heuristic Direction Rules on Pre-Entry Ticks
    print("\nPre-Entry Momentum vs Reversal Directional Accuracy:")
    for w in [1, 3, 5, 10, 30, 60]:
        mom_pred = (valid_micro[f'ret_{w}s'] > 0).astype(int)
        mom_acc = (mom_pred == valid_micro['target_dir']).mean()
        rev_acc = 1.0 - mom_acc
        buy_mean_ret = valid_micro[valid_micro['target_dir'] == 1][f'ret_{w}s'].mean()
        sell_mean_ret = valid_micro[valid_micro['target_dir'] == 0][f'ret_{w}s'].mean()
        print(f"  Window {w:2d}s: Momentum Acc = {mom_acc*100:.2f}%, Reversal Acc = {rev_acc*100:.2f} (Buy mean ret: ${buy_mean_ret:+.4f}, Sell mean ret: ${sell_mean_ret:+.4f})")

    # 2. 5-Fold Walk-Forward on Standardized Tick Features
    tick_cols = [f'ret_{w}s' for w in [1, 3, 5, 10, 30, 60]] + \
                [f'accel_{w}s' for w in [3, 5, 10, 30]] + \
                [f'consec_upticks_{w}s' for w in [5, 10, 30]]

    X_tick = valid_micro[tick_cols].fillna(0.0)
    y_tick = valid_micro['target_dir'].values

    n_splits = 5
    split_sz = len(valid_micro) // (n_splits + 1)

    wf_accs_lr = []
    wf_accs_dt = []
    wf_rocs_lr = []

    for i in range(1, n_splits + 1):
        tr_end = split_sz * i
        te_start = tr_end
        te_end = split_sz * (i + 1) if i < n_splits else len(valid_micro)

        X_tr, y_tr = X_tick.iloc[:tr_end], y_tick[:tr_end]
        X_te, y_te = X_tick.iloc[te_start:te_end], y_tick[te_start:te_end]

        # Standardize features to prevent solver convergence warnings
        scaler = StandardScaler()
        X_tr_scaled = scaler.fit_transform(X_tr)
        X_te_scaled = scaler.transform(X_te)

        # Logistic Regression with L2 regularization
        lr = LogisticRegression(max_iter=1000, C=1.0, random_state=42)
        lr.fit(X_tr_scaled, y_tr)
        p_lr = lr.predict(X_te_scaled)
        prob_lr = lr.predict_proba(X_te_scaled)[:, 1] if len(lr.classes_) > 1 else np.zeros(len(y_te))

        acc_lr = accuracy_score(y_te, p_lr)
        roc_lr = roc_auc_score(y_te, prob_lr) if len(np.unique(y_te)) > 1 else np.nan
        wf_accs_lr.append(acc_lr)
        wf_rocs_lr.append(roc_lr)

        # Decision Stump
        dt = DecisionTreeClassifier(max_depth=2, random_state=42)
        dt.fit(X_tr, y_tr)
        p_dt = dt.predict(X_te)
        acc_dt = accuracy_score(y_te, p_dt)
        wf_accs_dt.append(acc_dt)

    print("\n5-Fold Walk-Forward Direction Performance (Tick Microstructure):")
    print(f"  Standardized Logistic Regression: Mean Acc = {np.mean(wf_accs_lr)*100:.2f}% (Folds: {[round(x*100, 1) for x in wf_accs_lr]})")
    print(f"  Standardized Logistic Regression: Mean ROC-AUC = {np.nanmean(wf_rocs_lr):.4f}")
    print(f"  Decision Stump (Depth=2):        Mean Acc = {np.mean(wf_accs_dt)*100:.2f}% (Folds: {[round(x*100, 1) for x in wf_accs_dt]})")

    print("\nSTAGE 07 COMPLETE.\n")

if __name__ == "__main__":
    main()
