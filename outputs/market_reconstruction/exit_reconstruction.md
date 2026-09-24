# Exit reconstruction

## Method and hard limitation

Entry-price semantics and a 100-oz multiplier are used only as a working approximation to infer an exit price from P&L. Broker-side rounding, fees, spreads and the 0.03-lot parity anomaly prevent treating this as exact. Candidate paths use the non-broker bid-only M1 proxy, so predicted timestamps are minute-end approximations and prices are reference values.

Six exit families were evaluated in five expanding chronological folds: median time, fixed price barriers, ATR-scaled barriers, EMA9 failure, VWAP failure and short-term momentum failure. Barrier parameters are learned from prior trades only.

| candidate | median_time_error | median_price_error | within_5m | outcome_match |
| --- | --- | --- | --- | --- |
| atr_barriers | 386 | 2.554 | 0.4509 | 0.6945 |
| ema9_failure | 417 | 2.382 | 0.4255 | 0.7527 |
| fixed_barriers | 240 | 1.66 | 0.5345 | 0.7673 |
| median_time_stop | 276 | 1.608 | 0.4836 | 0.8582 |
| momentum_failure | 345 | 2.275 | 0.4764 | 0.7709 |
| vwap_failure | 1089 | 4.425 | 0.2436 | 0.68 |

The best time-match candidate under the declared ordering is **fixed_barriers**, with mean five-minute close match 53.45% and median absolute time error 240 seconds. This is insufficient to identify the original exit mechanism.

Observed winner/loser holding asymmetry still supports different favorable/adverse management behavior. It does not distinguish a stop, target, trailing, reversal, momentum-failure, bar-close or hybrid state machine.
