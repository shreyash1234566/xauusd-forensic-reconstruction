# Phase 3 event-sequence analysis

The search vocabulary is deliberately small: H1, M30, M15, multi-event armed proxy, event, cooldown and other. Contiguous pre-entry sequences of lengths 2–5 are compared with clock-phase-matched controls. Search space is constrained to this vocabulary and four lengths; Benjamini–Hochberg adjustment is applied across retained sequence tests.

| length | sequence | trade_count | control_count | rate_difference | fisher_p | bh_q |
| --- | --- | --- | --- | --- | --- | --- |
| 3 | EVENT>OTHER>ARM | 12 | 1 | 0.026005 | 0.003197 | 0.58505 |
| 2 | OTHER>ARM | 36 | 18 | 0.042553 | 0.016096 | 0.73637 |
| 4 | EVENT>EVENT>EVENT>OTHER | 0 | 7 | -0.016548 | 0.015239 | 0.73637 |
| 5 | OTHER>EVENT>EVENT>EVENT>OTHER | 0 | 7 | -0.016548 | 0.015239 | 0.73637 |
| 2 | ARM>ARM | 35 | 23 | 0.028369 | 0.1339 | 1 |
| 3 | ARM>ARM>ARM | 14 | 4 | 0.023641 | 0.02916 | 1 |
| 3 | OTHER>OTHER>ARM | 18 | 12 | 0.014184 | 0.35286 | 1 |
| 4 | EVENT>OTHER>EVENT>OTHER | 9 | 3 | 0.014184 | 0.14313 | 1 |
| 3 | OTHER>EVENT>OTHER | 21 | 16 | 0.01182 | 0.50181 | 1 |
| 2 | EVENT>M30 | 6 | 1 | 0.01182 | 0.12345 | 1 |
| 4 | OTHER>ARM>ARM>ARM | 5 | 0 | 0.01182 | 0.061762 | 1 |
| 2 | COOLDOWN>COOLDOWN | 4 | 0 | 0.0094563 | 0.12411 | 1 |
| 3 | EVENT>ARM>ARM | 8 | 4 | 0.0094563 | 0.38424 | 1 |
| 3 | EVENT>EVENT>ARM | 5 | 1 | 0.0094563 | 0.21708 | 1 |
| 3 | M30>EVENT>OTHER | 4 | 0 | 0.0094563 | 0.12411 | 1 |
| 3 | OTHER>ARM>EVENT | 10 | 6 | 0.0094563 | 0.45012 | 1 |
| 4 | ARM>ARM>ARM>ARM | 6 | 2 | 0.0094563 | 0.28673 | 1 |
| 4 | ARM>EVENT>OTHER>ARM | 4 | 0 | 0.0094563 | 0.12411 | 1 |
| 4 | EVENT>EVENT>OTHER>ARM | 4 | 0 | 0.0094563 | 0.12411 | 1 |
| 4 | OTHER>OTHER>OTHER>ARM | 12 | 8 | 0.0094563 | 0.49826 | 1 |

No sequence is promoted to source logic without a frozen chronological replication result.
