# Phase 3 hidden-state and capacity analysis

State features are built before each candidate minute: prior entry/exit timing, prior completed result/direction/size, active-position count, trade density, recent completed event count and raw-clock history. No current-trade PnL, close, MFE or MAE is supplied to entry models.

Observed entries are compatible with a maximum active-position count of one: five entry bars occur with one position already active, and none require more than one. This falsifies a universal flat-only state machine, but does not identify the account's actual concurrency rule.

The sparse score tests a small clock + state + location set only in expanding chronological folds. Its results appear in `phase3_replication_results.csv`; non-replication is not reinterpreted as a recovered hidden state.
