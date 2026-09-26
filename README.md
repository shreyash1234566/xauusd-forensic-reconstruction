# Reverse-trade forensic research project

This project produces an evidence-graded behavioral fingerprint from a supplied
headerless trade-history TSV. It does not claim to recover source code or a
specific entry/exit strategy from selected closed trades alone.

## Deliverables

- `outputs/01a0bada-7e73-77c0-9b06-15db62fdf55d/reverse_engineering_report.md` — the complete A–T research report.
- `outputs/01a0bada-7e73-77c0-9b06-15db62fdf55d/tables/` — proof log, hypothesis register, statistical tests, candidate ranking and reproducible intermediate tables.
- `outputs/01a0bada-7e73-77c0-9b06-15db62fdf55d/reverse_trade_analysis.xlsx` — spreadsheet handoff with formulas and charts.
- `outputs/market_reconstruction/market_reconstruction_report.md` — clearly labelled exploratory comparison to a non-broker M1 reference feed; it does not identify the strategy.
- `outputs/market_reconstruction/algorithm_identification_status.md` — final continuation verdict and evidence boundary.
- `outputs/market_reconstruction/algorithm_claim_audit.md` — claim-by-claim grading of the imported P1–P9b findings and the completed P10 work.
- `outputs/market_reconstruction/candidate_event_table.csv.gz` — leakage-safe M1 opportunity panel with completed M5/M15/H1 context.
- `outputs/market_reconstruction/entry_match_table.csv` and `exit_match_table.csv` — per-trade historical/OOS replication results.

## Reproduce the trade-history analysis

From the project root, activate the local environment and run:

```powershell
.\.venv\Scripts\python.exe -m reverse_trade.pipeline --input data\raw\trades_raw.tsv --output outputs\01a0bada-7e73-77c0-9b06-15db62fdf55d
.\.venv\Scripts\python.exe -m reverse_trade.report --output outputs\01a0bada-7e73-77c0-9b06-15db62fdf55d --project-root .
.\.venv\Scripts\python.exe -m pytest
```

To rerun the continuation analysis and its independent validation:

```powershell
.\.venv\Scripts\python.exe scripts\continue_identification.py
.\.venv\Scripts\python.exe scripts\validate_continuation.py
```

The copied raw input is retained unchanged in `data/raw/trades_raw.tsv`.
The data requirements needed to test actual entry and exit rules are in
`docs/data_requirements.md`.

## Algorithm Reconstruction Framework (Stages A through Z)

The permanent scientific methodology is now
`docs/CTPI_METHODOLOGY.md`. The active, right-sized next sequence is
`docs/CTPI_IMMEDIATE_EXECUTION_PLAN.md`. CTPI governs evidentiary claims and the
five permitted identifiability outcomes; the six-step plan governs immediate
execution. The A-to-Z plan below remains the detailed engineering reference.

Run the immediate CTPI sequence with:

```powershell
.\.venv\Scripts\python.exe scripts\ctpi_immediate_execution.py
```

Its reconciled evidence, raw-tick same-clock placebo, targeted planted recovery,
completed-bar direction placebo, availability diagnostic and five-outcome verdict are written under
`outputs/ctpi_immediate/`.

After freezing that evidence base, run the bounded sample-size power curve and
validated-component replay audit with:

```powershell
.\.venv\Scripts\python.exe scripts\ctpi_next_tracks.py
```

Those outputs are written under `outputs/ctpi_next_tracks/`.

The implementation plan is documented in
`docs/ALGORITHM_RECONSTRUCTION_IMPLEMENTATION_PLAN_V1.md`. Stages A-F lock the
423-record ledger and Phase 7C evidence, acquire a separate full-span Dukascopy
tick stream, and validate/hash both sources. The 2,032-file original archive
under `data/market/raw_ticks/` and the Phase 7C reconciliation are preserved.
The two feeds must not be blended. Run the saved full-public workflow with:

```powershell
.\.venv\Scripts\python.exe -m reverse_trade.reconstruction.cli run --output outputs\reconstruction_v1\run_20260924_full_public --supplemental-ticks-dir data\market\supplemental_raw_ticks\dukascopy_full_20260924
```

This executes A-F and records G-M and N-Z as blocked. A complete public market
file inventory does not reveal the account's active/eligible periods or prove
continuous observation, so it is not a complete point-process risk set.

The later audited workflow has now executed through the final identifiability
gate. The authoritative result is
`outputs/reconstruction_v1/run_20260924_final/FINAL_RECONSTRUCTION_REPORT.md`:
the hidden policy remains unidentified. Of 420 canonical entry epochs, 299 have
the frozen causal feature support. A UTC split near 14:00 gained information in
all four outer folds but earned only 31.08 bits against a 64-bit description
cost, so it was rejected by MDL. Direction and exits were not identified.
No executable reconstructed strategy is exported.

Run the staged evidence and coverage audit:

```powershell
.\.venv\Scripts\python.exe -m reverse_trade.reconstruction.cli run --output outputs\reconstruction_v1\run_20260924
```

Earlier outputs under `outputs/reconstruction_v1/{baselines,benchmark,search,evaluate}`
were produced by a prototype using fabricated market features or candidate
timestamps copied from the trade list. They are invalid as strategy evidence.
The runner records blocked stages explicitly and does not substitute M1
interpolation or synthetic quotes for either genuine raw-tick source.
