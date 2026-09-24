# Pre-trade sizing-state analysis (Claude P10 completion)

## Result

The large-lot indicator (`lot_size > 0.01`) occurs 22 times and all 22 have positive reported result. The simple plug-in IID probability is 0.0440; using separate observed win fractions within the two ticket segments gives 0.0590. Neither is a valid identification test after exploratory selection, estimated base rates, dependence and regime concentration.

The strongest observed explanation is temporal/operational regime: the large-lot rate is 17.89% before the ticket namespace jump and 1.52% after it (Fisher p=2.74e-08). This supports a sizing regime change; it does not establish discretionary conviction, signal strength, or a second EA.

There are 7 adjacent large-lot pairs versus a shuffled mean of 1.09 (permutation p=0.0002). Spearman correlation between lot size and cumulative reported result available before the trade is -0.176 (p=0.0003); cumulative closed result is not account equity.

All predictors below are available before the current trade. Market variables use the prior completed M1 bar; cumulative result excludes the current row.

## Registered univariate tests

| predictor | test | n | large_lot_n | effect | effect_label | odds_ratio | family_p | bh_q |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| previous_large | Fisher exact | 423 | 22 | 0.2808 | large-lot rate difference (1 minus 0) | 12.01 | 3.91e-05 | 0.000391 |
| previous_win_pre | Fisher exact | 423 | 22 | -0.021 | large-lot rate difference (1 minus 0) | 0.6853 | 0.5184 | 0.7406 |
| first_trade_day | Fisher exact | 423 | 22 | 0.0453 | large-lot rate difference (1 minus 0) | 2.826 | 0.04637 | 0.1159 |
| buy | Fisher exact | 423 | 22 | -0.00123 | large-lot rate difference (1 minus 0) | 0.9754 | 1 | 1 |
| segment_b | Fisher exact | 423 | 22 | -0.1637 | large-lot rate difference (1 minus 0) | 0.07103 | 2.742e-08 | 5.483e-07 |
| previous_pnl_pre | Mann-Whitney plus label permutation | 422 | 22 | 0.0892 | Cliff delta (large minus base) | n.a. | 0.4815 | 0.7406 |
| previous_size_pre | Mann-Whitney plus label permutation | 422 | 22 | 0.2799 | Cliff delta (large minus base) | n.a. | 1 | 1 |
| recent5_pnl_pre | Mann-Whitney plus label permutation | 422 | 22 | 0.1077 | Cliff delta (large minus base) | n.a. | 0.7911 | 1 |
| recent5_win_rate_pre | Mann-Whitney plus label permutation | 422 | 22 | -0.03818 | Cliff delta (large minus base) | n.a. | 1 | 1 |
| previous_pnl_per_001_pre | Mann-Whitney plus label permutation | 422 | 22 | -0.1068 | Cliff delta (large minus base) | n.a. | 0.3992 | 0.7259 |
| cumulative_pnl_pre | Mann-Whitney plus label permutation | 423 | 22 | -0.4573 | Cliff delta (large minus base) | n.a. | 0.0004998 | 0.003332 |
| gap_entry_pre | Mann-Whitney plus label permutation | 422 | 22 | 0.1828 | Cliff delta (large minus base) | n.a. | 0.1489 | 0.3059 |
| gap_exit_pre | Mann-Whitney plus label permutation | 422 | 22 | 0.181 | Cliff delta (large minus base) | n.a. | 0.1529 | 0.3059 |
| hour_sin | Mann-Whitney plus label permutation | 423 | 22 | 0.05645 | Cliff delta (large minus base) | n.a. | 0.9015 | 1 |
| hour_cos | Mann-Whitney plus label permutation | 423 | 22 | -0.3674 | Cliff delta (large minus base) | n.a. | 0.01149 | 0.04598 |
| m1_atr14 | Mann-Whitney plus label permutation | 423 | 22 | -0.3517 | Cliff delta (large minus base) | n.a. | 0.02149 | 0.07163 |
| m1_atr_ratio | Mann-Whitney plus label permutation | 423 | 22 | -0.2839 | Cliff delta (large minus base) | n.a. | 0.03798 | 0.1085 |
| m1_close | Mann-Whitney plus label permutation | 423 | 22 | -0.4254 | Cliff delta (large minus base) | n.a. | 0.006497 | 0.03248 |
| m1_ema20_dist | Mann-Whitney plus label permutation | 423 | 22 | 0.006688 | Cliff delta (large minus base) | n.a. | 0.9586 | 1 |
| m1_range_percentile_240 | Mann-Whitney plus label permutation | 423 | 22 | -0.08717 | Cliff delta (large minus base) | n.a. | 0.4916 | 0.7406 |

## Chronological sparse-logistic validation

| fold | train_n | test_n | train_large | test_large | roc_auc | pr_auc | base_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 148 | 55 | 17 | 0 | n.a. | n.a. | 0 |
| 2 | 203 | 55 | 17 | 0 | n.a. | n.a. | 0 |
| 3 | 258 | 55 | 17 | 1 | 0.7778 | 0.07692 | 0.01818 |
| 4 | 313 | 55 | 18 | 0 | n.a. | n.a. | 0 |
| 5 | 368 | 55 | 18 | 4 | 0.7794 | 0.4688 | 0.07273 |

Mean walk-forward ROC AUC is 0.779; mean PR AUC is 0.273. Folds with no large-lot test rows cannot identify predictive discrimination. The model is diagnostic, not a deployable sizing rule.
