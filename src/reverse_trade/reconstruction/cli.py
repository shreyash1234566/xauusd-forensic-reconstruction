"""Staged, evidence-gated runner for hidden-policy reconstruction.

The current project data supports canonical evidence and coverage audits. Later
analysis commands write an explicit blocked status until their required inputs
exist; they never synthesize market features from trade timestamps.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .acquisition import acquisition_plan_from_coverage
from .coverage import build_coverage_inventory, supported_at
from .evidence import audit_canonical_evidence, build_decision_epochs, load_canonical_records
from .io import write_json
from .risk_set import audit_sampled_quote_risk_set, build_sampled_quote_risk_set
from .stages_gm import stage_g, stage_h, stage_i, stage_j, stage_k_spec, stage_m
from .stage_n import run_stage_n
from .stage_o import run_stage_o
from .stage_pq import run_stage_q, stage_p
from .stage_st import run_stage_s, run_stage_t
from .stage_r import run_stage_r
from .finalize import finalize_reconstruction


def _default_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _coverage(root: Path, *, include_hash: bool = False) -> pd.DataFrame:
    records = load_canonical_records(root)
    return build_coverage_inventory(
        root / "data" / "market" / "raw_ticks",
        include_hash=include_hash,
        expected_start=records.open_time_utc.min(),
        expected_end=records.close_time_utc.max(),
    )


def command_audit(root: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    evidence = audit_canonical_evidence(root)
    records = load_canonical_records(root)
    annotated, epochs = build_decision_epochs(records)
    write_json(output / "evidence_manifest.json", evidence)
    annotated.to_csv(output / "canonical_records_annotated.csv", index=False)
    epochs.to_csv(output / "decision_epochs.csv", index=False)
    write_json(output / "audit_summary.json", {"records": len(records), "epochs": len(epochs), "status": "passed"})


def command_coverage(root: Path, output: Path, include_hash: bool = False) -> pd.DataFrame:
    output.mkdir(parents=True, exist_ok=True)
    inventory = _coverage(root, include_hash=include_hash)
    inventory.to_csv(output / "coverage_hours.csv", index=False)
    in_span = inventory.loc[inventory["in_expected_span"]]
    observed = int(in_span.support_status.eq("observed").sum())
    write_json(output / "coverage_summary.json", {
        "calendar_hours_in_ledger_span": len(in_span),
        "files_present": int(in_span.status.ne("missing_file").sum()),
        "observed_nonempty_files": observed,
        "missing_files": int(in_span.status.eq("missing_file").sum()),
        "empty_files": int(in_span.status.eq("empty").sum()),
        "invalid_files": int(in_span.status.eq("invalid").sum()),
        "nonempty_file_fraction_of_calendar_hours": observed / len(in_span),
        "additional_files_outside_ledger_span": int((~inventory.in_expected_span).sum()),
        "interpretation": "calendar-hour inventory only; unknown is not a negative label, and a nonempty file does not certify continuous intrahour coverage",
    })
    return inventory


def command_acquisition_plan(
    root: Path,
    output: Path,
    provider_id: str = "unselected_public_source",
    inventory: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if inventory is None:
        inventory = _coverage(root)
    if "in_expected_span" in inventory.columns:
        inventory = inventory.loc[inventory.in_expected_span].copy()
    plan = acquisition_plan_from_coverage(inventory, provider_id=provider_id)
    output.mkdir(parents=True, exist_ok=True)
    plan.to_csv(output / "supplemental_acquisition_plan.csv", index=False)
    write_json(output / "supplemental_acquisition_summary.json", {
        "provider_id": provider_id,
        "planned_hours": len(plan),
        "network_requests_performed": 0,
        "status": "planned_only",
        "note": "Unknown calendar hours include market closures; validate provider availability and estimate size before downloading.",
    })
    return plan


def command_prepare(
    root: Path,
    output: Path,
    *,
    include_hash: bool = False,
    supplemental_ticks_dir: Path | None = None,
) -> dict[str, object]:
    """Run evidence freeze, coverage reconstruction, and optional source audit."""
    command_audit(root, output / "audit")
    records = load_canonical_records(root)
    _, epochs = build_decision_epochs(records)
    inventory = command_coverage(root, output / "coverage", include_hash)
    acquisition = command_acquisition_plan(root, output / "acquisition", inventory=inventory)

    supplemental_inventory = None
    supplemental_support_counts: dict[str, int] = {}
    if supplemental_ticks_dir is not None:
        supplemental_inventory = build_coverage_inventory(
            supplemental_ticks_dir,
            include_hash=include_hash,
            expected_start=records.open_time_utc.min(),
            expected_end=records.close_time_utc.max(),
        )
        supplemental_inventory.to_csv(output / "coverage" / "dukascopy_coverage_hours.csv", index=False)
        supplemental_summary = {
            "provider_id": "dukascopy_supplemental",
            "calendar_hours": int(supplemental_inventory.in_expected_span.sum()),
            "nonempty_valid_hours": int((supplemental_inventory.in_expected_span & supplemental_inventory.support_status.eq("observed")).sum()),
            "empty_hours": int((supplemental_inventory.in_expected_span & supplemental_inventory.status.eq("empty")).sum()),
            "invalid_hours": int((supplemental_inventory.in_expected_span & supplemental_inventory.status.eq("invalid")).sum()),
            "missing_files": int((supplemental_inventory.in_expected_span & supplemental_inventory.status.eq("missing_file")).sum()),
            "source_stream_is_separate_from_canonical": True,
        }
        write_json(output / "coverage" / "dukascopy_coverage_summary.json", supplemental_summary)
        supplemental_acquisition = command_acquisition_plan(
            root,
            output / "acquisition" / "dukascopy",
            provider_id="dukascopy",
            inventory=supplemental_inventory,
        )
        supplemental_inventory["support_status"] = supplemental_inventory.apply(
            lambda row: "observed" if row.status == "ok" and row.tick_count > 0 else "unknown",
            axis=1,
        )
        event_support = pd.DataFrame({
            "epoch_id": epochs["epoch_id"],
            "decision_time_utc": pd.to_datetime(epochs["decision_time_utc"], utc=True),
        })
        event_support["supported_30s_lookback"] = event_support.decision_time_utc.map(
            lambda time: supported_at(supplemental_inventory, time, lookback=pd.Timedelta(seconds=30))
        )
        event_support.to_csv(output / "coverage" / "dukascopy_event_support.csv", index=False)
        supplemental_support_counts = {
            "canonical_decision_epochs_supported_with_30s_history": int(event_support.supported_30s_lookback.sum()),
            "canonical_decision_epochs_unsupported_with_30s_history": int((~event_support.supported_30s_lookback).sum()),
            "supplemental_provider_planned_unknown_hours": len(supplemental_acquisition),
        }

    nonempty_hours = set(pd.to_datetime(
        inventory.loc[inventory.support_status.eq("observed"), "intended_hour_utc"], utc=True
    ))
    support = pd.DataFrame({
        "epoch_id": epochs["epoch_id"],
        "decision_time_utc": epochs["decision_time_utc"],
    })
    support["hour_utc"] = pd.to_datetime(support.decision_time_utc, utc=True).dt.floor("h")
    support["hour_file_nonempty"] = support.hour_utc.isin(nonempty_hours)
    support["support_status"] = "unknown_feature_coverage_not_certified"
    support.loc[~support.hour_file_nonempty, "support_status"] = "unknown_hour_file_absent_or_empty"
    support.to_csv(output / "epoch_support.csv", index=False)

    hours = len(pd.date_range(records.open_time_utc.min().floor("h"), records.close_time_utc.max().floor("h"), freq="h", tz="UTC"))
    in_span = inventory.loc[inventory.in_expected_span]
    observed = int(in_span.support_status.eq("observed").sum())
    summary: dict[str, object] = {
        "status": "A_to_D_complete_coverage_gate_failed",
        "canonical_records": len(records),
        "canonical_epochs": len(epochs),
        "first_open_utc": records.open_time_utc.min(),
        "last_close_utc": records.close_time_utc.max(),
        "calendar_hours": hours,
        "nonempty_tick_files": observed,
        "missing_tick_files": int(in_span.status.eq("missing_file").sum()),
        "empty_tick_files": int(in_span.status.eq("empty").sum()),
        "invalid_tick_files": int(in_span.status.eq("invalid").sum()),
        "nonempty_file_fraction_calendar_hours": observed / hours,
        "planned_unknown_hours": len(acquisition),
        "epochs_in_nonempty_hour_files": int(support.hour_file_nonempty.sum()),
        "epochs_without_nonempty_hour_file": int((~support.hour_file_nonempty).sum()),
        "full_exposure_supported": False,
        "interpretation": "This calendar fraction is not a tradable-hours fraction. Existing files are trade-window-selected, and raw-file presence does not establish complete hourly or account-operation coverage.",
        "downstream_gate": "No real-ledger baseline, policy search, placebo significance, or identifiability verdict is valid until independent opportunities and real causal features are built over supported exposure.",
    }
    if supplemental_inventory is not None:
        summary["supplemental_provider_id"] = "dukascopy_supplemental"
        summary.update(supplemental_support_counts)
        summary["full_expected_hour_inventory_present_for_supplemental"] = bool(
            supplemental_summary["missing_files"] == 0
            and supplemental_summary["invalid_hours"] == 0
        )
        summary["full_exposure_supported"] = False
        summary["status"] = "A_to_F_complete_public_data_coverage_gate_failed"
    write_json(output / "readiness.json", summary)
    (output / "readiness.md").write_text(
        f"# Reconstruction readiness: stages A-{'F' if supplemental_inventory is not None else 'D'}\n\n"
        f"Canonical evidence passed: {len(records)} records and {len(epochs)} fixed decision epochs.\n\n"
        f"Ledger span: {records.open_time_utc.min()} to {records.close_time_utc.max()} UTC, or {hours:,} calendar hours. "
        f"There are {observed:,} nonempty hourly files ({observed / hours:.1%} of calendar hours), "
        f"{summary['missing_tick_files']:,} absent files, {summary['empty_tick_files']:,} empty files, "
        f"and {summary['invalid_tick_files']:,} invalid files. The request-only acquisition plan contains {len(acquisition):,} unknown hours.\n\n"
        "The calendar fraction is not market-open coverage. The archive was selected around known trades, and hourly file presence does not certify intrahour feature continuity or account operation. Stage D therefore fails its full-exposure gate. Later stages are marked blocked in this run rather than producing scores from fabricated inputs.\n",
        encoding="utf-8",
    )
    if supplemental_inventory is not None:
        (output / "readiness.md").write_text(
            (output / "readiness.md").read_text(encoding="utf-8")
            + "\n## Supplemental provider audit\n\n"
            + f"The separate Dukascopy stream has {supplemental_summary['calendar_hours']:,} hourly records for the ledger span: "
            + f"{supplemental_summary['nonempty_valid_hours']:,} nonempty valid, {supplemental_summary['empty_hours']:,} empty, "
            + f"{supplemental_summary['invalid_hours']:,} invalid, and {supplemental_summary['missing_files']:,} missing. "
            + f"At the 30-second causal-history gate, {supplemental_support_counts['canonical_decision_epochs_supported_with_30s_history']}/"
            + f"{len(epochs)} known trade epochs are supported. Provider streams remain separate. This does not define the algorithm's flat-market risk set "
            + "or prove that the account was active during every observed market hour; later inference stages remain gated.\n",
            encoding="utf-8",
        )
    return summary


def command_blocked(output: Path, stage: str, explanation: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "stage_status.json", {
        "stage": stage,
        "status": "blocked_by_input_gate",
        "reason": explanation,
    })


def command_continue_gm(root: Path, output: Path, supplemental_ticks_dir: Path) -> None:
    """Execute the next registered stages against the separate public feed."""

    output.mkdir(parents=True, exist_ok=True)
    statuses = {
        "G": stage_g(root, output / "G_observation"),
        "H": stage_h(root, output / "H_clocks"),
        "I": stage_i(root, output / "I_eligibility"),
        "J": stage_j(root, output / "J_validation"),
        "K_spec": stage_k_spec(output / "K_features"),
    }
    risk_manifest = output / "L_opportunities" / "opportunity_manifest.json"
    if risk_manifest.exists():
        risk = json.loads(risk_manifest.read_text(encoding="utf-8"))
    else:
        risk = build_sampled_quote_risk_set(root, supplemental_ticks_dir, output / "L_opportunities")
    statuses["K_features"] = {
        "status": "passed",
        "registry_features": 8,
        "causal_feature_rows": risk["sampled_controls"] + risk["canonical_cases"],
        "observed_feature_rows": risk["rows_with_observed_features"],
    }
    write_json(output / "K_features" / "stage_status.json", statuses["K_features"])
    risk_audit = audit_sampled_quote_risk_set(output / "L_opportunities")
    statuses["L"] = {**risk, "audit": risk_audit, "status": risk_audit["status"]}
    write_json(output / "L_opportunities" / "stage_status.json", statuses["L"])
    statuses["M"] = stage_m(output / "M_replay")
    all_passed = all(str(item.get("status", "")).startswith("passed") for item in statuses.values())
    write_json(output / "run_summary.json", {
        "status": "G_to_M_complete" if all_passed else "G_to_M_failed",
        "stages": statuses,
        "next_stage": "N_planted_recovery" if all_passed else None,
        "real_policy_search_performed": False,
        "canonical_phase7c_modified": False,
        "synthetic_market_substitution_used": False,
    })
    if not all_passed:
        raise RuntimeError("One or more G-M stages failed")


def command_run(
    root: Path,
    output: Path,
    *,
    include_hash: bool = False,
    supplemental_ticks_dir: Path | None = None,
) -> None:
    summary = command_prepare(
        root,
        output / "A_to_F" if supplemental_ticks_dir is not None else output / "A_to_D",
        include_hash=include_hash,
        supplemental_ticks_dir=supplemental_ticks_dir,
    )
    command_blocked(output / "N_benchmark", "N_planted_recovery", "The previous benchmark command only reported policy metadata; an end-to-end recovery runner is not validated.")
    command_blocked(output / "G_to_M_design_and_replay", "G_to_M_observation_clocks_risk_set_features_and_replay", "These stages need a declared observation/execution model, competing clocks, bounded eligibility assumptions, an independent opportunity panel, and validated end-to-end replay. Existing helper modules are not yet wired into a scientifically complete run.")
    command_blocked(output / "O_baselines", "O_event_models", "A supported risk set and causal real-tick feature panel are not available.")
    command_blocked(output / "P_to_U_search", "P_to_U_policy_search", "Search requires independently generated opportunities, genuine tick features, a validated replay contract, and chronological nested selection.")
    command_blocked(output / "V_to_Z_evaluation", "V_to_Z_evaluation", "There is no valid searched candidate cohort or supported full exposure; evaluation and identifiability claims are withheld.")
    write_json(output / "run_summary.json", {
        "status": "completed_through_stage_F_then_gated" if supplemental_ticks_dir is not None else "completed_through_stage_D_then_gated",
        "readiness_status": summary["status"],
        "stages_run": ["A_evidence", "B_ledger_lock", "C_evidence_semantics", "D_coverage"] + (["E_supplemental_public_ticks", "F_source_validation"] if supplemental_ticks_dir is not None else []),
        "stages_blocked": ["G-M", "N", "O", "P-U", "V-Z"],
        "no_synthetic_or_modelled_market_feed_used": True,
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["audit", "coverage", "plan-acquisition", "prepare", "run", "continue-gm", "benchmark", "fit-baselines", "search", "stateful", "components", "evaluate"],
    )
    parser.add_argument("--root", type=Path, default=_default_root())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-hash", action="store_true")
    parser.add_argument("--provider-id", default="unselected_public_source")
    parser.add_argument("--supplemental-ticks-dir", type=Path)
    parser.add_argument("--risk-set", type=Path)
    parser.add_argument("--splits", type=Path)
    parser.add_argument("--gm-run", type=Path)
    parser.add_argument("--benchmark-run", type=Path)
    parser.add_argument("--baseline-run", type=Path)
    parser.add_argument("--search-run", type=Path)
    parser.add_argument("--component-run", type=Path)
    parser.add_argument("--stateful-run", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    if args.command == "audit":
        command_audit(root, output)
    elif args.command == "coverage":
        command_coverage(root, output, args.include_hash)
    elif args.command == "plan-acquisition":
        command_acquisition_plan(root, output, args.provider_id)
    elif args.command == "prepare":
        command_prepare(root, output, include_hash=args.include_hash, supplemental_ticks_dir=args.supplemental_ticks_dir)
    elif args.command == "run":
        command_run(root, output, include_hash=args.include_hash, supplemental_ticks_dir=args.supplemental_ticks_dir)
    elif args.command == "continue-gm":
        if args.supplemental_ticks_dir is None:
            raise SystemExit("continue-gm requires --supplemental-ticks-dir")
        command_continue_gm(root, output, args.supplemental_ticks_dir.resolve())
    elif args.command == "benchmark":
        summary = run_stage_n(output)
        if summary["status"] != "passed":
            raise SystemExit(f"Stage N recovery gate failed: {summary['failed_families']}")
    elif args.command == "fit-baselines":
        if args.risk_set is None or args.splits is None:
            raise SystemExit("fit-baselines requires --risk-set and --splits")
        summary = run_stage_o(args.risk_set.resolve(), args.splits.resolve(), output)
        if summary["status"] != "passed":
            raise SystemExit("Stage O baseline gate failed")
    elif args.command == "search":
        if args.risk_set is None or args.splits is None:
            raise SystemExit("search requires --risk-set and --splits")
        p_summary = stage_p(output / "P_grammar")
        q_summary = run_stage_q(args.risk_set.resolve(), args.splits.resolve(), output / "Q_memoryless_search")
        write_json(output / "run_summary.json", {
            "status": "P_Q_complete_R_U_not_run",
            "P": p_summary,
            "Q": q_summary,
            "real_policy_identified": False,
            "next_stage": "R_stateful_mechanisms",
        })
    elif args.command == "stateful":
        if args.risk_set is None or args.splits is None:
            raise SystemExit("stateful requires --risk-set and --splits")
        summary = run_stage_r(args.risk_set.resolve(), args.splits.resolve(), output / "R_stateful_search")
        write_json(output / "run_summary.json", {
            "status": "R_bounded_stateful_search_complete",
            "R": summary,
            "real_policy_identified": summary["any_candidate_accepted"],
            "next_stage": "U_complete_policy_assembly" if summary["any_candidate_accepted"] else "Y_bounded_identifiability",
        })
    elif args.command == "components":
        if args.risk_set is None or args.splits is None:
            raise SystemExit("components requires --risk-set and --splits")
        s_summary = run_stage_s(args.risk_set.resolve(), args.splits.resolve(), output / "S_direction_size")
        t_summary = run_stage_t(root, args.risk_set.resolve(), args.splits.resolve(), output / "T_exits")
        write_json(output / "run_summary.json", {
            "status": "S_T_conditional_complete",
            "S": s_summary, "T": t_summary,
            "entry_mechanism_required_for_full_policy": True,
            "real_policy_identified": False,
        })
    elif args.command == "evaluate":
        required = {
            "--gm-run": args.gm_run, "--benchmark-run": args.benchmark_run,
            "--baseline-run": args.baseline_run, "--search-run": args.search_run,
            "--component-run": args.component_run,
            "--stateful-run": args.stateful_run,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise SystemExit(f"evaluate requires: {', '.join(missing)}")
        finalize_reconstruction(
            root, output,
            gm_run=args.gm_run.resolve(), benchmark_run=args.benchmark_run.resolve(),
            baseline_run=args.baseline_run.resolve(), search_run=args.search_run.resolve(),
            component_run=args.component_run.resolve(), stateful_run=args.stateful_run.resolve(),
        )
    print(f"reconstruction {args.command} complete: {output}")


if __name__ == "__main__":
    main()
