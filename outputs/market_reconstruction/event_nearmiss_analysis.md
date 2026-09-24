# Event near-miss analysis

## Design

Each of the 423 observed trades is paired with the most similar eligible non-entry M1 candidate before and after it on the same raw-clock day/session, normally within ±120 minutes. Similarity uses pre-entry volatility, range, return, location, higher-timeframe proxy state and clock features. The controls are limited to the observed position-capacity envelope (zero or one active recorded position): five actual entry bars occur while one trade is already open. This is a matched descriptive experiment, not proof of the unobserved broker opportunity set.

`event_nearmiss_table.csv` has one row per trade. `event_matched_controls.csv` retains the two control rows used for testing.

## Measured event and clock features that differ after matching

| event_feature | trade_rate | matched_control_rate | paired_rate_difference | trade_n | permutation_p | bh_q |
| --- | --- | --- | --- | --- | --- | --- |
| boundary_30 | 0.085106 | 0.035461 | 0.049645 | 423 | 0.0009995 | 0.010495 |
| boundary_60 | 0.047281 | 0.01182 | 0.035461 | 423 | 0.00049975 | 0.010495 |
| boundary_15 | 0.11111 | 0.073286 | 0.037825 | 423 | 0.025987 | 0.18191 |
| event_lower_high_break | 0.11111 | 0.085106 | 0.026005 | 423 | 0.057471 | 0.29269 |
| event_large_body_expansion | 0.078014 | 0.056738 | 0.021277 | 423 | 0.11244 | 0.29269 |
| event_cross_prior_high_20 | 0.078014 | 0.05792 | 0.020095 | 423 | 0.12544 | 0.29269 |
| event_cross_prior_low_20 | 0.078014 | 0.059102 | 0.018913 | 423 | 0.095952 | 0.29269 |
| event_compression_to_expansion | 0.0047281 | 0 | 0.0047281 | 423 | 0.12144 | 0.29269 |
| event_impulse_pullback_cont_up | 0.0047281 | 0 | 0.0047281 | 423 | 0.11144 | 0.29269 |
| event_cross_prior_low_10 | 0.11348 | 0.092199 | 0.021277 | 423 | 0.15942 | 0.33478 |
| event_cross_prior_high_10 | 0.10875 | 0.088652 | 0.020095 | 423 | 0.18891 | 0.36064 |
| event_higher_low_break | 0.10165 | 0.082742 | 0.018913 | 423 | 0.22039 | 0.38568 |

The matched feature family uses 2,000 within-set label permutations and Benjamini–Hochberg adjustment across the event-feature family. Any association remains a candidate eligibility correlate because unmeasured price path, ask/bid, spread, timer and order-state variables are absent.

## Result

The table demonstrates whether the measured completed-bar events make observed entries less generic than comparable nearby non-trades. It does not establish a unique hidden trigger; a frequent event among controls falsifies a simple deterministic version of that event rule.
