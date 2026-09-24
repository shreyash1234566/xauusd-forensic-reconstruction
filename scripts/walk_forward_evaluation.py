import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.metrics import precision_score, recall_score, roc_auc_score, f1_score, precision_recall_curve, auc
import json
from pathlib import Path

ROOT = Path(".")
PANEL_PATH = ROOT / "data" / "processed" / "decision_panel.parquet"
TRADES_PATH = ROOT / "outputs" / "market_reconstruction" / "phase7c_trade_reconciliation.csv"

df = pd.read_parquet(PANEL_PATH)
df['dt'] = pd.to_datetime(df['dt'])
df['dow'] = df['dt'].dt.dayofweek
df = df.sort_values('dt').reset_index(drop=True)

feature_cols = [c for c in df.columns if c not in ['dt', 'is_trade', 'trade_dir', 'dow']]
df[feature_cols] = df[feature_cols].fillna(0.0)

print(f"Dataset: {len(df)} bars, {df['is_trade'].sum()} trade entries")

# 1. 5-Fold Walk-Forward Purged Expanding Window Validation
n_splits = 5
split_size = len(df) // (n_splits + 1)

print("\n=== 1. WALK-FORWARD EXPANDING WINDOW: ENTRY TRIGGER (Positive vs Counterfactual Non-Trade) ===")
fold_results = []
for i in range(1, n_splits + 1):
    train_end = split_size * i
    test_start = train_end + 60 # 60-bar purge
    test_end = split_size * (i + 1)
    if i == n_splits:
        test_end = len(df)

    train_df = df.iloc[:train_end]
    test_df = df.iloc[test_start:test_end]

    X_train, y_train = train_df[feature_cols], train_df['is_trade']
    X_test, y_test = test_df[feature_cols], test_df['is_trade']

    # Train Balanced Random Forest
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

    print(f"Fold {i}: Train bars={len(train_df)} (Pos={y_train.sum()}), Test bars={len(test_df)} (Pos={y_test.sum()}) | ROC-AUC={roc:.4f}, PR-AUC={pr_auc:.6f}, Prec@99.5%={prec*100:.2f}%, Recall={rec*100:.2f}%")
    fold_results.append({'fold': i, 'roc_auc': roc, 'pr_auc': pr_auc, 'precision': prec, 'recall': rec})

print(f"Mean Walk-Forward ROC-AUC: {np.mean([r['roc_auc'] for r in fold_results]):.4f}")

# 2. Walk-Forward Direction Classification (Buy vs Sell)
trade_panel = df[df['is_trade'] == 1].copy()
trade_panel['trade_dir'] = trade_panel['trade_dir'].astype(int)

print("\n=== 2. WALK-FORWARD EXPANDING WINDOW: DIRECTION RECONSTRUCTION (Buy vs Sell) ===")
dir_results = []
n_trades = len(trade_panel)
t_split = n_trades // (n_splits + 1)
for i in range(1, n_splits + 1):
    t_train_end = t_split * i
    t_train = trade_panel.iloc[:t_train_end]
    t_test = trade_panel.iloc[t_train_end: t_split * (i + 1) if i < n_splits else n_trades]

    X_tr, y_tr = t_train[feature_cols], t_train['trade_dir']
    X_te, y_te = t_test[feature_cols], t_test['trade_dir']

    rf_dir = RandomForestClassifier(n_estimators=100, max_depth=4, random_state=42)
    rf_dir.fit(X_tr, y_tr)

    preds = rf_dir.predict(X_te)
    probs = rf_dir.predict_proba(X_te)[:, 1] if len(rf_dir.classes_) > 1 else np.zeros(len(y_te))
    acc = (preds == y_te).mean()
    roc = roc_auc_score(y_te, probs) if len(np.unique(y_te)) > 1 else np.nan
    print(f"Fold {i}: Train={len(t_train)} (Buys={y_tr.sum()}), Test={len(t_test)} (Buys={y_te.sum()}) | Accuracy={acc*100:.2f}%, ROC-AUC={roc:.4f}")
    dir_results.append({'fold': i, 'acc': acc, 'roc': roc})

print(f"Mean Direction Accuracy: {np.mean([r['acc'] for r in dir_results])*100:.2f}%")

# 3. Matched Negative Controls (Identical hour/minute on non-trade days)
print("\n=== 3. MATCHED NEGATIVE CONTROL ANALYSIS ===")
trades_recon = pd.read_csv(TRADES_PATH)
trades_recon['open_dt'] = pd.to_datetime(trades_recon['open_time_utc'])
trades_recon['dow'] = trades_recon['open_dt'].dt.dayofweek
trades_recon['hour'] = trades_recon['open_dt'].dt.hour
trades_recon['minute'] = trades_recon['open_dt'].dt.minute

matched_negatives = []
for idx, r in trades_recon.iterrows():
    candidates = df[(df['is_trade'] == 0) & (df['dow'] == r['dow']) & (df['utc_hour'] == r['hour']) & (df['utc_minute'] == r['minute'])]
    if len(candidates) > 0:
        sampled = candidates.sample(min(5, len(candidates)), random_state=42)
        matched_negatives.append(sampled)

if matched_negatives:
    matched_neg_df = pd.concat(matched_negatives).drop_duplicates(subset=['dt'])
    print(f"Constructed {len(matched_neg_df)} matched negative control bars (matched by DOW, Hour, Minute).")

    # Compare ATR, Return, and Indicators between Trade Bars and Matched Negatives
    t_atr = trade_panel['atr_pct_14'].mean()
    n_atr = matched_neg_df['atr_pct_14'].mean()
    print(f"Trade Bars Mean ATR%: {t_atr:.5f} vs Matched Negative Mean ATR%: {n_atr:.5f} (Delta: {(t_atr-n_atr)/n_atr*100:.2f}%)")

    t_ret = trade_panel['return_1'].abs().mean()
    n_ret = matched_neg_df['return_1'].abs().mean()
    print(f"Trade Bars Mean |Return_1|: {t_ret:.2f} vs Matched Negative Mean |Return_1|: {n_ret:.2f} (Delta: {(t_ret-n_ret)/n_ret*100:.2f}%)")

# 4. Parsimonious Decision Tree / Symbolic Rule Extraction
print("\n=== 4. PARSIMONIOUS SYMBOLIC RULE INDUCTION ===")
dt = DecisionTreeClassifier(max_depth=3, min_samples_leaf=10, random_state=42)
dt.fit(trade_panel[feature_cols], trade_panel['trade_dir'])
tree_rules = export_text(dt, feature_names=feature_cols)
print("Inducted Directional Decision Tree:\n", tree_rules)

# Feature Importances for Direction
rf_all = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
rf_all.fit(trade_panel[feature_cols], trade_panel['trade_dir'])
importances = pd.Series(rf_all.feature_importances_, index=feature_cols).sort_values(ascending=False)
print("\nTop 10 Feature Importances for Direction (Buy vs Sell):")
print(importances.head(10).to_string())
