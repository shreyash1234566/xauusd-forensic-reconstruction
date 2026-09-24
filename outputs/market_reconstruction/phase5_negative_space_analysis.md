# Phase 5 negative-space analysis

The hierarchy creates 2538 ticket-control rows from 423 ledger tickets. Levels A–E progressively match clock phase, session, volatility, location and momentum. Level F selects the nearest temporal neighbor satisfying the level-E constraints. Explicit fallbacks are retained. These are external-M1-proxy similarities, not proof of equal broker quotes or hidden EA state.

| control_set | fallback | rows |
| --- | --- | --- |
| A_same_clock_phase | none | 423 |
| B_clock_session | none | 423 |
| C_plus_volatility | none | 423 |
| D_plus_location | none | 423 |
| E_plus_momentum | none | 421 |
| E_plus_momentum | relaxed_to_A | 2 |
| F_nearest_temporal_neighbor | none | 421 |
| F_nearest_temporal_neighbor | relaxed_to_A | 2 |
