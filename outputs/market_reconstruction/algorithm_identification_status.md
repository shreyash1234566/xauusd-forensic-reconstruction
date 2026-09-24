# Algorithm identification status

## LEVEL D — UNIDENTIFIED

The actual original algorithm has **not** been identified. The strongest tested entry architecture is `MODEL 0 time/session`, but its OOS event precision is 0.00311, recall is 0.21895, and mean one-M1-bar match rate is 0.224. The best declared exit family matches closes within five minutes at 53.45%. This is not sufficient for Level B or Level A.

## Directly known

The file contains 423 XAUUSD.f closed intervals, 214 Buy and 209 Sell, mostly 0.01 size, with strong outcome-conditioned holding-time asymmetry and an operational ticket/size discontinuity. The copied raw file is unchanged.

## What the Claude ledger adds

It supplies independently developed hypotheses and checks for price semantics, ticket chronology, timing boundaries, payoff nulls, sizing, and behavioral regimes. Independent checks here support the entry-price/approximately-100-oz working interpretation and ticket discontinuity, while retaining the stated accounting caveat.

## What the external-market work adds

It permits pre-entry market-state and negative-space comparison. M1 impulse/expansion, clock, trend/location and completed HTF state have measurable associations, but none of the nine architectures replicates the event stream out of sample.

## Claims that do not survive

Dukascopy broker-feed equivalence, a proven UTC+3 broker timezone, exact EMA/VWAP source rules, a definitive breakout/liquidity algorithm, 31.9-pip SL, 62.8-pip TP, conviction sizing, and a specific number of algorithms are unsupported or overstated.

## Strongest current structural hypothesis

A timing/state gate followed by expansion/impulse and market-location filtering, with quicker adverse-trade handling and longer favorable-trade management. This is a hypothesis class, not the source algorithm.

## Historical and OOS match

The strongest candidate emits 7862 historical signals and matches 34 entry bars in-sample (recall 0.081). In chronological OOS evaluation it records TP=67, FP=21485, FN=239, precision 0.00311, and recall 0.21895.

## Remaining identification barriers

Broker-specific bid/ask ticks, exact server timezone, actual exit prices, order/deal/position linkage, stops/targets and modifications, costs, rejected/cancelled orders, account state, EA identifiers and the true opportunity set remain absent. M1 bars cannot resolve second-level intrabar triggers. The present result is a statistical approximation and falsification exercise, not source-code recovery.
