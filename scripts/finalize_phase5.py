"""Finalize Phase 5 status documents from the already-computed evidence tables."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"


def table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "No rows."
    lines = ["| " + " | ".join(frame.columns) + " |", "| " + " | ".join("---" for _ in frame.columns) + " |"]
    for values in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(value).replace("|", "/") for value in values) + " |")
    return "\n".join(lines)


def summarize_replication(frame: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    summary = frame.groupby(group_columns, as_index=False).agg(
        validation_observations=("validation_observations", "sum"), signals=("signals", "sum"),
        trades_captured=("trades_captured", "sum"), false_alarms=("false_alarms", "sum"),
        mean_fold_precision=("precision", "mean"), mean_fold_recall=("recall", "mean"), mean_fold_f1=("f1", "mean"),
        mean_pr_auc=("pr_auc", "mean"), mean_roc_auc=("roc_auc", "mean"), mean_signals_per_10000=("signals_per_10000", "mean"),
    )
    summary["pooled_precision"] = summary.trades_captured / summary.signals.replace(0, pd.NA)
    return summary


def main() -> None:
    canonical = json.loads((OUT / "phase5_canonical_statistics.json").read_text(encoding="utf-8"))
    canonical_row = pd.DataFrame([canonical])
    (OUT / "phase5_canonical_recheck.md").write_text(
        "# Phase 5 canonical recheck\n\n" + table(canonical_row) + "\n\n"
        "The raw ledger is canonical. Its strict timestamp recheck finds three later entries that began while an earlier trade was still open, correcting the earlier narrative count of five. This still falsifies a universal flat-only rule. The 423 second-level entries collapse to 420 distinct M1 candidate minutes solely because of M1 aggregation.\n",
        encoding="utf-8",
    )
    negative = pd.read_csv(OUT / "phase5_negative_space_table.csv.gz")
    symbolic = pd.read_csv(OUT / "phase5_symbolic_candidates.csv")
    replication = pd.read_csv(OUT / "phase5_replication_results.csv")
    baseline = summarize_replication(replication.loc[replication.family.eq("CLOCK+MARKET+STATE")], ["candidate", "family"])
    ablation = summarize_replication(replication.loc[replication.family.ne("CLOCK+MARKET+STATE")], ["candidate", "family"])
    (OUT / "phase5_baseline_analysis.md").write_text(
        "# Phase 5 baseline observable-space models\n\n"
        "Five predeclared regularized/restricted classifiers were evaluated with five expanding chronological folds. Training used a bounded case-control sample for computational stability; every validation metric is computed across the full chronological candidate-minute fold. Thresholds select the predeclared raw-trade-rate signal budget. A 15-minute embargo separates train from validation.\n\n"
        + table(baseline.round(6)) + "\n\nPR AUC is primary; ROC AUC is secondary under extreme imbalance. Neither is evidence that the original EA has been recovered.\n",
        encoding="utf-8",
    )
    (OUT / "phase5_feature_ablation.md").write_text(
        "# Phase 5 feature-family ablation\n\n"
        "The ten hypothesis families were predeclared before inspection: A CLOCK, B GEOMETRY, C MOMENTUM, D VOLATILITY, E TREND/LOCATION, F ACCOUNT STATE, and the four stated combinations. Each uses the same L1 logistic candidate and chronological protocol.\n\n"
        + table(ablation.round(6)) + "\n\nNo family is called a reconstruction unless it distinguishes matched controls and has stable OOS precision and recall.\n",
        encoding="utf-8",
    )
    rows = replication.loc[replication.family.ne("CLOCK+MARKET+STATE")].copy()
    summary = rows.groupby("family", as_index=False).agg(
        signals=("signals", "sum"), trades_captured=("trades_captured", "sum"), false_alarms=("false_alarms", "sum"),
        mean_fold_f1=("f1", "mean"), mean_fold_pr_auc=("pr_auc", "mean"), mean_fold_precision=("precision", "mean"),
    )
    summary = summary.sort_values(["mean_fold_f1", "mean_fold_precision"], ascending=False).head(3).round(6)
    status = "# Phase 5 status\n\n"
    status += "1. **Canonical ground truth:** 423 trades; 214 Buy / 209 Sell; 367 profitable / 56 losing; +1451.22 P&L; 401×0.01, 21×0.02, 1×0.03; three later entries began while a prior trade was active. The Phase 5 raw-ledger recheck corrects the earlier narrative count of five.\n"
    status += "2. **Observable information:** completed external bid-only M1 OHLCV-derived features, raw-clock features, and prior ledger/account-state proxies.\n"
    status += "3. **Provably unavailable locally:** broker-native ticks, Ask/spread, order/deal/position lifecycle, modifications, rejected/cancelled orders, and broker-server timing.\n"
    status += f"4. **Nearest non-trade alternatives:** {len(negative)} hierarchical matched rows cover {negative.ticket.nunique()} tickets; no observable equality can rule out a hidden order, quote or state difference.\n"
    status += "5. **OOS feature families:** see the predeclared ablation results below; none is labelled a reconstruction without matched acceptance.\n"
    status += "6. **Symbolic regression:** constrained eight-expression candidate generation found no compact stable rule that passed the combined acceptance test.\n"
    status += f"7. **Exact trade moments:** no candidate reproduces a substantial fraction of exact second-level trade moments; the observable panel has {canonical['distinct_entry_minutes']} distinct M1 entry minutes for 423 trades.\n"
    status += "8. **Matched near-miss testing:** no candidate met the predeclared matched-control acceptance test after BH correction.\n"
    status += "9. **Direction:** remains unidentified within the observable opportunity-minute set.\n"
    status += "10. **Sizing:** remains unidentified; only 22 above-minimum-size observations and critical account inputs are missing.\n"
    status += "11. **Exits:** NOT_IDENTIFIABLE_FROM_M1.\n"
    status += "12. **Regime specificity:** no reconstruction-level candidate exists to claim cross-regime stability.\n"
    status += "13. **Hypotheses tested:** 5 full-feature baselines + 10 L1 ablations + 8 predeclared symbolic predicates + 4 controlled sequences.\n"
    status += "14. **Multiple testing:** BH was applied to the eight symbolic enrichment tests and separately to eight matched tests; no candidate met the combined acceptance rule.\n"
    status += "15. **Mathematically unidentifiable:** the original policy among infinitely many compatible computable policies, exact intrabar trigger, true opportunity set and lifecycle.\n"
    status += "16. **Highest-value additional data:** a synchronized native terminal/account archive containing Bid/Ask ticks plus Orders, Deals, Positions and Journal lifecycle for XAUUSD.f.\n\n"
    status += "## Top ablation summaries\n\n" + table(summary) + "\n\n**Final level: LEVEL D — UNIDENTIFIED.** Statistical association, prediction, and a compact observable predicate are not treated as causal reconstruction.\n"
    (OUT / "phase5_status.md").write_text(status, encoding="utf-8")
    validation = {
        "phase": 5, "identification_level": "D — UNIDENTIFIED", "canonical": canonical,
        "candidate_minutes": 346696, "entry_minutes": int(canonical["distinct_entry_minutes"]), "negative_space_rows": int(len(negative)),
        "folds": 5, "embargo_minutes": 15, "baseline_hypotheses": 5, "ablation_hypotheses": 10,
        "symbolic_hypotheses": int(len(symbolic)), "sequence_hypotheses": 4,
        "symbolic_accepted": int(symbolic.acceptance.eq("CANDIDATE_FOR_FURTHER_EVIDENCE").sum()),
        "sindy": "SINDY_NOT_APPLICABLE", "irl": "IRL_NOT_IDENTIFIABLE",
        "future_information_policy": "All market features shifted one M1 observation; account-state features use prior observed entries/exits only.",
    }
    (OUT / "phase5_validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "level": validation["identification_level"], "symbolic_accepted": validation["symbolic_accepted"]}, indent=2))


if __name__ == "__main__":
    main()
