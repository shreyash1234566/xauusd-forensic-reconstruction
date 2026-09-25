# Reconstruction v1 implementation status

Updated 24 September 2026 after the full public-tick acquisition and source audit.

Stages A-C lock the canonical 423-record ledger, Phase 7C reconciliation, and fixed 420-epoch mapping. Stage D inventories expected calendar hours. Stage E acquired the complete 8,580-hour span from Dukascopy into a separate supplemental archive; Stage F hashed and validated both source archives. The original raw_ticks archive and Phase 7C reconciliation remain unchanged.

The original raw-tick archive contains 2,032 named hourly files; 1,909 are nonempty and valid within the 8,580-hour ledger span. The separate Dukascopy stream contains one file for each of the 8,580 hours: 5,732 nonempty valid hours and 2,848 provider-empty hours, with no invalid or missing files. Its per-file SHA-256 and structural checks are recorded under `outputs/reconstruction_v1/run_20260924_audited/E_F/`. The two feeds must remain separate in modeling. Full account exposure still is not established: empty public hours are unknown/closed periods, nonempty file presence does not prove complete intrahour continuity, and account operation/eligibility is unavailable.

The earlier baseline, benchmark, search, and evaluation commands used fabricated market features, candidate times copied from the trade list, or metadata labels instead of measured recovery. Those outputs are invalid as strategy evidence. The current full-public run executes A-F and explicitly blocks G-M and N-Z: observation/execution assumptions, independently generated opportunities, a complete causal feature panel, validated full replay, planted recovery, model selection, and evaluation are not yet wired into an end-to-end scientific runner.

Still required before later stages can support a real reconstruction: market-session/availability assumptions; a label-independent opportunity panel and causal features; planted recovery without injecting the true policy into its candidate pool; correct multiple-position and order lifecycle replay; nested chronological selection; complete entry, direction, size, and exit evaluation; and search-adjusted placebo calibration.

Stages G-M are now implemented and executed over a label-independent quote-clock case-control design. The saved panel contains 343,598 seeded controls and all 420 cases; 299 cases and 258,765 controls have the frozen causal feature support. Stage N passes non-degenerate planted recovery for the registered in-grammar families and correctly rejects stochastic/nonlinear fixtures. Stage O and P-Q complete chronological out-of-sample modeling and symbolic search. S-T complete conditional direction, size, and exit analysis.

The authoritative final verdict is `UNIDENTIFIED_PARTIAL_BEHAVIORAL_STRUCTURE`, saved under `outputs/reconstruction_v1/run_20260924_final/`. The strongest timing rule gained 31.08 outer-test bits but cost 64 MDL bits, direction gained -0.0026 bits/trade, and exits were not identified. R was therefore not expanded, no complete U policy was assembled, and no executable reconstructed strategy was exported.

No further account data is assumed or requested. Missing account availability remains unobservable; missing market/feature support remains unknown rather than a negative label.
