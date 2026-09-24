# Entry reconstruction and negative-space analysis

## Leakage control and data granularity

The candidate panel uses the existing Dukascopy bid-only aggregated M1 proxy. Every M1 market feature is shifted one complete bar. M5/M15/H1 values are joined only when their bar has completed. Trade outcome, close time, P&L, MFE and MAE are excluded from entry predictors. Five expanding chronological folds begin after the first 35% of elapsed history.

Because entries contain seconds but the reference data are M1 OHLC, the analysis cannot distinguish bar open, first tick after close, intrabar threshold crossing or an N-second timer. Exact-second match rates are therefore diagnostic limits, not model failures alone.

## Candidate architectures

| model | description | historical_candidate_signals | historical_matched_entry_bars | historical_precision | historical_recall | oos_tp | oos_fp | oos_fn | oos_precision | oos_recall | oos_f1_mean | oos_roc_auc_mean | oos_pr_auc_mean | oos_direction_accuracy_matched | oos_entry_match_60s_mean | oos_entry_match_one_m1_bar_mean | parameters_or_rules | complexity | bic_mdl | oos_entry_match_1s_mean | oos_entry_match_5s_mean | oos_entry_match_15s_mean | oos_entry_match_30s_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MODEL 0 time/session | Time and bar-clock state only | 7862 | 34 | 0.004325 | 0.08095 | 67 | 21485 | 239 | 0.003109 | 0.219 | 0.008036 | 0.6848 | 0.002488 | 0.4962 | 0.2106 | 0.2241 | 10 | linear | not valid | 0.005882 | 0.03302 | 0.09459 | 0.1874 |
| MODEL 8 constrained nonlinear | 120 depth-3 boosted trees | 17159 | 121 | 0.007052 | 0.2881 | 33 | 10469 | 273 | 0.003142 | 0.1078 | 0.005567 | 0.7067 | 0.002883 | 0.219 | 0.1299 | 0.1435 | 120 | 120 depth-3 trees | not valid | 0.002941 | 0.01289 | 0.04668 | 0.09736 |
| MODEL 5 expansion+session+HTF | Adds completed M5/M15/H1 context | 3976 | 18 | 0.004527 | 0.04286 | 59 | 18385 | 247 | 0.003199 | 0.1928 | 0.003662 | 0.6903 | 0.002612 | 0.5429 | 0.201 | 0.2227 | 60 | linear | not valid | 0.005882 | 0.02058 | 0.07738 | 0.1659 |
| MODEL 6 prior interpretable | Lagged version of prior body/EMA/VWAP candidate | 33909 | 42 | 0.001239 | 0.1 | 9 | 7337 | 297 | 0.001225 | 0.02941 | 0.00256 | 0.4998 | 0.001429 | 0.6667 | 0.04205 | 0.04793 | 5 | linear | not valid | 0 | 0.007386 | 0.01307 | 0.0321 |
| MODEL 2 expansion+trend | M1 expansion and trend/location | 1387 | 2 | 0.001442 | 0.004762 | 55 | 38456 | 251 | 0.001428 | 0.1797 | 0.002191 | 0.5251 | 0.001567 | 0.479 | 0.2442 | 0.2876 | 37 | linear | not valid | 0.01093 | 0.04525 | 0.09609 | 0.1813 |
| MODEL 7 sparse rule | L1 sparse logistic rule | 144554 | 354 | 0.002449 | 0.8429 | 69 | 29809 | 237 | 0.002309 | 0.2255 | 0.002072 | 0.6879 | 0.002486 | 0.5401 | 0.2728 | 0.2786 | 70 | sparse linear | not valid | 0.01033 | 0.04438 | 0.1329 | 0.2492 |
| MODEL 3 expansion+trend+VWAP | Adds session VWAP proxy | 37470 | 72 | 0.001922 | 0.1714 | 30 | 24395 | 276 | 0.001228 | 0.09804 | 0.001827 | 0.5317 | 0.001577 | 0.4253 | 0.1589 | 0.1876 | 38 | linear | not valid | 0.003922 | 0.01662 | 0.05496 | 0.107 |
| MODEL 1 M1 expansion | Prior completed M1 expansion only | 2023 | 4 | 0.001977 | 0.009524 | 13 | 16104 | 293 | 0.0008066 | 0.04248 | 0.00168 | 0.5343 | 0.00176 | 0.7667 | 0.08979 | 0.1239 | 17 | linear | not valid | 0.004444 | 0.01902 | 0.04261 | 0.06104 |
| MODEL 4 expansion+session | M1 expansion plus clock state | 149404 | 352 | 0.002356 | 0.8381 | 1 | 1470 | 305 | 0.0006798 | 0.003268 | 0.0008989 | 0.6843 | 0.002567 | 0 | 0.005689 | 0.0127 | 27 | linear | not valid | 0 | 0 | 0 | 0.005689 |

The strongest OOS architecture by the prespecified F1/PR ordering is **MODEL 0 time/session**. It produces OOS precision 0.00311, recall 0.21895, mean F1 0.00804, mean ROC AUC 0.685, and mean PR AUC 0.00249. These values do not approach event-level replication of the 423 trades.

Time-only MODEL 0 has mean OOS PR AUC 0.00249. M1 expansion MODEL 1 has 0.00176; completed HTF context MODEL 5 has 0.00261. Incremental differences are clues, not proof that the source contains those indicators.

## Negative space

`near_miss_events.csv` supplies up to three same-day, ±120-minute non-entry bars nearest to each observed entry in lagged expansion, volatility, velocity, EMA-spread, VWAP-distance and clock space. The persistence of close near-misses confirms the central unresolved question: the available M1 state does not explain why the account selected these specific bars and rejected many similar bars.

## Current entry conclusion

No tested architecture reproduces enough exact events to identify the source algorithm. Body/volatility, clock, trend/location and HTF variables remain a **partial market fingerprint**, not an executable reconstruction.
