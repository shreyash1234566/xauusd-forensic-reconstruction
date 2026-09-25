"""Final gated U-Z packaging when no complete policy survives selection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence import audit_canonical_evidence
from .io import sha256, write_json


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def finalize_reconstruction(
    root: Path,
    output: Path,
    *,
    gm_run: Path,
    benchmark_run: Path,
    baseline_run: Path,
    search_run: Path,
    component_run: Path,
    stateful_run: Path,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    gm = _read(gm_run / "run_summary.json")
    n = _read(benchmark_run / "stage_status.json")
    o = _read(baseline_run / "stage_status.json")
    q = _read(search_run / "Q_memoryless_search" / "stage_status.json")
    s = _read(component_run / "S_direction_size" / "stage_status.json")
    t = _read(component_run / "T_exits" / "stage_status.json")
    r = _read(stateful_run / "R_stateful_search" / "stage_status.json")
    if (gm["status"] != "G_to_M_complete" or n["status"] != "passed" or o["status"] != "passed"
            or r["status"] != "passed_bounded_search_complete"):
        raise ValueError("Upstream gates G-R are not complete")

    r_status = r
    u_status = {
        "stage": "U_complete_policy_assembly", "status": "not_run_no_complete_candidate" if not r["any_candidate_accepted"] else "requires_candidate_assembly",
        "reason": "No bounded Stage R candidate survived all outer-fold and MDL gates." if not r["any_candidate_accepted"] else "At least one Stage R candidate requires explicit full-policy assembly before replay.",
    }
    v_status = {
        "stage": "V_autonomous_replay", "status": "not_run_no_complete_policy" if not r["any_candidate_accepted"] else "pending_complete_policy_assembly",
        "reason": "Autonomous replay requires a frozen complete policy; replaying an unselected rule would be a post-selection claim.",
    }
    w_status = {
        "stage": "W_robustness_placebo", "status": "not_applicable_for_acceptance",
        "reason": "There is no accepted candidate to calibrate. Four chronological outer-fold results and the MDL penalty remain reported; no p-value is claimed.",
    }
    for name, value in (("R", r_status), ("U", u_status), ("V", v_status), ("W", w_status)):
        write_json(output / f"{name}_stage_status.json", value)

    x = {
        "stage": "X_residual_diagnosis", "status": "complete",
        "canonical_epochs": 420,
        "supported_feature_epochs": s["supported_entry_epochs"],
        "unevaluable_epochs": 420 - s["supported_entry_epochs"],
        "entry_timing": {
            "weak_structure": "UTC split near 14:00 was positive in four outer folds",
            "mean_bits_per_event": q["best_mean_outer_bits_per_event_vs_B0"],
            "total_information_gain_bits": q["best_total_outer_information_gain_bits"],
            "complexity_bits": q["best_complexity_bits"],
            "mdl_net_bits": q["best_outer_mdl_net_bits"],
            "accepted": False,
        },
        "direction": {"mean_bits_per_trade": s["mean_outer_direction_bits_per_trade"], "identified": False},
        "size": {"base_volume_fraction": s["base_0_01_volume_fraction"], "identified": False},
        "exit": {"identified": False, "reason": t["reason"]},
    }
    write_json(output / "X_residual_summary.json", x)

    verdict = {
        "verdict": "UNIDENTIFIED_PARTIAL_BEHAVIORAL_STRUCTURE",
        "exact_source_algorithm_identified": False,
        "observationally_equivalent_complete_policy_identified": False,
        "accepted_entry_mechanism": False,
        "supported_claims": [
            "The complete public Dukascopy calendar-hour response set was acquired and validated separately from canonical Phase 7C evidence.",
            "299 of 420 canonical entry epochs have the registered 30-second causal feature support.",
            "A diagnostic split near 14:00 UTC is positive in all four outer folds but fails MDL after its registered 64-bit cost.",
            "The registered causal features do not improve the broad logistic intensity baselines out of sample.",
            f"Stage R searched {r['registered_candidates']} bounded minute-clock interaction/state candidates; none passed the outer-fold and fully accounted MDL gate.",
            "Conditional direction and exit mechanisms are not identified; 0.01 is the dominant observed size.",
        ],
        "unsupported_claims": [
            "unique original source code", "complete entry rule", "autonomous replay compatibility",
            "direction rule", "sizing rule", "exit/order-management rule", "account uptime schedule",
        ],
        "why": "No complete candidate has passed the executed bounded searches; this is not proof against unsearched programs, observation models, or unavailable account state.",
    }
    write_json(output / "Y_identifiability_verdict.json", verdict)

    evidence = audit_canonical_evidence(root)
    artifact_paths = [
        gm_run / "run_summary.json",
        gm_run / "L_opportunities" / "risk_set_audit.json",
        benchmark_run / "stage_status.json",
        baseline_run / "stage_status.json",
        search_run / "Q_memoryless_search" / "stage_status.json",
        component_run / "run_summary.json",
        stateful_run / "run_summary.json",
        output / "Y_identifiability_verdict.json",
    ]
    manifest = {
        "canonical_evidence": evidence,
        "artifacts": [
            {"path": path.relative_to(root).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size}
            for path in artifact_paths
        ],
        "no_reconstructed_policy_exported": True,
        "reason": "Exporting an executable policy would misrepresent an unidentified result.",
    }
    write_json(output / "Z_reproduction_manifest.json", manifest)
    report = f"""# Hidden trading policy reconstruction — final gated result

## Verdict

**UNIDENTIFIED — partial behavioral structure only.** No exact or observationally equivalent complete trading policy passed the registered gates.

## What ran

Stages A–F locked and validated the evidence and separate public feed. G–M defined observation assumptions, clocks, eligibility, folds, causal features, a label-independent quote-clock risk set, and replay semantics. Stage N used one family-blind grammar to recover all registered planted in-grammar families and reject the stochastic and nonlinear fixtures. Stage O fit six weighted chronological event baselines. P–Q searched a frozen memoryless symbolic grammar. Stage R searched bounded interactions, trajectories, and state. S–T tested direction, size, and exits conditionally.

## Quantitative result

- Supported causal-feature entry epochs: **{s['supported_entry_epochs']} / 420**; the other **{420 - s['supported_entry_epochs']}** remain unevaluable, not negative examples.
- Strongest Q rule: UTC split near 14:00, **{q['best_mean_outer_bits_per_event_vs_B0']:.4f} bits/event** averaged across four positive outer folds.
- Total outer information gain: **{q['best_total_outer_information_gain_bits']:.2f} bits** versus **{q['best_complexity_bits']} complexity bits**, so MDL net is **{q['best_outer_mdl_net_bits']:.2f} bits** and the rule is rejected.
- Stage R searched **{r['registered_candidates']}** interaction/trajectory/state candidates on **{r['minute_rows']:,}** provider minutes. Its best frozen-cohort candidate achieved **{r['best_mean_outer_bits_per_event']:.4f} bits/event** and **{r['best_outer_mdl_net_bits']:.2f} net bits** after grammar and fitted-parameter cost; accepted candidates: **{len(r['accepted_candidate_ids'])}**.
- Direction: **{s['mean_outer_direction_bits_per_trade']:.4f} bits/trade** versus the training-rate baseline; not identified.
- Size: **{100*s['base_0_01_volume_fraction']:.2f}%** of supported epochs use 0.01 volume; no causal size mechanism identified.
- Exit: no registered fixed duration matches more than **{t['fixed_time_exact_matches_within_1s_max']}** supported record within one second; exit mechanism not identified.

## Scope of the result

Stage R executed a bounded minute-clock search over interactions, crossings, persistence, and armed/cooldown state. Its result is evidence only about that registered family under the public-feed observation assumptions. If no candidate survives, U-V remain unexecuted; that is an inconclusive bounded-search result, not a proof that the source algorithm is unfindable.
"""
    (output / "FINAL_RECONSTRUCTION_REPORT.md").write_text(report, encoding="utf-8")
    summary = {"status": "BOUNDED_SEARCH_COMPLETE_NOT_UNIVERSAL_A_TO_Z", **verdict}
    write_json(output / "run_summary.json", summary)
    return summary
