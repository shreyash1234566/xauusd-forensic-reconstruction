"""End-to-end integration tests for complete Algorithm Reconstruction pipeline (Stages N through Z).

Verifies:
- Complete workflow from public quotes and causal features through synthesis, replay matching, and evaluation.
- Exact recovery of planted ground-truth trading policy.
- Equivalence class clustering and divergence casebook generation.
- Placebo sensitivity calibration.
- Identifiability verdict assignment.
- Artifact export and executable Python reference generation.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd
import pytest

from reverse_trade.reconstruction.benchmarks import (
    PLANTED_BENCHMARK_REGISTRY,
    planted_bar_threshold_policy,
    planted_clock_only_policy,
)
from reverse_trade.reconstruction.event_models import (
    ContinuousPoissonB0,
    DiurnalCalendarB1,
    compute_bits_per_event,
)
from reverse_trade.reconstruction.identifiability import (
    ReconstructionVerdict,
    cluster_equivalence_classes,
    determine_identifiability_verdict,
    generate_divergence_casebook,
    run_placebo_sensitivity_test,
)
from reverse_trade.reconstruction.policy_ast import (
    Action,
    Policy,
    ThresholdCondition,
    TimeExit,
)
from reverse_trade.reconstruction.replay import Quote, ReplayEngine
from reverse_trade.reconstruction.reporting import (
    export_reconstructed_policy_package,
    generate_final_verdict_markdown,
    generate_placebo_calibration_markdown,
    generate_residual_casebook_markdown,
)
from reverse_trade.reconstruction.search import evaluate_policy
from reverse_trade.reconstruction.synthesis import SearchBudget, synthesize_beam_search


@pytest.fixture
def synthetic_simulation_environment():
    """Build a deterministic synthetic market timeline with known planted behavior."""
    times = pd.date_range("2026-01-01 10:00:00", periods=100, freq="10s", tz="UTC")
    quotes = [
        Quote(t, 2050.0 + np.sin(i * 0.1) * 2.0, 2050.1 + np.sin(i * 0.1) * 2.0)
        for i, t in enumerate(times)
    ]

    # Feature with distinct excursions
    ret_values = [0.001 if (i % 20 == 5) else -0.0002 for i in range(len(times))]
    features = pd.DataFrame({
        "decision_time_utc": times,
        "hour_utc": [t.hour for t in times],
        "day_of_week": [t.dayofweek for t in times],
        "ret5": ret_values,
        "spread": [0.1] * len(times),
        "feature_status": "observed",
    })

    # Ground truth planted policy: Buy when ret5 > 0.0005
    ground_truth_policy = Policy(
        ThresholdCondition("ret5", ">", 0.0005),
        Action.OPEN_BUY,
        volume=0.01,
        cooldown_seconds=30.0,
        exit_rule=TimeExit(holding_seconds=15.0),
        name="ground_truth_planted",
    )

    engine = ReplayEngine(ground_truth_policy)
    observed_trades, _ = engine.run(quotes, features)
    observed_epochs = observed_trades.rename(columns={"open_time_utc": "decision_time_utc"})

    return quotes, features, observed_epochs, ground_truth_policy


def test_full_reconstruction_pipeline_end_to_end(synthetic_simulation_environment):
    quotes, features, observed_epochs, gt_policy = synthetic_simulation_environment
    assert len(observed_epochs) > 0

    # 1. Program Synthesis & Beam Search
    budget = SearchBudget(
        max_thresholds_per_feature=5,
        cooldowns_seconds=(0.0, 30.0),
        volumes=(0.01,),
        directions=(Action.OPEN_BUY, Action.OPEN_SELL),
    )
    candidates = synthesize_beam_search(
        features,
        quotes,
        observed_epochs,
        features=["ret5", "spread"],
        beam_width=10,
        max_depth=1,
        budget=budget,
    )
    assert len(candidates) > 0

    # 2. Candidate Evaluation
    evaluations = [
        evaluate_policy(f"cand-{idx:03d}", cand, quotes, features, observed_epochs)
        for idx, cand in enumerate(candidates)
    ]
    evaluations.sort(key=lambda e: (float(e.metrics.get("entry_error_loss", 1.0)), -float(e.metrics.get("f1", 0.0))))

    top_cand_eval = evaluations[0]
    assert float(top_cand_eval.metrics.get("f1", 0.0)) == 1.0
    assert float(top_cand_eval.metrics.get("entry_error_loss", 1.0)) == 0.0

    # 3. Equivalence Class Clustering
    eq_classes = cluster_equivalence_classes(evaluations, time_tolerance_seconds=5.0)
    assert len(eq_classes) >= 1

    # 4. Divergence Casebook Generation
    casebook = generate_divergence_casebook(top_cand_eval, features, observed_epochs)
    assert isinstance(casebook, pd.DataFrame)
    assert len(casebook) == 0  # Perfect match has 0 divergence cases

    # 5. Placebo Sensitivity Testing
    placebo_res = run_placebo_sensitivity_test(top_cand_eval, observed_epochs, num_replications=15, random_seed=42)
    assert placebo_res.replications == 15
    assert placebo_res.real_f1 == 1.0

    # 6. Identifiability Verdict Assignment
    summary = determine_identifiability_verdict(
        evaluations,
        eq_classes,
        total_canonical_epochs=len(observed_epochs),
        supported_observed_epochs=len(observed_epochs),
    )
    assert summary.verdict == ReconstructionVerdict.EXACT_FINITE_HISTORY_COMPATIBILITY
    assert summary.top_candidate_f1 == 1.0

    # 7. Reporting & Artifact Packaging
    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)

        # Markdown reports
        verdict_md = generate_final_verdict_markdown(summary)
        assert "EXACT_FINITE_HISTORY_COMPATIBILITY" in verdict_md.upper() or "exact_finite_history_compatibility" in verdict_md

        casebook_md = generate_residual_casebook_markdown(casebook)
        assert "Zero divergence cases cataloged" in casebook_md

        placebo_md = generate_placebo_calibration_markdown([placebo_res])
        assert "Placebo Sensitivity" in placebo_md

        # Export package
        pkg_paths = export_reconstructed_policy_package(candidates[0], top_cand_eval, tmp_dir)
        assert pkg_paths["policy_json"].exists()
        assert pkg_paths["executable_py"].exists()
        assert pkg_paths["predicted_trades"].exists()
        assert pkg_paths["trade_matches"].exists()

        # Verify JSON policy structure
        with open(pkg_paths["policy_json"], "r", encoding="utf-8") as f:
            data = json.load(f)
            assert "condition" in data
            assert "side" in data
            assert data["side"] == "open_buy"
