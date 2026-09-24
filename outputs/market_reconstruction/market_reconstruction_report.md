# Exploratory external-market comparison

## Result

This is a sensitivity analysis, not a broker-feed reconstruction. It joins the 423 executed XAUUSD.f records to a Dukascopy **bid-only** M1 reference series after an assumed UTC+3 timestamp shift. All 423 entries can be assigned a nearby reference bar with a median timestamp lag of 30.0 seconds. That is a feasibility check, not proof of the account's server timezone, price feed, observed-price field semantics, or execution price.

The chronological entry-detection experiment does **not** reproduce the account's entries: across five walk-forward folds, mean ROC AUC is 0.511, mean precision is 0.0000, and mean lift is 0.00x against a 0.0010 base entry rate. The fitted shallow trees returned no predicted test entries. Consequently, this analysis supplies **no support** for a volatility-breakout, indicator, or other rule family.

## Reference data and limits

* Source: Dukascopy historical XAUUSD bid prices, aggregated to one-minute OHLC.
* The account's broker, bid/ask spread, server timezone, contract specification, ticks, exit prices, and order modifications remain unavailable.
* A single price falling inside a reference candle is not sufficient to authenticate a feed or a time shift. The reference series has recorded gaps and cannot recreate every path.
* The supplied result field has unknown currency/cost semantics; it is not a return or account-level profitability measure.

## Reference-feed excursion summary

The following values are extrema of the **external M1 bid reference path** over each reported trade interval, calculated from the TSV's unverified observed-price field. They are expressed using the script's conventional price-unit conversion and must not be interpreted as realized MFE/MAE, stop-loss distances, take-profit distances, or risk/reward.

| Diagnostic reference-path summary | Median | 75th percentile | 90th percentile |
| --- | ---: | ---: | ---: |
| Loss-side adverse excursion | +32.9 converted price units | +49.6 | +80.3 |
| Winner-side favorable excursion | 62.8 converted price units | 86.4 | 114.4 |
| Ratio of these two selected medians | 1.91 | — | — |

## What the model comparison says

The candidate panel contains 402,401 M1 reference observations. In-sample feature differences, including candle-body measures, are vulnerable to time-level confounding because the price level and market conditions drift over the year. The time-ordered results are the decisive check and are near chance. Tree thresholds and in-sample feature rankings are retained in the tables as failed exploratory experiments, not as candidate trading rules.

## Next required evidence

To test entry or exit hypotheses, obtain broker-specific bid/ask ticks or M1 bars, the server timezone, complete order/deal/position history, actual entry and exit prices, spreads/commissions/swaps, SL/TP values and modifications, and no-trade opportunity labels. Re-run the comparison only after that provenance is verified.

*Generated automatically from the exploratory reference-feed pipeline.*
