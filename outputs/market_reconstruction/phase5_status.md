# Phase 5 status

1. **Canonical ground truth:** 423 trades; 214 Buy / 209 Sell; 367 profitable / 56 losing; +1451.22 P&L; 401×0.01, 21×0.02, 1×0.03; three later entries began while a prior trade was active. The Phase 5 raw-ledger recheck corrects the earlier narrative count of five.
2. **Observable information:** completed external bid-only M1 OHLCV-derived features, raw-clock features, and prior ledger/account-state proxies.
3. **Provably unavailable locally:** broker-native ticks, Ask/spread, order/deal/position lifecycle, modifications, rejected/cancelled orders, and broker-server timing.
4. **Nearest non-trade alternatives:** 2538 hierarchical matched rows cover 423 tickets; no observable equality can rule out a hidden order, quote or state difference.
5. **OOS feature families:** see the predeclared ablation results below; none is labelled a reconstruction without matched acceptance.
6. **Symbolic regression:** constrained eight-expression candidate generation found no compact stable rule that passed the combined acceptance test.
7. **Exact trade moments:** no candidate reproduces a substantial fraction of exact second-level trade moments; the observable panel has 420 distinct M1 entry minutes for 423 trades.
8. **Matched near-miss testing:** no candidate met the predeclared matched-control acceptance test after BH correction.
9. **Direction:** remains unidentified within the observable opportunity-minute set.
10. **Sizing:** remains unidentified; only 22 above-minimum-size observations and critical account inputs are missing.
11. **Exits:** NOT_IDENTIFIABLE_FROM_M1.
12. **Regime specificity:** no reconstruction-level candidate exists to claim cross-regime stability.
13. **Hypotheses tested:** 5 full-feature baselines + 10 L1 ablations + 8 predeclared symbolic predicates + 4 controlled sequences.
14. **Multiple testing:** BH was applied to the eight symbolic enrichment tests and separately to eight matched tests; no candidate met the combined acceptance rule.
15. **Mathematically unidentifiable:** the original policy among infinitely many compatible computable policies, exact intrabar trigger, true opportunity set and lifecycle.
16. **Highest-value additional data:** a synchronized native terminal/account archive containing Bid/Ask ticks plus Orders, Deals, Positions and Journal lifecycle for XAUUSD.f.

## Top ablation summaries

| family | signals | trades_captured | false_alarms | mean_fold_f1 | mean_fold_pr_auc | mean_fold_precision |
| --- | --- | --- | --- | --- | --- | --- |
| F_ACCOUNT_STATE | 150 | 2 | 148 | 0.008867 | 0.003189 | 0.009697 |
| I_MARKET_STATE | 150 | 2 | 148 | 0.008867 | 0.003189 | 0.009697 |
| H_CLOCK_STATE | 89 | 1 | 88 | 0.005263 | 0.003771 | 0.005714 |

**Final level: LEVEL D — UNIDENTIFIED.** Statistical association, prediction, and a compact observable predicate are not treated as causal reconstruction.
