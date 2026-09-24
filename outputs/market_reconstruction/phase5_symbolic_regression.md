# Phase 5 symbolic candidate generation

A fixed eight-expression, depth-limited Boolean grammar was enumerated instead of an unconstrained formula search. The candidate set was defined before testing. BH FDR correction is applied separately to the eight panel-enrichment tests and eight final-level-F matched-control tests. These are observable-space predicates, not an EA formula.

| expression | features_used | complexity | training_precision | oos_precision | oos_recall | oos_f1 | oos_pr_auc | predicted_signals | actual_trades_captured | false_alarms | fold_stability | enrichment_pvalue | matched_discordant_trade_only | matched_discordant_control_only | matched_pvalue | enrichment_qvalue | matched_qvalue | acceptance |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m30_boundary | m30_boundary | 1 | NOT_FIT | 0.003116 | 0.085714 | 0.006013 | NOT_APPLICABLE_PREDICATE | 11555 | 36 | 11519 | static predicate; evaluated across full observable panel | 1e-06 | 0 | 0 | 1.0 | 5e-06 | 1.0 | REJECTED_AS_RECONSTRUCTION |
| m30_boundary_and_positive_5m | m30_boundary_+_positive_5m | 2 | NOT_FIT | 0.002879 | 0.038095 | 0.005353 | NOT_APPLICABLE_PREDICATE | 5558 | 16 | 5542 | static predicate; evaluated across full observable panel | 0.001636 | 0 | 0 | 1.0 | 0.003271 | 1.0 | REJECTED_AS_RECONSTRUCTION |
| m30_boundary_and_negative_5m | m30_boundary_+_negative_5m | 2 | NOT_FIT | 0.003344 | 0.047619 | 0.00625 | NOT_APPLICABLE_PREDICATE | 5980 | 20 | 5960 | static predicate; evaluated across full observable panel | 6.9e-05 | 0 | 0 | 1.0 | 0.000185 | 1.0 | REJECTED_AS_RECONSTRUCTION |
| m30_boundary_and_rsi_high | m30_boundary_+_rsi_high | 2 | NOT_FIT | 0.002505 | 0.02619 | 0.004573 | NOT_APPLICABLE_PREDICATE | 4391 | 11 | 4380 | static predicate; evaluated across full observable panel | 0.020401 | 3 | 3 | 1.0 | 0.032642 | 1.0 | REJECTED_AS_RECONSTRUCTION |
| m30_boundary_and_rsi_low | m30_boundary_+_rsi_low | 2 | NOT_FIT | 0.00402 | 0.042857 | 0.00735 | NOT_APPLICABLE_PREDICATE | 4478 | 18 | 4460 | static predicate; evaluated across full observable panel | 1.6e-05 | 6 | 2 | 0.289062 | 6.2e-05 | 1.0 | REJECTED_AS_RECONSTRUCTION |
| m30_boundary_and_range_expansion | m30_boundary_+_range_expansion | 2 | NOT_FIT | 0.00274 | 0.016667 | 0.004706 | NOT_APPLICABLE_PREDICATE | 2555 | 7 | 2548 | static predicate; evaluated across full observable panel | 0.038442 | 6 | 9 | 0.607239 | 0.051256 | 1.0 | REJECTED_AS_RECONSTRUCTION |
| local_breakout | local_breakout | 1 | NOT_FIT | 0.001479 | 0.078571 | 0.002904 | NOT_APPLICABLE_PREDICATE | 22309 | 33 | 22276 | static predicate; evaluated across full observable panel | 0.14642 | 21 | 9 | 0.042774 | 0.167338 | 0.342192 | REJECTED_AS_RECONSTRUCTION |
| high_volatility_and_momentum | high_volatility_+_momentum | 2 | NOT_FIT | 0.001193 | 0.121429 | 0.002362 | NOT_APPLICABLE_PREDICATE | 42755 | 51 | 42704 | static predicate; evaluated across full observable panel | 0.562586 | 0 | 0 | 1.0 | 0.562586 | 1.0 | REJECTED_AS_RECONSTRUCTION |

No expression is accepted as a reconstruction unless it satisfies both predeclared OOS and matched-control requirements.
