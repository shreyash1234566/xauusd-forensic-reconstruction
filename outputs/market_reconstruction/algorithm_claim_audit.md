# Algorithm claim audit

Every headline claim is graded using exactly one allowed label.

| Claim | Grade | Evidence | Limit |
| --- | --- | --- | --- |
| price = entry price | PLAUSIBLE HYPOTHESIS | Adjacent-pair test n=17; 100x median discrepancy 1.060. | Exact field metadata and broker deal records absent. |
| 100-oz multiplier | PLAUSIBLE HYPOTHESIS | Best multiplier on tested grid: 100. | Grid-limited; one parity anomaly; fees/rounding unknown. |
| broker timezone | UNIDENTIFIABLE | UTC+3 provides a useful alignment. | No server metadata or DST rule. |
| Dukascopy feed equivalence | INVALID/OVERSTATED | External series is bid-only aggregated M1. | No broker-feed identity evidence. |
| round-minute trigger | PLAUSIBLE HYPOTHESIS | Same-date/hour permutation detects clustering for some boundaries. | Clustering does not establish causation or timer logic. |
| session filter | PLAUSIBLE HYPOTHESIS | Raw-clock concentration and MODEL 0 diagnostics. | Timezone and opportunity set remain proxy-defined. |
| higher-timeframe context | PLAUSIBLE HYPOTHESIS | MODEL 5 OOS PR AUC 0.00261 vs MODEL 1 0.00176. | Feature association is not source-code identity. |
| M1 impulse trigger | PLAUSIBLE HYPOTHESIS | MODEL 1 OOS F1 0.00168; recall 0.04248. | Prior simple rules fail exact replication. |
| EMA 9/20 | INVALID/OVERSTATED | EMA spread is one correlated feature. | No replication evidence that source code uses these periods. |
| VWAP | INVALID/OVERSTATED | VWAP-distance is one proxy feature. | Vendor volume is a proxy and source-code usage is unproven. |
| breakout/liquidity break | UNIDENTIFIABLE | Breakout-distance features tested. | M1 OHLC cannot identify order-flow liquidity events. |
| 31.9-pip SL | INVALID/OVERSTATED | Value is an external-reference path excursion. | Excursion is not an order level. |
| 62.8-pip TP | INVALID/OVERSTATED | Value is an external-reference path excursion. | Excursion is not an order level. |
| dynamic exit | PLAUSIBLE HYPOTHESIS | Winner/loser duration asymmetry is statistically strong. | Many exit mechanisms generate the same asymmetry. |
| sizing based on conviction | INVALID/OVERSTATED | Segment A/B large-lot rates 0.179/0.015. | Regime/namespace change is the leading observed explanation. |
| multiple algorithms | UNIDENTIFIABLE | Mixtures/HMMs describe heterogeneous states. | Components do not map to persistent executable rules. |
| adaptive regimes | PLAUSIBLE HYPOTHESIS | Multiple trade-attribute change points are robust. | Market regime or infrastructure changes are alternatives. |
| exact algorithm identification | UNIDENTIFIABLE | Best OOS model is MODEL 0 time/session with precision 0.00311, recall 0.21895. | Replication is insufficient and M1 lacks intraminute path/broker execution. |

## Statistical-test register

| Test | Null hypothesis | Sample size | Method | Effect size | p-value | Multiple-testing treatment | Limitations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Entry-price/100x paired continuity | 100x inferred exits are not closer than recorded-price-as-exit | 17 | paired Wilcoxon, one-sided | median discrepancy=1.060 | 0.05444 | single prespecified comparison; multiplier grid descriptive | gap movement and costs |
| Ticket monotonicity | ticket IDs unrelated to chronological rank | 423 | Kendall tau | tau=0.990544 | 2.025e-203 | not part of a searched family | namespace meaning unknown |
| Round-minute boundaries | entries exchangeable with eligible same-date/hour M1 bars | 423 | Monte Carlo permutation | observed minus null shares in CSV | 0.0002 | BH across 5/15/30/60-minute family | raw hour and proxy eligibility |
| Sizing univariates | pre-trade predictor independent of lot>0.01 | 423 | Fisher or Mann-Whitney + permutation | effect sizes in CSV | 2.742e-08 | BH within declared P10 univariate family | 22 positives; regime concentration |
| Entry models | pre-entry features do not discriminate entry bars | 420 | five expanding chronological folds | best PR AUC=0.00249 | n.a. | nine prespecified architectures; no p-value promotion | extreme imbalance; feed/time proxy |
| Exit candidates | candidate does not improve time/price matching | 423 | five expanding chronological folds | best 5m match=0.5345 | n.a. | six declared families; descriptive selection | inferred exit price and M1 timing |

P-values quantify compatibility with a stated null under its assumptions. They do not prove a source-code mechanism, broker identity, causality, or uniqueness.
