# CTPI exit investigation

## Decision

No tested market-state exit feature survives the chronological lockbox gate beyond age and calendar.

Entry discovery remains frozen. This analysis does not reuse the entry lockbox for a new entry search.

## Design

- Canonical trades: 423
- Raw-tick-complete trades: 394
- Discovery/lockbox trades: 296 / 98
- Lockbox starts: 2026-06-09T16:44:30+00:00
- Causal risk-set interval: 15 seconds
- Baseline: flexible holding age, side, UTC time of day, and weekday.
- Candidate state: executable move, MFE, MAE, peak retracement, short momentum, volatility, spread, and tick rate.
- Positive gate: incremental lockbox information above zero and Holm-adjusted sign-flip p < 0.05.

## Lockbox results

| model | bits per exit vs baseline | Holm p | gate | standardized coefficient |
| --- | ---: | ---: | --- | ---: |
| unrealized_move | -0.0154 | 1 | FAIL | -0.0527 |
| mfe | -0.0066 | 1 | FAIL | -0.0390 |
| mae | 0.0212 | 0.5832 | FAIL | 0.0777 |
| drawdown_from_mfe | -0.0026 | 1 | FAIL | 0.0023 |
| momentum_30s | -0.0018 | 1 | FAIL | 0.0065 |
| momentum_120s | 0.0001 | 0.4936 | FAIL | -0.0006 |
| volatility_120s | 0.0170 | 0.5832 | FAIL | 0.0973 |
| spread | 0.0035 | 1 | FAIL | 0.0494 |
| tick_rate_15s | 0.0274 | 0.2405 | FAIL | 0.0913 |
| combined_market_state | 0.0338 | 0.5832 | FAIL | n.a. |

Surviving predeclared models: none.

## Absolute goodness of fit

The combined model time-rescaling gate is **FAIL** (KS p=0.0003034).

A market-state association is only a partial exit component. A complete exit mechanism also needs absolute calibration and deterministic sequential replay. Public ticks cannot establish broker-side stop/target modifications or the unique original source code.

## Evidence exclusions

The old `phase8c_exit_falsification.py` candidate table is excluded because several candidate rows are literal hard-coded numbers rather than computed results. The older M1 walk-forward table remains historical descriptive evidence, not this confirmatory raw-tick test.

## Mathematical interpretation

For each open trade and interval, the model estimates `P(exit in the next interval | still open, age, calendar, market state)`. The reported bits are `(LL_state - LL_baseline)/(N_exits ln 2)` on the untouched chronological lockbox. Therefore a positive value measures exit-timing information beyond the age/session clock; it does not by itself prove a deterministic rule.
