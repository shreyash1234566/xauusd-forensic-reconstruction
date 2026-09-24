# Phase 5 canonical recheck

| trade_rows | buy | sell | profitable | losing | total_pnl | lot_counts | overlapping_entries | source_sha256 | distinct_entry_minutes | raw_base_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 423 | 214 | 209 | 367 | 56 | 1451.22 | {'0.01': 401, '0.02': 21, '0.03': 1} | 3 | 3B22B24C5F7BEB2118FFEC613640A9AB1472C3D04E4503229D00771277E4B6BD | 420 | 0.00105119023064058 |

The raw ledger is canonical. Its strict timestamp recheck finds three later entries that began while an earlier trade was still open, correcting the earlier narrative count of five. This still falsifies a universal flat-only rule. The 423 second-level entries collapse to 420 distinct M1 candidate minutes solely because of M1 aggregation.
