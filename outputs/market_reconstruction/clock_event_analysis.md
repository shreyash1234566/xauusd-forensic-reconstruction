# Clock-event analysis

The table compares the observed entry-bar rate at raw-clock boundaries against all other eligible proxy minutes. Matched p-values reuse the nearby-state control design rather than a uniform-minute binomial null.

| clock_event | eligible_event_minutes | entry_bars_on_event | trade_rate_event | trade_rate_non_event | rate_ratio_event_vs_non_event | matched_permutation_p | matched_bh_q |
| --- | --- | --- | --- | --- | --- | --- | --- |
| boundary_5 | 69337 | 99 | 0.0014278 | 0.0011574 | 1.2336 | 0.71364 | 0.78932 |
| boundary_15 | 23111 | 47 | 0.0020337 | 0.0011528 | 1.7642 | 0.025987 | 0.18191 |
| boundary_30 | 11554 | 36 | 0.0031158 | 0.0011458 | 2.7192 | 0.0009995 | 0.010495 |
| boundary_60 | 5779 | 20 | 0.0034608 | 0.0011734 | 2.9495 | 0.00049975 | 0.010495 |

A rate ratio above one is compatible with bar/timer/session timing, but does not identify which of those mechanisms applied or establish broker timezone.
