# Phase 3 status

## LEVEL D — UNIDENTIFIED

Phase 3 retains the Phase 2 result that M30/H1 raw-clock boundaries are statistically enriched opportunity markers in the M1 proxy, but not sufficient trigger rules. The immediate-boundary versus post-120-second-window comparison does not identify whether the mechanism is a bar close, fixed timer, or a wider eligibility window because all share the same observable clock basis and lack tick/order data.

The strongest Phase 3 replication candidate is **H1 M30 boundary / bar-close proxy**: OOS precision 0.00383, recall 0.09477, F1 0.00734. This is not close to reconstructing 423 selected events.

What was learned: clock timing adds structure; flat-only eligibility is falsified; M30-phase matched controls still fail to reveal a single deterministic state/event condition.

What remains unknown: intrabar price crossing, exact timer scheduling, broker spread/ask, unrecorded order decisions, EA/account state and true market opportunity set. Tick bid/ask plus broker order/deal/position logs would resolve the highest-value ambiguities.
