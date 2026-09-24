# Phase 10/11 Entry-Logic Audit Report

**Date**: 2026-09-22
**Status**: ALL PASS

## Checklist

| Check | Status | Detail |
|-------|--------|--------|
| A1: open_utc is timezone-aware (UTC) | PASS | tz=UTC |
| A2: panel['dt'] is timezone-naive (UTC-valued but tz-naive) | PASS | panel dt.tz=None |
| A3: All offsets are +2h or +3h (EET/EEST) | PASS | offsets: [3.0, 3.0, 3.0, 3.0, 3.0] |
| B1: Case timestamps have sub-minute resolution (not floored to minute) | PASS | Example: 2025-09-25 16:32:56+00:00, seconds=56 |
| B2: Tick feature extraction uses second-level open_utc (not floor('1min')) | PASS | Verified by code: tickfeat10.get_window(target_ms) uses exact ms timestamp |
| C1: Panel dt is minute-resolution (correct for M1 bar controls) | PASS | Fraction with second>0: 0.0000 |
| D1: Panel is_trade=1 bars align with recon open_utc floor(min) | PASS | Recall: 1.0000 (420/420 bars) |
| D2: No busy-state inconsistency in 100 sampled bars | PASS | Inconsistencies found: 0 |
| E1: Panel dt is mostly 1-minute spaced (some gaps expected for weekends) | PASS | 99.92% 1-min steps; gaps present: True |
| E2: Same-minute bar exists in panel for sample trade | PASS | Trade open: 2025-09-25 16:32:56, floor: 2025-09-25 16:32:00, found: 1 bars |
| E3: Previous-minute bar exists in panel (required for causal M1 features) | PASS | Prev bar dt: 2025-09-25 16:31:00, found: 1 bars |
| F1: Tick window contains no ticks at or after target_ms (causal) | PASS | Max tick ms: 1758817975656, target ms: 1758817976000, diff: 344ms |
| F2: Tick window loads sufficient ticks (>10 ticks for feature coverage) | PASS | Ticks loaded: 1415 |
| G1: Average eligible controls per trade day >= 30 (broad risk set has enough) | PASS | Avg controls/day (10 dates sampled): 718.4 |
| G2: Local risk-set has >= 50 controls at same hour across different dates | PASS | Same-hour (UTC 16) controls from other dates: 17511 |
| H0: Canonical execution ledger rows | PASS | len(records)=423 |
| H1: Exactly 420 unique decision epochs | PASS | len(epochs)=420 |
| H2: Exactly three 2-record concurrent epochs | PASS | two-record epochs=3 |
| H3: Exactly three strictly-overlapping later entries | PASS | entry_while_position_active sum=3 |
| H4: Concurrent epoch minutes match known mapping | PASS | detected=['2025-09-29 05:46:00', '2025-09-30 08:20:00', '2025-10-02 12:23:00'] |
| I1: Record partition counts = 320/1/102 | PASS | counts={'buffer': 1, 'discovery': 320, 'lockbox': 102} |
| I2: No epoch crosses frozen record partition boundary | PASS | crossing_epochs=0 |
| I3: Epoch partition counts = 317/1/102 | PASS | epoch_counts={'discovery': 317, 'lockbox': 102, 'buffer': 1} |
| I4: Discovery ends strictly before lockbox begins | PASS | Last discovery=2026-06-10 05:02:18, first lockbox=2026-06-12 05:17:41 |
| J1: Discovery eligibility boundary contains exactly 320 discovery records | PASS | discovery_n=320 (expected 320) |
| J2: Discovery eligibility boundary contains zero buffer and zero lockbox records | PASS | buffer_in_boundary=0 (actual partition buffer_n=1), lockbox_in_boundary=0 (actual partition lockbox_n=102); neither partition participates in discovery eligibility |
| J3: Three partitions are mutually disjoint and cover all 423 records (discovery=320, buffer=1, lockbox=102) | PASS | pairwise_overlap=0, union=423 (expected 0 overlap, 423 union) |
| J4: Buffer record is in buffer partition and absent from discovery eligibility boundary | PASS | buffer_partition_count=1, buffer_tickets_in_discovery_boundary=0 (must be 0) |

## Critical Finding: M1 Feature Causality

**ISSUE**: When a trade opens at time T (e.g., 08:15:23), the M1 bar
labeled at floor(T, '1min') = 08:15:00 is STILL OPEN at T.
Using features (return_1, rsi_14 etc.) of this same-minute bar includes
intra-bar price information from AFTER the entry decision was made.

**REQUIRED FIX**: All M1 features for a case/control at M1-bar B must
come from bar B-1 (the previous completed minute bar).
This is implemented in phase10_11_main.py via `panel.shift(1)` alignment.

## Decision: Use Lagged M1 Features

For all models using M1 features (M2, M4):
- Join each case/control bar B to the **previous bar** B-1's features
- `X_m1 = panel.shift(1)` applied before join


## Summary
- Passes: 28
- Failures: 0