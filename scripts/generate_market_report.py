"""Generate the final markdown report for the market reconstruction phase."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "market_reconstruction"
REPORT_PATH = OUT_DIR / "market_reconstruction_report.md"


def main() -> None:
    # Load metrics
    with open(OUT_DIR / "market_reconstruction_metrics.json", "r", encoding="utf-8") as f:
        metrics = json.load(f)
    reference_excursion_ratio = metrics.get(
        "reference_excursion_ratio_median", metrics.get("implied_rr_median")
    )

    # Load the historical reference-feed excursion summary.  Earlier runs
    # called this file ``sl_tp_geometry.csv``; retain compatibility while
    # deliberately avoiding any stop/target interpretation.
    import pandas as pd
    geometry_path = OUT_DIR / "tables" / "reference_feed_excursion_summary.csv"
    if not geometry_path.exists():
        geometry_path = OUT_DIR / "tables" / "sl_tp_geometry.csv"
    geometry_df = pd.read_csv(geometry_path)
    geo = dict(zip(geometry_df["metric"], geometry_df["value"]))

    # Read tree rules
    tree_rules = (OUT_DIR / "decision_tree_rules.txt").read_text(encoding="utf-8")
    dir_rules = (OUT_DIR / "direction_tree_rules.txt").read_text(encoding="utf-8")

    md = f"""# Exploratory external-market comparison

## Result

This is a sensitivity analysis, not a broker-feed reconstruction. It joins the 423 executed XAUUSD.f records to a Dukascopy **bid-only** M1 reference series after an assumed UTC+3 timestamp shift. All {metrics['trades']} entries can be assigned a nearby reference bar with a median timestamp lag of {metrics['median_lag_seconds']:.1f} seconds. That is a feasibility check, not proof of the account's server timezone, price feed, observed-price field semantics, or execution price.

The chronological entry-detection experiment does **not** reproduce the account's entries: across five walk-forward folds, mean ROC AUC is {metrics['wf_mean_auc']:.3f}, mean precision is {metrics['wf_mean_precision']:.4f}, and mean lift is {metrics['wf_mean_lift']:.2f}x against a {metrics['null_precision']:.4f} base entry rate. The fitted shallow trees returned no predicted test entries. Consequently, this analysis supplies **no support** for a volatility-breakout, indicator, or other rule family.

## Reference data and limits

* Source: Dukascopy historical XAUUSD bid prices, aggregated to one-minute OHLC.
* The account's broker, bid/ask spread, server timezone, contract specification, ticks, exit prices, and order modifications remain unavailable.
* A single price falling inside a reference candle is not sufficient to authenticate a feed or a time shift. The reference series has recorded gaps and cannot recreate every path.
* The supplied result field has unknown currency/cost semantics; it is not a return or account-level profitability measure.

## Reference-feed excursion summary

The following values are extrema of the **external M1 bid reference path** over each reported trade interval, calculated from the TSV's unverified observed-price field. They are expressed using the script's conventional price-unit conversion and must not be interpreted as realized MFE/MAE, stop-loss distances, take-profit distances, or risk/reward.

| Diagnostic reference-path summary | Median | 75th percentile | 90th percentile |
| --- | ---: | ---: | ---: |
| Loss-side adverse excursion | {geo['loss_mae_pip_median']:+.1f} converted price units | {geo['loss_mae_pip_p75']:+.1f} | {geo['loss_mae_pip_p90']:+.1f} |
| Winner-side favorable excursion | {geo['win_mfe_pip_median']:.1f} converted price units | {geo['win_mfe_pip_p75']:.1f} | {geo['win_mfe_pip_p90']:.1f} |
| Ratio of these two selected medians | {reference_excursion_ratio:.2f} | — | — |

## What the model comparison says

The candidate panel contains {metrics['panel_rows']:,} M1 reference observations. In-sample feature differences, including candle-body measures, are vulnerable to time-level confounding because the price level and market conditions drift over the year. The time-ordered results are the decisive check and are near chance. Tree thresholds and in-sample feature rankings are retained in the tables as failed exploratory experiments, not as candidate trading rules.

## Next required evidence

To test entry or exit hypotheses, obtain broker-specific bid/ask ticks or M1 bars, the server timezone, complete order/deal/position history, actual entry and exit prices, spreads/commissions/swaps, SL/TP values and modifications, and no-trade opportunity labels. Re-run the comparison only after that provenance is verified.

*Generated automatically from the exploratory reference-feed pipeline.*
"""
    REPORT_PATH.write_text(md, encoding="utf-8")
    print(f"Report saved to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
