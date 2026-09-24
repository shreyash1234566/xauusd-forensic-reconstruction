# Reconstruction v1 implementation status

Generated during the first implementation milestone on 24 September 2026.

Implemented and tested:

- Canonical evidence audit with locked 423-record and 420-epoch invariants.
- Phase 7C reconciliation loading without mutation of canonical sources.
- Fixed three-pair decision-epoch construction.
- Raw hourly tick-file coverage inventory with `observed` versus `unknown` status.
- Label-independent supplemental-acquisition planning; this creates requests only and does not download market data.
- Label-independent tick, timer, and completed-bar decision clocks.
- Causal feature helpers that require quote timestamps before a decision boundary.
- A compact serializable policy grammar for thresholds, conjunctions, size, cooldown, time exits, and price-distance exits.
- Deterministic replay using candidate-generated position state and bid/ask fill conventions.
- Maximum-cardinality, one-to-one entry matching.
- Finite first-tier threshold enumeration, chronological-fold helpers, and planted threshold fixtures.
- End-to-end planted T0 threshold recovery benchmark using the same replay, matching, and scoring paths as candidate evaluation.
- Source-indexed raw-tick loader and complete-candidate evaluation interface; they preserve unknown coverage and do not perform a real-ledger search by themselves.

Current outputs:

- `evidence/` confirms 423 canonical records and 420 decision epochs.
- `coverage/` inventories 2,032 canonical hourly files: 1,913 observed and 119 unknown/invalid-or-empty support hours. This is a raw-file coverage fact, not a claim about original EA uptime.

Not yet implemented:

- Supplemental public-tick acquisition. It needs a chosen public source and a resumable downloader; canonical data will remain untouched.
- Full-period normalized tick partitions and full opportunity panel.
- Pending orders, trailing exits, regime-state synthesis, absolute intensity fitting, and full policy search/evaluation runners.
- End-to-end planted-policy tournament and real-ledger candidate search.

The unimplemented items remain deliberately unavailable as commands. They must not be simulated with placeholder results or interpreted as completed strategy findings.
