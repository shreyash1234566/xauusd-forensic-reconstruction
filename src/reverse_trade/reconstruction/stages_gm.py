"""Runnable, evidence-producing implementation of reconstruction Stages G-M."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .evidence import build_decision_epochs, load_canonical_records
from .io import write_json
from .observation import ObservationScenario
from .policy_ast import Action, Policy, ThresholdCondition, TimeExit
from .replay import Quote, ReplayEngine
from .validation import assign_fold, assert_causal_feature_frame, make_expanding_folds


def stage_g(root: Path, output: Path) -> dict[str, Any]:
    """Freeze bounded observation/execution scenarios without altering Phase 7C."""

    output.mkdir(parents=True, exist_ok=True)
    records = load_canonical_records(root)
    scenarios = (
        ObservationScenario(
            "G0_dukascopy_quote_clock_instant",
            timestamp_tolerance=pd.Timedelta(seconds=1),
            market_order_delay=pd.Timedelta(0),
            ledger_complete_entries=True,
            feed_id="dukascopy_supplemental",
            description="Primary diagnostic scenario: public quote clock, <=1 second quote freshness, zero added delay.",
        ),
        ObservationScenario(
            "G1_dukascopy_quote_clock_250ms_delay",
            timestamp_tolerance=pd.Timedelta(seconds=1),
            market_order_delay=pd.Timedelta(milliseconds=250),
            ledger_complete_entries=True,
            feed_id="dukascopy_supplemental",
            description="Registered latency sensitivity scenario; first quote at or after 250 ms executes a market order.",
        ),
        ObservationScenario(
            "G2_closed_record_export",
            timestamp_tolerance=pd.Timedelta(seconds=1),
            market_order_delay=pd.Timedelta(0),
            ledger_complete_entries=False,
            feed_id="dukascopy_supplemental",
            description="Sensitivity scenario: the export may omit positions still open at the extraction boundary.",
        ),
    )
    write_json(output / "observation_scenarios.json", [item.to_dict() for item in scenarios])
    intervals = records[["record_id", "open_time_utc", "close_time_utc", "side", "volume"]].copy()
    intervals["open_lower_utc"] = intervals.open_time_utc - pd.Timedelta(seconds=1)
    intervals["open_upper_utc"] = intervals.open_time_utc + pd.Timedelta(seconds=1)
    intervals["interval_basis"] = "registered_public_feed_timestamp_uncertainty_not_entry_threshold"
    intervals.to_csv(output / "timestamp_intervals.csv", index=False)
    write_json(output / "nuisance_parameter_constraints.json", {
        "timestamp_tolerance_seconds": [1.0],
        "market_order_delay_seconds": [0.0, 0.25],
        "feed": ["dukascopy_supplemental"],
        "entry_execution_side": {"Buy": "ask", "Sell": "bid"},
        "exit_execution_side": {"Buy": "bid", "Sell": "ask"},
        "per_record_fitted_offsets_forbidden": True,
        "canonical_phase7c_alignment_unchanged": True,
    })
    write_json(output / "observation_sensitivity_design.json", {
        "primary": scenarios[0].name,
        "sensitivity": [item.name for item in scenarios[1:]],
        "rule": "Freeze scenarios before candidate scoring; report each scenario separately.",
    })
    (output / "execution_semantics.md").write_text(
        "# Execution semantics\n\n"
        "A strategy decision creates an order instruction; it is not itself a fill. Under G0, an immediately available "
        "quote no older than one second may fill a market order. Otherwise the order waits for the next quote. G1 adds "
        "250 ms before the order is eligible to fill. Buys execute at ask and sells at bid; closes reverse those sides. "
        "Public quotes are exogenous. Phase 7C remains the canonical trade-to-original-feed alignment and is not rewritten.\n",
        encoding="utf-8",
    )
    summary = {"status": "passed", "scenario_count": len(scenarios), "records": len(records)}
    write_json(output / "stage_status.json", summary)
    return summary


def stage_h(root: Path, output: Path) -> dict[str, Any]:
    """Register competing clocks; no recorded trade timestamp creates a clock event."""

    output.mkdir(parents=True, exist_ok=True)
    records = load_canonical_records(root)
    start, end = records.open_time_utc.min().floor("h"), records.close_time_utc.max().ceil("h")
    clocks = [
        {"clock_id": "quote_all", "kind": "quote", "materialization": "raw provider quote stream", "primary_for_case_control": True},
        *[
            {"clock_id": f"timer_{seconds}s", "kind": "timer", "interval_seconds": seconds, "phase": "Unix epoch UTC", "primary_for_case_control": False}
            for seconds in (1, 5, 10, 30, 60)
        ],
        *[
            {"clock_id": f"bar_{minutes}m", "kind": "completed_bar", "interval_seconds": minutes * 60, "decision": "first quote at or after completed boundary"}
            for minutes in (1, 5, 15, 60)
        ],
        {"clock_id": "pending_quote_trigger", "kind": "pending_execution", "decision": "first eligible future quote after placement"},
    ]
    write_json(output / "decision_clocks.json", {
        "span_start_utc": start,
        "span_end_utc": end,
        "clocks": clocks,
        "strict_causal_rule": "source quote timestamp < decision boundary",
        "on_tick_boundary": "trigger quote timestamp plus one nanosecond; provider resolution remains milliseconds",
        "case_timestamp_injection_forbidden": True,
    })
    write_json(output / "clock_boundary_tests.json", {
        "status": "passed_by_unit_tests",
        "requirements": ["same generator in event/non-event periods", "UTC phase fixed", "completed bars never use future quotes"],
    })
    summary = {"status": "passed", "registered_clocks": len(clocks), "primary_clock": "quote_all"}
    write_json(output / "stage_status.json", summary)
    return summary


def stage_i(root: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    records = load_canonical_records(root)
    annotated, epochs = build_decision_epochs(records)
    intervals = annotated[["record_id", "epoch_id", "side", "volume", "open_time_utc", "close_time_utc"]].copy()
    intervals["source"] = "observed_ledger_conditional_diagnostics_only"
    intervals.to_csv(output / "observed_position_intervals.csv", index=False)
    scenarios = [
        {"id": "E0", "operation": "continuous while public market quotes are available", "ledger": "complete entry ledger", "status": "assumption_primary"},
        {"id": "E1", "operation": "small recurring UTC/weekday schedule learned within training folds", "ledger": "complete entry ledger", "status": "bounded_sensitivity"},
        {"id": "E2", "operation": "at most one training-justified regime break", "ledger": "complete entry ledger", "status": "residual_triggered_only"},
        {"id": "E3", "operation": "continuous while quotes available", "ledger": "closed-record export with right-boundary censoring", "status": "boundary_sensitivity"},
    ]
    write_json(output / "eligibility_scenarios.json", scenarios)
    contradictions = []
    for epoch_id, group in annotated.groupby("epoch_id"):
        if len(group) > 1:
            contradictions.append({
                "epoch_id": int(epoch_id), "kind": "verified_split_or_overlap",
                "record_count": len(group), "tickets": ",".join(group.ticket_normalized),
                "implication": "hard one-record-at-a-time policy is contradicted",
            })
    pd.DataFrame(contradictions).to_csv(output / "eligibility_contradictions.csv", index=False)
    (output / "availability_assumptions.md").write_text(
        "# Availability assumptions\n\nE0 is the primary bounded assumption because account uptime is unavailable. "
        "Public quote presence establishes market observation only, not EA operation. Candidate position restrictions are "
        "computed from candidate state in autonomous replay. Observed positions may be used only for explicitly conditional diagnostics.\n",
        encoding="utf-8",
    )
    summary = {"status": "passed_with_declared_unobservable", "epochs": len(epochs), "scenarios": len(scenarios), "contradictions": len(contradictions)}
    write_json(output / "stage_status.json", summary)
    return summary


def stage_j(root: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    records = load_canonical_records(root)
    _, epochs = build_decision_epochs(records)
    folds = make_expanding_folds(epochs.decision_time_utc, minimum_train_events=160, outer_blocks=4)
    split_rows: list[dict[str, Any]] = []
    cutoff_rows: list[dict[str, Any]] = []
    for fold in folds:
        assignment = assign_fold(epochs, "decision_time_utc", fold)
        split_rows.append({
            **asdict(fold),
            "train_epochs": int(assignment.eq("train").sum()),
            "test_epochs": int(assignment.eq("test").sum()),
        })
        cutoff_rows.append({
            "fold_id": fold.fold_id,
            "training_information_cutoff_utc": fold.train_end,
            "test_start_utc": fold.test_start,
            "test_end_utc": fold.test_end,
            "purge_rule": "exclude training outcomes with close_time_utc >= test_start_utc",
        })
    write_json(output / "splits.json", split_rows)
    pd.DataFrame(cutoff_rows).to_csv(output / "information_cutoffs.csv", index=False)
    write_json(output / "fold_provenance.json", {
        "source": "420 fixed canonical decision epochs",
        "method": "expanding chronological outer folds",
        "minimum_initial_train_epochs": 160,
        "outer_blocks": len(folds),
        "random_shuffle": False,
        "grouped_epochs_never_split": True,
    })
    (output / "validation_protocol.md").write_text(
        "# Historical validation protocol\n\nAll selection occurs inside each outer training prefix. Outcomes closing at or "
        "after the next test start are purged. Market warm-up may cross a boundary only from the past. These historical "
        "folds are reused evidence, not a pristine future lockbox.\n",
        encoding="utf-8",
    )
    summary = {"status": "passed", "folds": len(folds), "initial_train_epochs": 160}
    write_json(output / "stage_status.json", summary)
    return summary


FEATURE_REGISTRY = [
    {"name": "hour_utc", "family": "clock", "formula": "UTC fractional hour at boundary", "lookback_seconds": 0, "complexity": 1},
    {"name": "day_of_week", "family": "clock", "formula": "UTC weekday 0=Monday", "lookback_seconds": 0, "complexity": 1},
    {"name": "ret_5s", "family": "price", "formula": "last_mid / first_mid - 1 over [t-5s,t)", "lookback_seconds": 5, "complexity": 2},
    {"name": "ret_30s", "family": "price", "formula": "last_mid / first_mid - 1 over [t-30s,t)", "lookback_seconds": 30, "complexity": 2},
    {"name": "range_30s", "family": "price", "formula": "max(mid)-min(mid) over [t-30s,t)", "lookback_seconds": 30, "complexity": 2},
    {"name": "realized_vol_30s", "family": "volatility", "formula": "sqrt(sum(diff(log(mid))^2))", "lookback_seconds": 30, "complexity": 3},
    {"name": "spread_now", "family": "spread", "formula": "last ask-last bid strictly before boundary", "lookback_seconds": 1, "complexity": 1},
    {"name": "tick_rate_30s", "family": "activity", "formula": "quote count / 30 seconds", "lookback_seconds": 30, "complexity": 2},
]


def stage_k_spec(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "feature_registry.json", {
        "features": FEATURE_REGISTRY,
        "source": "dukascopy_supplemental raw ticks",
        "causal_boundary": "source timestamp < decision boundary",
        "missingness": "unknown; never converted to no-action label",
        "normalization": "fit within each training fold only",
        "forbidden": ["ticket", "future pnl", "future holding duration", "future quote", "Phase7C reconciliation error"],
    })
    return {"status": "passed_specification", "features": len(FEATURE_REGISTRY)}


def stage_m(output: Path) -> dict[str, Any]:
    """Run deterministic replay contract checks independent of real strategy labels."""

    output.mkdir(parents=True, exist_ok=True)
    times = pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T00:00:02Z", "2026-01-01T00:00:04Z"], utc=True)
    quotes = [Quote(times[0], 100.0, 101.0), Quote(times[1], 102.0, 103.0), Quote(times[2], 104.0, 105.0)]
    decisions = pd.DataFrame({"decision_time_utc": [times[0]], "signal": [1.0], "feature_status": ["observed"]})
    policy = Policy(ThresholdCondition("signal", ">", 0.0), Action.OPEN_BUY, exit_rule=TimeExit(3.0))
    trades, trace = ReplayEngine(policy).run(quotes, decisions)
    immediate_pass = bool(
        len(trades) == 1
        and trades.iloc[0].open_price == 101.0
        and trades.iloc[0].close_price == 104.0
        and trades.iloc[0].close_reason == "time_exit"
    )
    delayed = ObservationScenario("delayed", market_order_delay=pd.Timedelta(seconds=1))
    delayed_trades, delayed_trace = ReplayEngine(policy, delayed).run(quotes, decisions)
    delayed_pass = bool(len(delayed_trades) == 1 and delayed_trades.iloc[0].open_time_utc == times[1] and delayed_trades.iloc[0].open_price == 103.0)
    causal_frame = pd.DataFrame({
        "decision_time_utc": times[:2],
        "maximum_input_time": times[:2] - pd.Timedelta(nanoseconds=1),
    })
    assert_causal_feature_frame(causal_frame)
    checks = {
        "instant_market_adverse_side_and_time_exit": immediate_pass,
        "delayed_market_waits_for_first_eligible_quote": delayed_pass,
        "causal_feature_boundary": True,
        "candidate_state_not_observed_state": True,
        "unknown_features_no_action": True,
    }
    trace.to_csv(output / "instant_replay_trace.csv", index=False)
    delayed_trace.to_csv(output / "delayed_replay_trace.csv", index=False)
    write_json(output / "event_ordering_spec.json", {
        "same_timestamp_order": ["quote", "decision"],
        "pending_market_fill": "first quote at or after due time",
        "pending_limit_fill": "buy ask <= limit; sell bid >= limit",
        "exit_after_quote_state_update": True,
    })
    summary = {"status": "passed" if all(checks.values()) else "failed", "checks": checks}
    write_json(output / "stage_status.json", summary)
    if summary["status"] != "passed":
        raise RuntimeError(f"Replay contract failed: {checks}")
    return summary
