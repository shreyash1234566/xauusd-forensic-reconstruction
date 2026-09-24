# Phase 5 baseline observable-space models

Five predeclared regularized/restricted classifiers were evaluated with five expanding chronological folds. Training used a bounded case-control sample for computational stability; every validation metric is computed across the full chronological candidate-minute fold. Thresholds select the predeclared raw-trade-rate signal budget. A 15-minute embargo separates train from validation.

| candidate | family | validation_observations | signals | trades_captured | false_alarms | mean_fold_precision | mean_fold_recall | mean_fold_f1 | mean_pr_auc | mean_roc_auc | mean_signals_per_10000 | pooled_precision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| elastic_net | CLOCK+MARKET+STATE | 173345 | 119 | 1 | 118 | 0.005556 | 0.004878 | 0.005195 | 0.004889 | 0.735329 | 6.864923 | 0.008403 |
| l1_logistic | CLOCK+MARKET+STATE | 173345 | 89 | 1 | 88 | 0.005714 | 0.004878 | 0.005263 | 0.003771 | 0.714633 | 5.13427 | 0.011236 |
| restricted_gradient_boosting | CLOCK+MARKET+STATE | 173345 | 123 | 0 | 123 | 0.0 | 0.0 | 0.0 | 0.005148 | 0.746084 | 7.095676 | 0.0 |
| restricted_random_forest | CLOCK+MARKET+STATE | 173345 | 109 | 1 | 108 | 0.009524 | 0.005405 | 0.006897 | 0.006598 | 0.739148 | 6.288038 | 0.009174 |
| shallow_tree | CLOCK+MARKET+STATE | 173345 | 24590 | 76 | 24514 | 0.004723 | 0.33068 | 0.009092 | 0.003368 | 0.716984 | 1418.558366 | 0.003091 |

PR AUC is primary; ROC AUC is secondary under extreme imbalance. Neither is evidence that the original EA has been recovered.
