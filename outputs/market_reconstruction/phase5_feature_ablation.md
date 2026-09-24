# Phase 5 feature-family ablation

The ten hypothesis families were predeclared before inspection: A CLOCK, B GEOMETRY, C MOMENTUM, D VOLATILITY, E TREND/LOCATION, F ACCOUNT STATE, and the four stated combinations. Each uses the same L1 logistic candidate and chronological protocol.

| candidate | family | validation_observations | signals | trades_captured | false_alarms | mean_fold_precision | mean_fold_recall | mean_fold_f1 | mean_pr_auc | mean_roc_auc | mean_signals_per_10000 | pooled_precision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| l1_logistic | A_CLOCK | 173345 | 254 | 0 | 254 | 0.0 | 0.0 | 0.0 | 0.002221 | 0.674885 | 14.65286 | 0.0 |
| l1_logistic | B_GEOMETRY | 173345 | 173345 | 237 | 173108 | 0.001367 | 1.0 | 0.002731 | 0.001367 | 0.5 | 10000.0 | 0.001367 |
| l1_logistic | C_MOMENTUM | 173345 | 173345 | 237 | 173108 | 0.001367 | 1.0 | 0.002731 | 0.001367 | 0.5 | 10000.0 | 0.001367 |
| l1_logistic | D_VOLATILITY | 173345 | 138676 | 192 | 138484 | 0.001108 | 0.8 | 0.002212 | 0.001352 | 0.497177 | 8000.0 | 0.001385 |
| l1_logistic | E_TREND_LOCATION | 173345 | 173345 | 237 | 173108 | 0.001367 | 1.0 | 0.002731 | 0.001367 | 0.5 | 10000.0 | 0.001367 |
| l1_logistic | F_ACCOUNT_STATE | 173345 | 150 | 2 | 148 | 0.009697 | 0.008291 | 0.008867 | 0.003189 | 0.678833 | 8.653264 | 0.013333 |
| l1_logistic | G_CLOCK_MARKET | 173345 | 254 | 0 | 254 | 0.0 | 0.0 | 0.0 | 0.002221 | 0.6749 | 14.65286 | 0.0 |
| l1_logistic | H_CLOCK_STATE | 173345 | 89 | 1 | 88 | 0.005714 | 0.004878 | 0.005263 | 0.003771 | 0.714604 | 5.13427 | 0.011236 |
| l1_logistic | I_MARKET_STATE | 173345 | 150 | 2 | 148 | 0.009697 | 0.008291 | 0.008867 | 0.003189 | 0.678807 | 8.653264 | 0.013333 |
| l1_logistic | J_CLOCK_MARKET_STATE | 173345 | 89 | 1 | 88 | 0.005714 | 0.004878 | 0.005263 | 0.003771 | 0.714633 | 5.13427 | 0.011236 |

No family is called a reconstruction unless it distinguishes matched controls and has stable OOS precision and recall.
