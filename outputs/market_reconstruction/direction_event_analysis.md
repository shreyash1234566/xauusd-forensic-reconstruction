# Direction event analysis

Direction is modeled only among observed entry bars using pre-entry completed-bar event geometry and location variables. Across 5 chronological folds, the event-geometry direction model has mean accuracy 0.527, mean ROC AUC 0.521, and mean Buy PR AUC 0.546.

| fold | train_n | test_n | buy_rate_test | direction_accuracy | roc_auc | pr_auc_buy |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 114 | 68 | 0.54412 | 0.5 | 0.43592 | 0.52845 |
| 2 | 182 | 78 | 0.5641 | 0.51282 | 0.52072 | 0.5601 |
| 3 | 260 | 64 | 0.34375 | 0.5 | 0.47186 | 0.38077 |
| 4 | 324 | 51 | 0.4902 | 0.58824 | 0.63692 | 0.62707 |
| 5 | 375 | 45 | 0.48889 | 0.53333 | 0.53953 | 0.63277 |

This asks whether one event family has opposite Buy/Sell polarity under local state. It does not establish two separate direction algorithms.
