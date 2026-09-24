# Phase 2 identification status

## LEVEL D — UNIDENTIFIED

Phase 2 adds completed-bar event geometry, matched nearby non-trades, observed-history cooldown state and sparse chronological eligibility models. The best Phase 2 aggregate candidate is **E2 events + eligibility state** with OOS precision 0.00447, recall 0.03268, mean F1 0.00851, mean PR AUC 0.00325, and 2,236 OOS candidate signals. This does not reproduce the historical event stream with the selectivity required for Level C, B or A.

## Learned

Measured event geometry and raw-clock boundaries can be compared against similar nearby non-trades instead of treating every M1 minute as equally comparable. In this declared matched family, raw-clock 30- and 60-minute boundaries remain enriched after BH adjustment (q≈0.0105); no completed-bar geometry feature survives the same adjustment. The analysis also quantifies how much apparent selection remains after conditioning on observed position capacity and cooldown history.

## Falsified or limited

No tested single completed-bar event, small proxy-state machine or constrained sparse rule explains why the system chose only these specific entries. A generic M1 completed-bar event is not sufficient when similar matched moments commonly receive no trade. The boundary enrichment is consistent with a timer/bar/session layer, but cannot tell these mechanisms apart or establish it as a sufficient trigger.

## Still unknown and data needed

Broker tick bid/ask, spread, server-time metadata, actual order/deal lifecycle, rejected/cancelled orders, stop/target modifications, EA logs and account state would be needed to distinguish an intrabar trigger, timer, microstructure gate, hidden cooldown, execution filter or unobserved strategy state. The M1 proxy cannot resolve those alternatives.
