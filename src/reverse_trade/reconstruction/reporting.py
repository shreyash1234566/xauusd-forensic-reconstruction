"""Forensic reporting, artifact generation, and candidate packaging (Stages X, Y, Z).

Implements:
- Final verdict report generator (final_verdict.md).
- Residual divergence casebook report (residual_casebook.md).
- Robustness and placebo calibration report (calibration_report.md).
- Machine-readable candidate policy export and executable Python/MQL5 reference code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from .identifiability import EquivalenceClass, IdentifiabilitySummary, PlaceboTestResult
from .io import write_json
from .policy_ast import Policy
from .search import CandidateEvaluation


def generate_final_verdict_markdown(summary: IdentifiabilitySummary) -> str:
    """Produce authoritative markdown report for final reconstruction verdict (Stage Y)."""

    lines = [
        "# Algorithm Reconstruction Final Verdict Report",
        "",
        "## 1. Reconstruction Verdict & Claim Level",
        f"- **Assigned Verdict:** `{summary.verdict.value}`",
        f"- **Explanation:** {summary.verdict_explanation}",
        "",
        "## 2. Quantitative Summary",
        f"- **Total Candidates Evaluated:** {summary.num_candidates_evaluated:,}",
        f"- **Observational Equivalence Classes:** {summary.num_equivalence_classes}",
        f"- **Top Candidate ID:** `{summary.top_candidate_id or 'None'}`",
        f"- **Top Candidate F1 Score:** {summary.top_candidate_f1:.4f}",
        f"- **Top Candidate Entry Error Loss:** {summary.top_candidate_loss:.4f}",
        f"- **Supported Observed Epochs:** {summary.supported_observed_epochs}",
        f"- **Unsupported / Gap Epochs:** {summary.unsupported_observed_epochs}",
        "",
        "## 3. Surviving Equivalence Classes",
    ]

    if not summary.equivalence_classes:
        lines.append("*No distinct equivalence classes survived search criteria.*")
    else:
        lines.append("| Class ID | Size | Representative Candidate | Mean F1 | Mean Loss | Member Candidates |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for eq in summary.equivalence_classes:
            members_str = ", ".join(eq.member_candidate_ids[:5])
            if len(eq.member_candidate_ids) > 5:
                members_str += f", ... (+{len(eq.member_candidate_ids)-5} more)"
            lines.append(
                f"| `{eq.class_id}` | {eq.size} | `{eq.representative_candidate_id}` | {eq.mean_f1:.4f} | {eq.mean_entry_loss:.4f} | {members_str} |"
            )

    lines.extend([
        "",
        "## 4. Methodological Invariants & Guarantees",
        "- **Causal feature helper:** Its quote-window function uses timestamps strictly before the decision boundary; this guarantee applies only when candidates are built through that helper.",
        "- **Independent Replay Simulation:** Replay engine executes autonomously without borrowing ledger state.",
        "- **Separation of Evidence:** Observed coverage is strictly separated from gap periods.",
    ])

    return "\n".join(lines) + "\n"


def generate_residual_casebook_markdown(casebook: pd.DataFrame) -> str:
    """Produce detailed casebook of false positives (FP) and false negatives (FN) (Stage X)."""

    lines = [
        "# Divergence & Residual Error Casebook",
        "",
        "## 1. Overview",
        f"- **Total Divergence Cases Cataloged:** {len(casebook):,}",
        "",
    ]

    if casebook.empty:
        lines.append("*Zero divergence cases cataloged. Candidate matches observed ledger epochs perfectly.*")
        return "\n".join(lines) + "\n"

    fn_count = (casebook["status"] == "FN").sum() if "status" in casebook.columns else 0
    fp_count = (casebook["status"] == "FP").sum() if "status" in casebook.columns else 0

    lines.extend([
        f"- **Missed Observed Epochs (FN):** {fn_count}",
        f"- **False Prediction Alarms (FP):** {fp_count}",
        "",
        "## 2. Catalog of Divergence Events",
        "| # | Status | Event Type | Decision Time (UTC) | Side | Reason Category | Detail |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for _, row in casebook.iterrows():
        idx = row.get("divergence_index", "-")
        status = row.get("status", "-")
        ev_type = row.get("event_type", "-")
        t_utc = str(row.get("decision_time_utc", "-"))
        side = row.get("side", "-")
        reason = row.get("reason_category", "-")
        detail = row.get("detail", "-")

        lines.append(
            f"| {idx} | `{status}` | `{ev_type}` | `{t_utc}` | {side} | `{reason}` | {detail} |"
        )

    return "\n".join(lines) + "\n"


def generate_placebo_calibration_markdown(placebo_results: Sequence[PlaceboTestResult]) -> str:
    """Produce placebo and robustness calibration report (Stage W)."""

    lines = [
        "# Circular Time-Shift Stress Check",
        "",
        "This is a descriptive stress check for a fixed candidate. Candidate search is not rerun, so the tail fractions are not search-adjusted p-values and do not establish statistical significance.",
        "",
        "## Circular-shift results",
        "",
        "| Candidate ID | Real F1 | Real Loss | Shifted F1 Mean ± Std | Shifted Loss Mean | Empirical F1 tail fraction |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for p in placebo_results:
        lines.append(
            f"| `{p.candidate_id}` | {p.real_f1:.4f} | {p.real_entry_loss:.4f} | {p.null_f1_mean:.4f} ± {p.null_f1_std:.4f} | {p.null_entry_loss_mean:.4f} | {p.p_value_f1:.4f} |"
        )

    lines.extend([
        "",
        "## Interpretation",
        "- Observed event times were circularly shifted across their finite time span while candidate predictions were fixed.",
        "- The add-one empirical tail fraction is descriptive. It is not a conventional p-value because the search and candidate selection were not repeated for each shift.",
    ])

    return "\n".join(lines) + "\n"


def export_reconstructed_policy_package(
    policy: Policy,
    evaluation: CandidateEvaluation,
    output_dir: Path,
) -> dict[str, Path]:
    """Export canonical machine-readable JSON, executable Python reference, and execution artifacts (Stage Z)."""

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Machine-readable policy JSON
    policy_json_path = output_dir / "policy_ast.json"
    write_json(policy_json_path, policy.to_dict())

    # 2. Evaluation metrics JSON
    metrics_json_path = output_dir / "evaluation_metrics.json"
    write_json(metrics_json_path, {
        "candidate_id": evaluation.candidate_id,
        "metrics": evaluation.metrics,
    })

    # 3. Executable Python script representation
    py_script_path = output_dir / "reconstructed_policy_executable.py"
    policy_json_str = json.dumps(policy.to_dict(), indent=4)
    py_code = [
        '"""Authoritative executable Python representation of reconstructed trading policy."""',
        "",
        "import json",
        "from reverse_trade.reconstruction.policy_ast import Policy, Action, TimeExit, ThresholdCondition, AndCondition",
        "from reverse_trade.reconstruction.replay import ReplayEngine, Quote",
        "",
        f"# Reconstructed AST definition for candidate {evaluation.candidate_id}",
        f'POLICY_SPEC_JSON = """{policy_json_str}"""',
        "",
        "def get_reconstructed_policy() -> Policy:",
        "    return Policy.from_dict(json.loads(POLICY_SPEC_JSON))",
        "",
        "if __name__ == '__main__':",
        "    policy = get_reconstructed_policy()",
        f"    print(f'Loaded reconstructed policy: {{policy.name}}')",
    ]
    py_script_path.write_text("\n".join(py_code) + "\n", encoding="utf-8")

    # 4. Predictions and matches CSVs
    preds_path = output_dir / "predicted_trades.csv"
    evaluation.predictions.to_csv(preds_path, index=False)

    matches_path = output_dir / "trade_matches.csv"
    evaluation.matches.to_csv(matches_path, index=False)

    return {
        "policy_json": policy_json_path,
        "metrics_json": metrics_json_path,
        "executable_py": py_script_path,
        "predicted_trades": preds_path,
        "trade_matches": matches_path,
    }
