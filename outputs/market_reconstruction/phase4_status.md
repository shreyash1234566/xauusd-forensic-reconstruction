# Phase 4 status

## Result

**LEVEL D — UNIDENTIFIED (unchanged).** Phase 4 completed the targeted broader local recovery audit and entered the formal data-limited branch. No additional modeling was run.

## Required answers

1. **Was higher-resolution data recovered?** No. Only external M1 OHLCV was available.
2. **Was Bid/Ask/spread recovered?** No. The available series is bid-only M1 and has no Ask or spread.
3. **Were order/deal/position records recovered?** No.
4. **Can the exact entry trigger be localized to seconds or ticks?** No.
5. **Can M30/H1 boundary timing be distinguished from a broader opportunity window?** No; M1 cannot distinguish exact bar-close, timer, or eligibility window.
6. **Can the directional rule be reconstructed?** No.
7. **Can the exit mechanism be reconstructed?** No.
8. **Can the sizing mechanism be reconstructed?** No.
9. **What explains the nearest non-trade moments?** No observable causal discriminator was recovered; an unobserved order, quote/spread condition, or hidden state may differ.
10. **What is still fundamentally unidentifiable?** The quote path, execution method, true opportunity set, lifecycle, hidden eligibility state, direction, exits and pre-trade sizing inputs.
11. **Did the project move beyond Level D?** No. Promotion is prevented by the absence of synchronized broker Bid/Ask ticks and complete order/deal/position lifecycle data; the M1 proxy cannot expose those missing decision boundaries.

## Baseline retained

- 423 trades: 214 Buy / 209 Sell; 367 winners / 56 losers; total P&L +1451.22.
- Sizes: 401 x 0.01, 21 x 0.02, 1 x 0.03.
- Five observed entries overlapped a prior active position.
- Phase 3 M30/H1 enrichment remains a constraint, not a reconstructed rule: best boundary proxy had 29/306 OOS entry bars, 7,573 signals, 0.383% precision, 9.48% recall and F1 0.00734.
- Clock-plus-state models performed worse; no corrected small event/state separator and no direction reconstruction were established.
