import numpy as np
import pandas as pd
import pytest

from reverse_trade.reconstruction.identifiability import (
    EquivalenceClass,
    IdentifiabilitySummary,
    PlaceboTestResult,
    ReconstructionVerdict,
    cluster_equivalence_classes,
    determine_identifiability_verdict,
    generate_divergence_casebook,
    run_placebo_sensitivity_test,
)
from reverse_trade.reconstruction.policy_ast import Action, Policy, ThresholdCondition, TimeExit
from reverse_trade.reconstruction.search import CandidateEvaluation


@pytest.fixture
def sample_evaluations() -> list[CandidateEvaluation]:
    times = pd.date_range("2026-01-01 12:00:00", periods=5, freq="10s", tz="UTC")
    preds1 = pd.DataFrame({"open_time_utc": times, "side": "Buy", "volume": 0.01})
    preds2 = pd.DataFrame({"open_time_utc": times + pd.Timedelta(seconds=5), "side": "Buy", "volume": 0.01})
    preds3 = pd.DataFrame({"open_time_utc": times + pd.Timedelta(seconds=120), "side": "Sell", "volume": 0.01})

    matches = pd.DataFrame([
        {"status": "tp", "observed_index": 0, "predicted_index": 0},
        {"status": "fp", "observed_index": None, "predicted_index": 1},
        {"status": "fn", "observed_index": 2, "predicted_index": None},
    ])

    ev1 = CandidateEvaluation(
        candidate_id="cand-001",
        metrics={"f1": 0.8, "entry_error_loss": 0.2, "tp": 4, "fp": 1, "fn": 1},
        matches=matches,
        predictions=preds1,
        trace=pd.DataFrame(),
    )
    ev2 = CandidateEvaluation(
        candidate_id="cand-002",
        metrics={"f1": 0.8, "entry_error_loss": 0.2, "tp": 4, "fp": 1, "fn": 1},
        matches=matches,
        predictions=preds2,
        trace=pd.DataFrame(),
    )
    ev3 = CandidateEvaluation(
        candidate_id="cand-003",
        metrics={"f1": 0.2, "entry_error_loss": 0.8, "tp": 1, "fp": 4, "fn": 4},
        matches=matches,
        predictions=preds3,
        trace=pd.DataFrame(),
    )
    return [ev1, ev2, ev3]


def test_cluster_equivalence_classes(sample_evaluations):
    classes = cluster_equivalence_classes(sample_evaluations, time_tolerance_seconds=10.0)
    assert len(classes) == 2
    # cand-001 and cand-002 are within 5s tolerance, so clustered together
    assert classes[0].size == 2
    assert "cand-001" in classes[0].member_candidate_ids
    assert "cand-002" in classes[0].member_candidate_ids
    assert classes[1].size == 1
    assert "cand-003" in classes[1].member_candidate_ids


def test_generate_divergence_casebook(sample_evaluations):
    ev = sample_evaluations[0]
    times = pd.date_range("2026-01-01 12:00:00", periods=5, freq="10s", tz="UTC")
    features = pd.DataFrame({"decision_time_utc": times, "ret5": [0.001, -0.002, 0.003, 0.004, -0.001]})
    observed = pd.DataFrame({
        "decision_time_utc": times,
        "side": ["Buy", "Buy", "Sell", "Buy", "Buy"],
        "volume": [0.01] * 5,
    })

    casebook = generate_divergence_casebook(ev, features, observed, max_cases=10)
    assert not casebook.empty
    assert "status" in casebook.columns
    assert "FN" in casebook["status"].values
    assert "FP" in casebook["status"].values


def test_run_placebo_sensitivity_test(sample_evaluations):
    ev = sample_evaluations[0]
    times = pd.date_range("2026-01-01 12:00:00", periods=20, freq="10min", tz="UTC")
    preds = pd.DataFrame({"open_time_utc": times[:5], "side": "Buy", "volume": 0.01})
    ev_with_preds = CandidateEvaluation(
        candidate_id=ev.candidate_id,
        metrics={"f1": 0.9, "entry_error_loss": 0.1, "tp": 5, "fp": 0, "fn": 0},
        matches=ev.matches,
        predictions=preds,
        trace=ev.trace,
    )
    observed = pd.DataFrame({
        "decision_time_utc": times[:5],
        "side": ["Buy"] * 5,
        "volume": [0.01] * 5,
    })

    res = run_placebo_sensitivity_test(ev_with_preds, observed, num_replications=10, random_seed=42)
    assert isinstance(res, PlaceboTestResult)
    assert res.replications == 10
    assert 0.0 <= res.p_value_f1 <= 1.0


def test_determine_identifiability_verdict_exact(sample_evaluations):
    exact_eval = CandidateEvaluation(
        candidate_id="exact-01",
        metrics={
            "f1": 1.0, "entry_error_loss": 0.0, "tp": 420, "fp": 0, "fn": 0,
            "predicted": 420, "unknown_opportunities": 0, "unsupported_observed_epochs": 0,
        },
        matches=sample_evaluations[0].matches,
        predictions=sample_evaluations[0].predictions,
        trace=sample_evaluations[0].trace,
    )
    summary = determine_identifiability_verdict([exact_eval], [], total_canonical_epochs=420, supported_observed_epochs=420)
    assert summary.verdict == ReconstructionVerdict.EXACT_FINITE_HISTORY_COMPATIBILITY
    assert summary.top_candidate_f1 == 1.0


def test_determine_identifiability_verdict_equivalence(sample_evaluations):
    eq_class = EquivalenceClass(
        class_id="EQ-001",
        member_candidate_ids=["cand-001", "cand-002"],
        representative_candidate_id="cand-001",
        size=2,
        mean_f1=0.8,
        mean_entry_loss=0.2,
        shared_features=["ret5"],
    )
    summary = determine_identifiability_verdict(sample_evaluations, [eq_class], total_canonical_epochs=420, supported_observed_epochs=420)
    assert summary.verdict == ReconstructionVerdict.OBSERVATIONAL_EQUIVALENCE_CLASS


def test_determine_identifiability_verdict_unsupported():
    summary = determine_identifiability_verdict([], [], total_canonical_epochs=420, supported_observed_epochs=150)
    assert summary.verdict == ReconstructionVerdict.INSUFFICIENT_OBSERVATION
