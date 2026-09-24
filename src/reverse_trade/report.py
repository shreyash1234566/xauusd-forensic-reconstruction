"""Build the comprehensive evidence-graded Markdown report."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


def number(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n.a."
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(numeric):
        return "n.a."
    return f"{numeric:,.{digits}f}"


def percent(value: Any, digits: int = 1) -> str:
    return f"{float(value) * 100:.{digits}f}%" if value is not None else "n.a."


def pvalue(value: Any) -> str:
    if value is None:
        return "n.a."
    numeric = float(value)
    if numeric < 0.0001:
        return f"{numeric:.2e}"
    return f"{numeric:.4f}"


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    def clean(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(clean(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(clean(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def csv_table(path: Path, columns: list[str], *, limit: int | None = None) -> str:
    frame = pd.read_csv(path)
    if limit is not None:
        frame = frame.head(limit)
    rows = [[row[column] for column in columns] for _, row in frame.iterrows()]
    return markdown_table(columns, rows)


def build_report(output_dir: Path, project_root: Path) -> Path:
    metrics = json.loads((output_dir / "analysis_metrics.json").read_text(encoding="utf-8"))
    tables = output_dir / "tables"
    summary = metrics["summary"]
    quality = metrics["data_quality"]
    direction = metrics["direction"]
    profit = metrics["profit"]
    duration = metrics["duration"]
    temporal = metrics["temporal"]
    sizing = metrics["sizing"]
    clustering = metrics["clustering"]
    latent = metrics["latent_models"]
    holding_regimes = metrics["holding_regimes"]
    walk = metrics["walk_forward_behavior"]

    fields = pd.read_csv(tables / "field_dictionary.csv")
    field_rows = [
        [row.Position, row.Working_name, row.Observed_structure, row.Certainty, row.Limitation]
        for row in fields.itertuples()
    ]
    monthly = pd.read_csv(tables / "temporal_monthly.csv")
    busiest_month = monthly.loc[monthly["trades"].idxmax()]
    tests = pd.read_csv(tables / "statistical_tests.csv")
    significant_tests = tests[tests["fdr_5pct_significant"] == True]  # noqa: E712
    gmm = pd.read_csv(tables / "gmm_model_comparison.csv")
    hmm = pd.read_csv(tables / "hmm_model_comparison.csv")
    change = pd.read_csv(tables / "change_point_tests.csv")
    phases = pd.read_csv(tables / "holding_time_phases.csv")
    overlaps = pd.read_csv(tables / "overlapping_entries.csv")
    candidates = pd.read_csv(tables / "candidate_ranking.csv")
    confidence = pd.read_csv(tables / "confidence_table.csv")
    source_matrix = pd.read_csv(project_root / "research" / "source_matrix.tsv", sep="\t")

    external_market_metrics_path = (
        project_root / "outputs" / "market_reconstruction" / "market_reconstruction_metrics.json"
    )
    if external_market_metrics_path.exists():
        external_market = json.loads(external_market_metrics_path.read_text(encoding="utf-8"))
        market_section = f"""An exploratory comparison against a Dukascopy bid-only M1 reference feed is present in this project. It requires an assumed UTC+3 timestamp shift and matches every record to a nearby bar, but this does not verify the broker feed, server timezone, bid/ask execution or the price-field semantics. More importantly, its five chronological entry-detection folds have mean ROC AUC {number(external_market['wf_mean_auc'], 3)}, mean precision {number(external_market['wf_mean_precision'], 4)} and mean lift {number(external_market['wf_mean_lift'], 2)}x. The shallow reference-feed models predicted no test entries. Therefore that experiment provides no evidence for a breakout, indicator or other entry family, and it does not loosen the identification limit.

The optional market module calculates returns, EMA, RSI, MACD, ATR, Bollinger z-score, stochastic, recent-high/low distances, wick/body features, volatility, VWAP where volume exists, entry alignment and reference-feed price-path excursions. Its output must stay exploratory until broker-specific bid/ask data and verified time semantics are supplied. See [`market_reconstruction_report.md`](../market_reconstruction/market_reconstruction_report.md)."""
    else:
        market_section = """Not run. No synchronized broker-specific ticks or OHLC were supplied, and substituting a generic XAU feed would create uncontrolled timestamp, spread and price mismatch. The project includes an optional market module that calculates returns, EMA, RSI, MACD, ATR, Bollinger z-score, stochastic, recent-high/low distances, wick/body features, volatility, VWAP where volume exists, entry alignment and price-unit MFE/MAE. It runs only when an explicitly supplied market file is used."""

    normalized = profit["normalized_to_0_01_lot"]
    block_significant = change[change["fdr_5pct_significant"] == True]  # noqa: E712
    gmm_best_row = gmm.loc[gmm["bic"].idxmin()]
    hmm_best_row = hmm.loc[hmm["bic"].idxmin()]

    report = f"""# Reverse engineering the hidden trading algorithm

## Executive conclusion

This file supports a **Level 1 behavioral fingerprint** and several cautious trade-derived subgroup findings. It does **not** identify the exact entry or exit algorithm. The strongest defensible description is a symmetric, short-horizon, mostly fixed-size gold-versus-USD trading process with episodic size changes, rare same-direction parallel entries, and a persistent outcome-conditioned holding pattern: profitable trades are held longer than losing trades. Calendar changes in holding time and raw-clock timing are real features of the exported trades, but they do not distinguish one adaptive algorithm from several algorithms or changing market conditions.

The current identification ceiling follows from the observations, not from a lack of model complexity. The TSV itself has only executed closed records. It has no synchronized broker market state, no rejected or flat decisions, no exit price, no bid/ask path, no account equity, and no broker symbol specification. Any specific RSI, EMA, breakout, trend, mean-reversion, TP, SL or trailing-stop rule would therefore be invented.

### Evidence classification

**PROVEN FROM THE FILE**

- The source has {summary['observations']} rows and exactly eight tab-delimited fields per row. Its SHA-256 is `{quality['sha256']}`.
- All rows carry `XAUUSD.f`; {summary['buy_count']} are Buy and {summary['sell_count']} are Sell.
- The apparent open interval runs from {summary['start_open']} through {summary['end_open']} across {summary['calendar_span_days_inclusive']} inclusive dates and {summary['distinct_open_dates']} active dates.
- {summary['positive_count']} result values are positive, {summary['negative_count']} are negative and none are zero. Their sum is {number(summary['total_pnl'], 2)} in unknown result/currency units.
- Size is 0.01 on 401 rows, 0.02 on 21 and 0.03 on one. Maximum observed concurrency is {summary['maximum_concurrency']}; only {summary['entries_while_active']} entries occur while another interval is active.

**STRONGLY SUPPORTED AS EXECUTED-TRADE BEHAVIOR**

- Direction is almost perfectly balanced ({percent(direction['buy_proportion'], 2)} Buy) and behaves like an IID sequence at this sample size. The IID-versus-first-order Markov likelihood-ratio test gives p={pvalue(direction['iid_vs_first_order_p_value'])}.
- Median holding time is {number(duration['median_minutes'], 2)} minutes; {percent(duration['share_closed_within_minutes']['15'])} close within 15 minutes and {percent(duration['share_closed_within_minutes']['30'])} within 30 minutes.
- Winners last longer than losses: medians {number(duration['winner_median_minutes'], 2)} versus {number(duration['loser_median_minutes'], 2)} minutes. The log-duration permutation p-value is {pvalue(duration['winner_loser_log_duration_permutation']['p_value'])}, and the geometric-mean ratio is {number(duration['winner_loser_geometric_mean_ratio'], 2)}x.
- That winner-longer relationship has the same sign in every primary holding-time phase: `{holding_regimes['winner_longer_in_every_primary_phase']}`.

**PLAUSIBLE, NOT IDENTIFIED**

- One core entry process with an adaptive time scale and a separate risk/size overlay.
- Quick invalidation of losing trades plus more permissive management of winners, such as trailing, signal-based or regime-scaled exits.
- A raw-clock filter or bar-timing effect. The timezone is unknown, so market sessions cannot be named.

**UNRESOLVED**

- One adaptive algorithm versus multiple independent algorithms.
- Automated versus manual origin of outliers.
- The causal reason for 0.02/0.03 sizing and the holding-time phases.

**IMPOSSIBLE TO IDENTIFY WITHOUT ADDITIONAL DATA**

- Exact indicator, price-action, event, entry, exit, TP/SL, MFE/MAE, risk-percent, spread, slippage, latency, feed and source-code rules.

![Overview](figures/overview.png)

## A. Data summary

{markdown_table(
        ['Measure', 'Result'],
        [
            ['Rows', summary['observations']],
            ['Physical fields per row', quality['columns']],
            ['Empty cells', quality['empty_cells']],
            ['Duplicate full rows / duplicate ticket strings', f"{quality['duplicate_full_rows']} / {quality['duplicate_ticket_values']}"],
            ['Apparent open range', f"{summary['start_open']} to {summary['end_open']}"],
            ['Active dates', summary['distinct_open_dates']],
            ['Mean trades per active date', number(summary['mean_trades_per_active_date'], 3)],
            ['Positive / negative active dates', f"{summary['positive_active_dates']} / {summary['negative_active_dates']}"],
            ['Maximum concurrency / overlapping entries', f"{summary['maximum_concurrency']} / {summary['entries_while_active']}"],
        ],
    )}

The export is strictly descending by close time. It has two apparent open-time inversions caused by overlapping intervals, so every sequence test first sorts by open time and ticket. The literal ticket `00983845` is preserved as text. It is a format/data-quality anomaly and is not silently repaired. Price display precision varies from zero to three decimal places, so tick size cannot be inferred from formatting.

### Field dictionary

{markdown_table(['Position', 'Working name', 'Observed structure', 'Certainty', 'Limitation'], field_rows)}

## B. Instrument identification

`XAUUSD.f` is, with high confidence, a broker-defined gold-versus-US-dollar symbol. The official ISO 4217 list identifies XAU as gold and USD as the US dollar, and CME classifies XAU/USD under spot precious metals. MetaTrader documents that symbol names, digits, contract size, spread and related specifications are broker-set. The `.f` suffix is therefore not evidence that this is a futures contract. An exact Pepperstone specification uses `XAUUSD.f` for “Spot Gold $”, but that is only a lead and does not establish this account's broker.

The exact legal wrapper, contract size, quote basis, tick value, trading hours, financing, profit currency and server timezone remain unresolved. Sources: [SIX ISO 4217 List One](https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-one.xml), [CME FX Product Guide](https://www.cmegroup.com/markets/fx/fx-product-guide.html), [MetaTrader 5 symbol specifications](https://www.metatrader5.com/en/terminal/help/trading/market_watch), and the [broker-specific XAUUSD.f example](https://files.pepperstone.com/legal/CYSEC/Pepperstone-Specificites-du-Compte-Risque-Limite.pdf).

Observed price-like values range from {number(pd.read_csv(project_root / 'data' / 'processed' / 'trades_enriched.csv')['observed_price'].min(), 3)} to {number(pd.read_csv(project_root / 'data' / 'processed' / 'trades_enriched.csv')['observed_price'].max(), 3)}. The column is compatible with an entry/average execution price, including near-identical prices in overlapping pairs, but the TSV cannot prove its semantics.

## C. Timeline

- First apparent open: {summary['start_open']}.
- Last apparent open: {summary['end_open']}.
- Last supplied interval closes shortly after the last open; every supplied row opens and closes on the same calendar date.
- Calendar span: {summary['calendar_span_days_inclusive']} inclusive dates, with {summary['distinct_open_dates']} active dates.
- Busiest month in the supplied interval: {busiest_month['month']} with {int(busiest_month['trades'])} trades.

## D. Trading behavior

The raw-clock entry distribution is concentrated around hours 06–16. Hour {temporal['busiest_raw_hour']:02d} contains {temporal['busiest_raw_hour_trades']} entries. The 24-bin uniform reference is rejected (p={pvalue(temporal['uniform_hour_p_value'])}); the five-minute-bin minute-of-hour reference is also non-uniform (p={pvalue(temporal['uniform_minute_bin_p_value'])}). These tests describe `P(raw clock | observed trade)`. They do not estimate `P(trade | raw clock)` because eligible no-trade times and the server timezone are absent. Weekday counts are compatible with a uniform Monday–Friday reference (p={pvalue(temporal['uniform_weekday_p_value'])}).

There are {clustering['entries_while_active']} overlap pairs. All are same direction and none is a hedge. They occur early in the sample and look like rare parallel entries or scale-ins, but deal/order lineage is needed to distinguish those explanations.

{markdown_table(
        ['Prior ticket', 'New ticket', 'Side pair', 'Entry delta (sec)', 'Common overlap (sec)', 'Sizes'],
        [
            [row.prior_ticket, row.new_ticket, f"{row.prior_side}/{row.new_side}", number(row.entry_delta_seconds, 0), number(row.common_overlap_seconds, 0), f"{row.prior_lot_size}/{row.new_lot_size}"]
            for row in overlaps.itertuples()
        ],
    )}

The observed number of same-day gaps at or below 30 minutes is {clustering['same_day_gaps_le_30_minutes']}. An IID null that preserves each day's count and the global raw-clock distribution has mean {number(clustering['empirical_clock_iid_null_mean'], 2)} and p={pvalue(clustering['empirical_clock_iid_null_p_value'])}. This is borderline, not strong evidence of event bursts, and the actual opportunity window is still unknown.

![Raw-clock patterns](figures/temporal_patterns.png)

## E. Statistical fingerprint

### Direction and sequence

{markdown_table(
        ['Metric', 'Result'],
        [
            ['Buy / Sell', f"{summary['buy_count']} / {summary['sell_count']}"],
            ['Buy share (95% Wilson CI)', f"{percent(direction['buy_proportion'], 2)} ({percent(direction['buy_proportion_ci_95'][0], 2)}–{percent(direction['buy_proportion_ci_95'][1], 2)})"],
            ['Direction entropy', f"{number(direction['entropy_bits'], 4)} bits"],
            ['Same-direction transition rate', percent(direction['same_direction_rate'], 2)],
            ['Runs-test p-value', pvalue(direction['runs_test']['p_value'])],
            ['IID vs first-order Markov p-value', pvalue(direction['iid_vs_first_order_p_value'])],
            ['First- vs second-order Markov p-value', pvalue(direction['first_vs_second_order_p_value'])],
        ],
    )}

The chronological transition counts are Buy→Buy 105, Buy→Sell 108, Sell→Buy 108 and Sell→Sell 101. BIC favors the IID direction model over first- and second-order Markov alternatives. There is no trade-only evidence for directional persistence.

![Direction transitions](figures/direction_transitions.png)

### P&L-like result

{markdown_table(
        ['Metric', 'Result'],
        [
            ['Positive / negative / zero', f"{summary['positive_count']} / {summary['negative_count']} / {summary['zero_count']}"],
            ['Positive share, Wilson 95% CI', f"{percent(summary['win_rate'], 2)} ({percent(summary['win_rate_ci_95'][0], 2)}–{percent(summary['win_rate_ci_95'][1], 2)})"],
            ['Positive share, day-cluster bootstrap 95% CI', f"{percent(summary['win_rate_day_cluster_bootstrap_ci_95'][0], 2)}–{percent(summary['win_rate_day_cluster_bootstrap_ci_95'][1], 2)}"],
            ['Total / mean / median', f"{number(summary['total_pnl'], 2)} / {number(profit['mean'], 3)} / {number(profit['median'], 3)}"],
            ['Mean day-cluster bootstrap 95% CI', f"{number(summary['mean_pnl_day_cluster_bootstrap_ci_95'][0], 3)}–{number(summary['mean_pnl_day_cluster_bootstrap_ci_95'][1], 3)}"],
            ['Minimum / maximum', f"{number(profit['minimum'], 2)} / {number(profit['maximum'], 2)}"],
            ['Average positive / average negative', f"{number(profit['average_winner'], 3)} / {number(profit['average_loser'], 3)}"],
            ['Payoff ratio / profit factor', f"{number(profit['payoff_ratio'], 3)} / {number(profit['profit_factor'], 3)}"],
            ['Longest positive / negative run', f"{profit['longest_win_streak']} / {profit['longest_loss_streak']}"],
            ['Closed-trade cumulative max drawdown', number(summary['maximum_closed_trade_drawdown'], 2)],
        ],
    )}

The drawdown above is calculated only from chronologically accumulated closed-row results. It is not account-equity drawdown and excludes open-position marks, fees if absent from the result field, deposits, withdrawals and other symbols. Buy and Sell means are almost identical after normalizing every result to a 0.01 size: {number(normalized['buy_mean'], 3)} versus {number(normalized['sell_mean'], 3)}, permutation p={pvalue(normalized['buy_sell_mean_permutation']['p_value'])}.

### Holding time and exit fingerprint

{markdown_table(
        ['Metric', 'Result'],
        [
            ['Mean / median', f"{number(duration['mean_minutes'], 2)} / {number(duration['median_minutes'], 2)} minutes"],
            ['25th / 75th percentile', f"{number(duration['quantiles_minutes']['0.25'], 2)} / {number(duration['quantiles_minutes']['0.75'], 2)} minutes"],
            ['90th / 95th / 99th percentile', f"{number(duration['quantiles_minutes']['0.9'], 2)} / {number(duration['quantiles_minutes']['0.95'], 2)} / {number(duration['quantiles_minutes']['0.99'], 2)} minutes"],
            ['Maximum', f"{number(duration['maximum_minutes'], 2)} minutes"],
            ['Winner / loser median', f"{number(duration['winner_median_minutes'], 2)} / {number(duration['loser_median_minutes'], 2)} minutes"],
            ['Duration vs size-normalized result Spearman rho', f"{number(duration['duration_normalized_pnl_spearman_rho'], 3)} (p={pvalue(duration['duration_normalized_pnl_spearman_p_value'])})"],
            ['Exact whole-minute holds observed / expected', f"{duration['whole_minute_duration_count']} / {number(duration['whole_minute_duration_expected'], 2)} (p={pvalue(duration['whole_minute_duration_binomial_p_value'])})"],
            ['Largest exact-second duration repeat count', duration['largest_exact_duration_count']],
        ],
    )}

The absence of excess whole-minute durations and the weak exact-second modes argue against a rigid whole-minute time stop. A lognormal is the best of the tested single positive-duration distributions by BIC, but no fitted distribution proves an exit rule. The longer-winner/shorter-loser pattern is consistent with quick invalidation plus winner extension; it does not distinguish trailing, signal reversal, volatility scaling or structure-based exits.

![P&L versus holding time](figures/pnl_vs_duration.png)

### Position size

Above-base size occurs on {sizing['above_base_count']} rows ({percent(sizing['above_base_share'], 2)}). Direction is unrelated to above-base size (Fisher p={pvalue(sizing['side_size_fisher_p_value'])}). Neither the previous trade's result nor the previous five-trade result separates the size groups (p={pvalue(sizing['previous_pnl_large_minus_base_permutation']['p_value'])} and {pvalue(sizing['previous_five_trade_pnl_large_minus_base_permutation']['p_value'])}). After normalizing result to 0.01, large-minus-base performance is {number(sizing['normalized_pnl_large_minus_base_permutation']['difference'], 3)} with p={pvalue(sizing['normalized_pnl_large_minus_base_permutation']['p_value'])}. All 22 above-base rows are positive, but the exchangeable-outcome probability is {pvalue(sizing['all_above_base_win_hypergeometric_probability'])} before broad search correction.

Size is time-clustered: the registered one-change scan remains significant under block permutation and FDR. This is evidence of an episodic size regime, not evidence for a second entry algorithm. Account equity is absent, so fixed-fraction or balance-step sizing cannot be tested.

## F. One-vs-multiple-system analysis

{markdown_table(
        ['Hypothesis', 'Evidence for', 'Evidence against / missing', 'Current status'],
        [
            ['H0: one adaptive strategy', 'Symmetric sides; IID directions; winner-longer exit pattern persists across holding phases', 'Behavior is nonstationary in duration, raw clock and size', 'Plausible; not proven'],
            ['H1: two strategies', 'Mixture/HMM likelihood improves with more components/states', 'Low silhouette; state count is at/near search boundary; market regimes can create the same components', 'Weak and unresolved'],
            ['H2: three or more strategies', 'BIC selects a multi-state descriptive model', 'No component has a source label; selection keeps improving with flexibility', 'Weak and unresolved'],
            ['H3: automation plus manual intervention', 'A few multivariate outliers exist', 'No manual/EA reason codes; anomalies have many alternative explanations', 'Unsupported'],
            ['H4: core strategy plus risk/execution module', 'Base size dominates; larger size is episodic; rare same-side parallel entries', 'Equity, margin, signal strength and order lineage are absent', 'Plausible'],
        ],
    )}

The GMM BIC minimum among the registered search is {number(gmm_best_row['bic'], 1)} at {int(gmm_best_row['components'])} components; the mean seed-to-seed adjusted Rand stability is {number(latent['gmm_seed_stability_adjusted_rand_mean'], 3)}. The HMM BIC minimum is {number(hmm_best_row['bic'], 1)} at {int(hmm_best_row['states'])} states. Both models summarize raw clock, log duration, size-normalized result and log entry gap. They deliberately exclude side and lot from the fitting features. Even so, low silhouettes and boundary-seeking state counts show non-Gaussian heterogeneity more clearly than a uniquely identified number of source algorithms.

Holding-time recursive scans identify {holding_regimes['primary_phase_count']} descriptive phases, with a {percent(holding_regimes['log_duration_rss_reduction'])} reduction in log-duration RSS and segmented-minus-single BIC of {number(holding_regimes['segmented_minus_single_bic'], 1)}. The boundaries are model-dependent and can result from volatility changes under one fixed exit rule.

{markdown_table(
        ['Phase', 'Dates', 'Trades', 'Median minutes', 'Winner median', 'Loser median'],
        [
            [int(row.phase), f"{str(row.start_open_time)[:10]} to {str(row.end_open_time)[:10]}", int(row.trades), number(row.median_duration_minutes, 2), number(row.winner_median_duration_minutes, 2), number(row.loser_median_duration_minutes, 2)]
            for row in phases.itertuples()
        ],
    )}

## G. Candidate strategy families

{markdown_table(
        ['Candidate', 'In-sample fit', 'Out-of-sample fit', 'Complexity', 'Stability', 'Evidence'],
        [[row.Candidate, row.In_sample_fit, row.Out_of_sample_fit, row.Complexity, row.Stability, row.Evidence] for row in candidates.itertuples()],
    )}

Trend, momentum, mean-reversion, breakout, price-action, volatility and event-driven families cannot be ranked from trade outcomes alone. The observed payoff and holding asymmetry does not support the stereotyped “many small wins and rare large losses” version of fixed-target mean reversion, but that is not a family-level rejection.

## H. Research review

The most transferable methods are system identification with explicit observational equivalence, change-point testing, finite mixtures/HMMs, chronological validation, block/bootstrap uncertainty, FDR/data-snooping controls, and interpretable rule discovery after a no-trade panel exists. Inverse reinforcement learning is premature because the state space, available actions and transitions are not observed, and reward functions are non-identifiable even with much richer demonstrations.

Closest direct precedents include [Hayes, Beling & Scherer on reverse engineering trading strategies](https://doi.org/10.1007/s10669-013-9458-1), [Yang et al. on Gaussian-process trading-strategy identification](https://doi.org/10.1080/14697688.2015.1011684), and [Sueshige et al. on identifying forex strategy ecology](https://doi.org/10.1371/journal.pone.0208332). Those projects use market states, complete action streams or order-book data that this TSV lacks.

{markdown_table(
        ['ID', 'Citation', 'Method', 'Transfer to this project', 'Main failure modes'],
        [[row['ID'], row['Citation'], row['Method'], row['Transfer to this project'], row['Main failure modes']] for _, row in source_matrix.head(12).iterrows()],
    )}

The full 26-source method/data/failure-mode matrix is in [`research/source_matrix.tsv`](../../research/source_matrix.tsv).

## I. Entry reconstruction

No entry rule is identified. What can be said is narrower:

- The executed direction sequence is balanced and statistically compatible with IID.
- Side does not materially change result, win fraction, holding time or above-base size.
- Entries concentrate in raw-clock windows and minute-of-hour bins, but timezone and opportunity exposure are missing.
- Three early overlap pairs are same-side and near-simultaneous, consistent with a shared signal or execution split.

To reconstruct entries, create a timestamped opportunity panel with Buy, Sell and NoTrade labels using the exact broker feed. Fit interpretable logistic models and shallow trees first; record incremental likelihood/AIC/BIC, permutation importance and time-ordered holdout results. Symbolic/program search should start only after the feature grammar and untouched test periods are frozen.

## J. Exit reconstruction

The file supports an outcome-conditioned duration fingerprint, not an exit mechanism. Fixed whole-minute timing is unsupported. Exact fixed TP/SL, trailing stops, signal reversal, volatility scaling and structure exits require the exit price plus the bid/ask path from open through close. MFE, MAE, exit-to-MFE ratio and ATR-scaled distances are therefore unavailable.

The defensible candidate is a generic rule class:

1. Close invalidated/losing positions relatively quickly.
2. Permit favorable positions to remain open longer.
3. Allow the overall time scale to vary by calendar/market regime.

This class is observationally compatible with several distinct implementations and is not source-code reconstruction.

## K. Risk reconstruction

The base observed size is 0.01. Larger sizes are episodic rather than a smooth monotone function of closed cumulative result. That weakens a simple equity-growth-step explanation, but equity and margin are absent. The single 0.03 row participates in a parallel same-direction pair, which is compatible with a one-off scale-in or execution split. Exact risk percent, stop-distance sizing, martingale/anti-martingale behavior and exposure caps remain unknown.

## L. Market-state analysis

{market_section}

## M. Model-selection evidence

{markdown_table(
        ['Model', 'Order', 'AIC', 'BIC', 'Minimum state/component size'],
        [
            *[['GMM', int(row.components), number(row.aic, 1), number(row.bic, 1), int(row.minimum_component_size)] for row in gmm.itertuples()],
            *[['Gaussian HMM', int(row.states), number(row.aic, 1), number(row.bic, 1), int(row.minimum_state_size)] for row in hmm.itertuples()],
        ],
    )}

The direction model comparison favors IID. The latent-feature models favor several descriptive components/states, but their state-count evidence is not a count of algorithms. The registered block-permutation one-change scan retains FDR-significant changes in lot size and raw-clock circular position; size-normalized P&L, win fraction and direction do not have an FDR-significant single change.

{markdown_table(
        ['Feature', 'Split time', 'Before', 'After', 'Block p', 'FDR q'],
        [[row.feature, row.split_open_time, number(row.mean_before, 3), number(row.mean_after, 3), pvalue(row.block_permutation_p_value), pvalue(row.fdr_q_value)] for row in block_significant.itertuples()],
    )}

## N. Out-of-sample testing

True strategy walk-forward validation remains blocked because an exact broker market state and an authenticated no-trade opportunity set are absent. The exploratory non-broker reference-feed test also fails to predict entries; it is evidence against adopting its fitted trees, not a reconstruction. A limited expanding-month behavioral stability test uses the first three months as the initial training window and advances one month at a time. Across {walk['folds']} folds, mean absolute errors are {percent(walk['mean_absolute_buy_rate_error'])} for Buy share, {percent(walk['mean_absolute_win_rate_error'])} for positive-result share, {number(walk['mean_absolute_mean_pnl_error'], 3)} result units for mean P&L and {number(walk['mean_absolute_median_duration_error'], 2)} minutes for median duration. This measures stability of summaries, not signal replication.

## O. Null-model testing

- Direction-label permutation shows no unusual adjacent persistence.
- Raw-clock bucket versus direction permutation is not significant (p={pvalue(temporal['side_clock_bucket_permutation_p_value'])}).
- The empirical-clock IID burst null is borderline (p={pvalue(clustering['empirical_clock_iid_null_p_value'])}).
- Buy/Sell raw and size-normalized result differences are null.
- Change-point scans use both IID and contiguous-block permutations; FDR uses the more conservative block p-values.
- The full test universe and BH/Bonferroni results are in [`tables/statistical_tests.csv`](tables/statistical_tests.csv).

## P. Robustness testing

- Bootstrap intervals are shown both at row level and by resampling whole active dates.
- P&L comparisons are repeated after normalizing for 0.01 size.
- Direction is checked by runs, permutation, likelihood-ratio, AIC and BIC methods.
- GMM stability is tested across seeds; PELT is tested across penalty multipliers; one-change scans use block permutation.
- Holding-time phase interpretation is checked against outcome behavior. Winners remain longer in every primary phase.
- Multiple-testing control is applied to the registered trade-only tests. {len(significant_tests)} tests remain significant at 5% BH FDR, but exposure-invalid timing references are not promoted to causal claims.

## Q. Reconstructed pseudocode

This is the maximum defensible reconstruction. `UNKNOWN` is deliberate.

```text
INPUTS
    broker market state = UNKNOWN
    account/equity state = UNKNOWN
    server timezone = UNKNOWN

MARKET FILTER
    UNKNOWN: trend / momentum / mean reversion / breakout / event logic

RAW-CLOCK FILTER
    behavior is concentrated in recurring clock windows
    exact named session = UNKNOWN until timezone is known

DIRECTION
    choose Buy or Sell by UNKNOWN market-state rule
    aggregate output is approximately symmetric and IID

POSITION SIZE
    default observed size = 0.01
    occasionally use 0.02; once use 0.03
    cause = UNKNOWN episodic risk/signal/execution condition

ENTRY
    enter one position
    rarely add a near-simultaneous same-direction position

EXIT
    if trade becomes unfavorable, it tends to close sooner
    if favorable, it tends to remain open longer
    calendar/market conditions alter the typical holding-time scale
    exact stop / target / trailing / reversal rule = UNKNOWN

RE-ENTRY
    short close-to-next-entry gaps occur, without strong direction persistence
```

## R. Confidence table

{markdown_table(
        ['Component', 'Reconstruction', 'Confidence'],
        [[row.Component, row.Reconstruction, row.Confidence] for row in confidence.itertuples()],
    )}

## S. What remains unknown

### Formal identifiability limitation

Let the observed trade sequence be

`T = F(M, A, E, θ)`,

where `M` is market history, `A` is account/risk state, `E` is execution/broker behavior and `θ` is the hidden strategy. In this file, most of `M`, `A` and `E` are unobserved. Even if they were known for the finite sample, different systems can satisfy

`F₁(M, A, E, θ₁) = F₂(M, A, E, θ₂) = T`.

Therefore a finite fitted rule does not prove source identity. The current result distinguishes exact file facts, statistical evidence, observational equivalence, plausible reconstruction and unsupported speculation. This follows the structural-identifiability literature ([Bellman & Åström](https://doi.org/10.1016/0025-5564(70)90132-X)) and the explicit non-identifiability results in inverse reinforcement learning ([Cao, Cohen & Szpruch](https://papers.nips.cc/paper/2021/hash/671f0311e2754fcdd37f70a8550379bc-Abstract.html)).

Unknown items include field-7 semantics; result currency and cost treatment; broker/server/timezone; contract size/tick value; entry and exit bid/ask; exact exit price; pending/rejected/cancelled orders; partial fills; magic/comment/EA identifiers; account equity; other positions; true opportunity set; and every market-state indicator at decision time.

## T. Additional data required

Highest priority:

1. Original MT4/MT5 statement plus raw deal, order and position history with stable IDs, comments, magic numbers and reason codes.
2. Broker/server name, server timezone and the complete `XAUUSD.f` Symbol Specification.
3. Entry and exit requested/executed bid/ask prices, spread, commission, swap, SL/TP and all modifications, partial fills, rejects and cancels.
4. Account balance/equity/margin history and all simultaneous positions.
5. Broker-specific ticks over the entire sample; if unavailable, broker-specific 1-minute bid/ask OHLC with spread and volume.
6. Versioned economic-release timestamps for any event-driven hypothesis.

The exact machine-readable schemas and rerun guidance are in [`docs/data_requirements.md`](../../docs/data_requirements.md).

## Reproducibility and audit artifacts

- [`analysis_metrics.json`](analysis_metrics.json): machine-readable headline results.
- [`tables/experiment_tracker.csv`](tables/experiment_tracker.csv): hypothesis register.
- [`tables/proof_log.csv`](tables/proof_log.csv): claim/evidence/test/assumption/alternative/confidence log.
- [`tables/specification_coverage.csv`](tables/specification_coverage.csv): section-by-section brief coverage.
- [`tables/anomaly_review.csv`](tables/anomaly_review.csv): statistically unusual rows, never labeled manual.
- [`tables/walk_forward_behavior.csv`](tables/walk_forward_behavior.csv): expanding-month behavior checks.
- [`tables/holding_time_recursive_scans.csv`](tables/holding_time_recursive_scans.csv): recursive holding-time scans and p-values.
- [`tables/holding_time_phases.csv`](tables/holding_time_phases.csv): primary duration phases.
- [`research/source_matrix.tsv`](../../research/source_matrix.tsv): research/data-requirement matrix.

All outputs derive from the preserved raw file and deterministic random seeds. See the project README for the rerun command.
"""

    output_path = output_dir / "reverse_engineering_report.md"
    output_path.write_text(report, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--project-root", default=Path.cwd(), type=Path)
    args = parser.parse_args()
    path = build_report(args.output.resolve(), args.project_root.resolve())
    print(json.dumps({"status": "ok", "report": str(path)}))


if __name__ == "__main__":
    main()
