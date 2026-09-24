# Claude evidence ledger and independent checks

## Scope

The pasted Claude brief reports P1–P9b as completed and P10 as interrupted. No Claude scripts or raw P1–P9b output files were present in the current workspace, so the claims below are imported as a research ledger and cross-checked where the preserved files permit. They are not silently treated as primary artifacts.

## Workspace reuse inventory

| Artifact | Present | Reuse |
| --- | --- | --- |
| Raw trades | True | data/raw/trades_raw.tsv; 423 preserved rows |
| Processed trades | True | existing trade-only outputs retained |
| Claude scripts/results | False | pasted P1–P9b claims imported as ledger; P10 newly completed |
| External XAUUSD | True | 402,401 Dukascopy bid M1 proxy rows |
| M1 entry features | True | prior aligned table retained; new leakage-safe full panel built |
| M5/M15/H1 tables | False | new completed-bar features generated |
| No-trade panel | True | prior in-memory pipeline concept rebuilt and persisted with lagged features |
| Rule sweep/tree/OOS | True | prior failed OOS result retained as baseline |
| MFE/MAE | True | retained as external-reference excursions only |
| Reports/charts | True | existing reports preserved; required continuation reports added |

## Imported findings and current disposition

| Finding | Claude result | Independent disposition |
| --- | --- | --- |
| Price/P&L semantics | Price behaves as entry; about 100 oz/lot | **PLAUSIBLE HYPOTHESIS**. Under the preregistered adjacent-pair definition here, multiplier 100 median discrepancy is 1.060; best grid multiplier is 100. The isolated ticket 36227388 remains incompatible with an exact 2-decimal/no-cost formula. |
| Ticket sequence | No inversions; large 2025-12-29 namespace jump | **DIRECTLY OBSERVED**: 1/422 adjacent inversions, Kendall tau 0.990544; largest jump 43,149,339 at 2025-12-29. The single inversion is the preserved leading-zero ticket `00983845`, so the pasted zero-inversion claim is not literally reproduced. |
| Direction | No simple first-order dependence | Retained from verified trade-only analysis: LR p≈0.625 and runs test null. |
| Holding-time asymmetry | Winners held longer | Retained: median 8.27 vs 2.93 minutes; permutation and rank tests strongly reject equal distributions. Mechanism remains unidentified. |
| Round-minute structure | Nominal clustering | Re-tested against eligible M1 bars from the same raw date and hour; see `round_minute_tests.csv`. This is a timing clue, not a proven trigger. |
| Timezone/DST | Unresolved | Retained as **UNIDENTIFIABLE** from current data. UTC+3 is an assumed proxy mapping only. |
| Driftless two-barrier null | Rejected | Valid only as rejection of a stylized null; no exit mechanism follows. |
| Fixed target | Single invariant target unsupported | Retained with the narrower wording “not supported.” |
| Lot size | 22/22 larger-lot rows positive | P10 completed using pre-trade variables. Size is strongly concentrated before/after the ticket boundary, so “conviction sizing” is not identified. |
| Regimes / mixtures | Heterogeneous states | Retained as behavioral heterogeneity, never as a count of algorithms. |

## Independent price-pair definition

Pairs are chronologically adjacent, non-overlapping trades where the next entry is within ten minutes of the previous close (n=17). The inferred previous exit under each multiplier is compared with the next recorded price. This check is sensitive to market movement during the gap and to the non-broker feed/accounting assumptions; it supports a working interpretation, not an exact accounting identity.
