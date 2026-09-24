# Stateful eligibility and cooldown analysis

## Observed-proxy states

The following are analytical states created from observed history, not recovered EA states: `IN_TRADE` means an already-open recorded position; `COOLDOWN` means ≤5 minutes after a recorded exit; `SETUP_PROXY`/`ARMED_PROXY` are one or at least two measured completed-bar events; `WATCHING_PROXY` is the remainder. Their candidate and entry rates are:

| proxy_state | candidate_minutes | entry_bars | entry_rate_per_10k_minutes |
| --- | --- | --- | --- |
| ARMED_PROXY | 73181 | 104 | 14.211 |
| COOLDOWN | 2068 | 10 | 48.356 |
| IN_TRADE | 6322 | 5 | 7.9089 |
| SETUP_PROXY | 87359 | 109 | 12.477 |
| WATCHING_PROXY | 177766 | 192 | 10.801 |

## Cooldown exposure rates

| cooldown_bin | prior_win_code | candidate_minutes | entry_bars | entry_rate_per_10k_minutes |
| --- | --- | --- | --- | --- |
| 0-5s | 0 | 4 | 0 | 0 |
| 0-5s | 1 | 43 | 1 | 232.56 |
| 1-2m | 0 | 54 | 0 | 0 |
| 1-2m | 1 | 362 | 2 | 55.249 |
| 10-30m | 0 | 918 | 8 | 87.146 |
| 10-30m | 1 | 6982 | 3 | 4.2968 |
| 15-30s | 0 | 11 | 0 | 0 |
| 15-30s | 1 | 89 | 0 | 0 |
| 2-5m | 0 | 160 | 2 | 125 |
| 2-5m | 1 | 1074 | 4 | 37.244 |
| 30-60s | 0 | 33 | 1 | 303.03 |
| 30-60s | 1 | 174 | 0 | 0 |
| 5-10m | 0 | 260 | 1 | 38.462 |
| 5-10m | 1 | 1766 | 5 | 28.313 |
| 5-15s | 0 | 7 | 0 | 0 |
| 5-15s | 1 | 57 | 0 | 0 |
| >30m | 0 | 14142 | 43 | 30.406 |
| >30m | 1 | 314237 | 344 | 10.947 |
| nan | -1 | 1 | 1 | 10000 |

These cooldown exposure denominators use candidate minutes with no recorded active position. They test whether entry likelihood is suppressed immediately after an observed exit, but cannot determine whether a missing trade was due to an internal cooldown, a rejected order, an unrecorded eligibility rule, or absence of a tick-level setup.
