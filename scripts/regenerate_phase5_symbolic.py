"""Re-evaluate the fixed symbolic predicates against final level-F controls."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest

from phase5_observable_reconstruction import bh_qvalues, symbolic_rules


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"


def markdown_table(frame: pd.DataFrame) -> str:
    lines = ["| " + " | ".join(frame.columns) + " |", "| " + " | ".join("---" for _ in frame.columns) + " |"]
    for values in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(value).replace("|", "/") for value in values) + " |")
    return "\n".join(lines)


def main() -> None:
    panel = pd.read_csv(OUT / "phase5_feature_table.csv.gz", parse_dates=["timestamp"])
    negative = pd.read_csv(OUT / "phase5_negative_space_table.csv.gz")
    controls = negative.loc[negative.is_final_matched_control].copy()
    lookup = panel.set_index("timestamp")
    y = panel.entry.to_numpy(dtype=bool)
    base = y.mean()
    rows = []
    for name, predicate in symbolic_rules(panel).items():
        signal = predicate(panel).fillna(False).to_numpy(dtype=bool)
        activated = int(signal.sum())
        tp = int((signal & y).sum())
        enriched = binomtest(tp, activated, base, alternative="greater").pvalue if activated else 1.0
        trade_hits, control_hits = [], []
        for row in controls.itertuples(index=False):
            trade_ts, control_ts = pd.Timestamp(row.trade_candidate_minute), pd.Timestamp(row.control_timestamp)
            if trade_ts in lookup.index and control_ts in lookup.index:
                trade_hits.append(bool(predicate(lookup.loc[[trade_ts]]).iloc[0]))
                control_hits.append(bool(predicate(lookup.loc[[control_ts]]).iloc[0]))
        trade_only = sum(a and not b for a, b in zip(trade_hits, control_hits))
        control_only = sum((not a) and b for a, b in zip(trade_hits, control_hits))
        matched_p = binomtest(max(trade_only, control_only), trade_only + control_only, 0.5).pvalue if trade_only + control_only else 1.0
        rows.append({
            "expression": name, "features_used": name.replace("and", "+"), "complexity": name.count("and") + 1,
            "training_precision": "NOT_FIT", "oos_precision": tp / activated if activated else 0.0, "oos_recall": tp / y.sum(),
            "oos_f1": 2 * tp / (activated + y.sum()) if activated else 0.0, "oos_pr_auc": "NOT_APPLICABLE_PREDICATE",
            "predicted_signals": activated, "actual_trades_captured": tp, "false_alarms": activated - tp,
            "fold_stability": "static predicate; evaluated across full observable panel", "enrichment_pvalue": enriched,
            "matched_discordant_trade_only": trade_only, "matched_discordant_control_only": control_only, "matched_pvalue": matched_p,
        })
    result = pd.DataFrame(rows)
    result["enrichment_qvalue"] = bh_qvalues(result.enrichment_pvalue)
    result["matched_qvalue"] = bh_qvalues(result.matched_pvalue)
    result["acceptance"] = np.where((result.oos_f1 >= .05) & (result.matched_qvalue < .05), "CANDIDATE_FOR_FURTHER_EVIDENCE", "REJECTED_AS_RECONSTRUCTION")
    result.to_csv(OUT / "phase5_symbolic_candidates.csv", index=False)
    (OUT / "phase5_symbolic_regression.md").write_text(
        "# Phase 5 symbolic candidate generation\n\n"
        "A fixed eight-expression, depth-limited Boolean grammar was enumerated instead of an unconstrained formula search. The candidate set was defined before testing. BH FDR correction is applied separately to the eight panel-enrichment tests and eight final-level-F matched-control tests. These are observable-space predicates, not an EA formula.\n\n"
        + markdown_table(result.round(6)) + "\n\nNo expression is accepted as a reconstruction unless it satisfies both predeclared OOS and matched-control requirements.\n",
        encoding="utf-8",
    )
    print({"expressions": len(result), "accepted": int(result.acceptance.eq("CANDIDATE_FOR_FURTHER_EVIDENCE").sum())})


if __name__ == "__main__":
    main()
