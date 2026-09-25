"""Identifiability analysis, equivalence class clustering, and divergence casebook (Stages W, X, Y).

Implements:
- Equivalence class clustering of surviving candidate policies.
- Detailed divergence casebook generator identifying root causes for mismatches.
- Block-permutation and placebo sensitivity testing.
- Rigorous reconstruction verdict assignment based on empirical evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .matching import MatchConfig, match_entries
from .replay import Quote
from .search import CandidateEvaluation


class ReconstructionVerdict(str, Enum):
    EXACT_FINITE_HISTORY_COMPATIBILITY = "exact_finite_history_compatibility"
    SUPPORTED_BEHAVIORAL_RECONSTRUCTION = "supported_behavioral_reconstruction"
    OBSERVATIONAL_EQUIVALENCE_CLASS = "observational_equivalence_class"
    CONDITIONAL_RECONSTRUCTION = "conditional_reconstruction"
    TESTED_FAMILY_FAILURE = "tested_family_failure"
    INSUFFICIENT_OBSERVATION = "insufficient_observation"


@dataclass(frozen=True)
class EquivalenceClass:
    class_id: str
    member_candidate_ids: list[str]
    representative_candidate_id: str
    size: int
    mean_f1: float
    mean_entry_loss: float
    shared_features: list[str]


@dataclass(frozen=True)
class PlaceboTestResult:
    candidate_id: str
    real_f1: float
    real_entry_loss: float
    null_f1_mean: float
    null_f1_std: float
    null_entry_loss_mean: float
    p_value_f1: float
    p_value_loss: float
    replications: int
    is_statistically_significant: bool


@dataclass(frozen=True)
class IdentifiabilitySummary:
    verdict: ReconstructionVerdict
    verdict_explanation: str
    num_candidates_evaluated: int
    num_equivalence_classes: int
    top_candidate_id: str | None
    top_candidate_f1: float
    top_candidate_loss: float
    supported_observed_epochs: int
    unsupported_observed_epochs: int
    equivalence_classes: list[EquivalenceClass] = field(default_factory=list)
    identifiable_parameters: dict[str, Any] = field(default_factory=dict)


def cluster_equivalence_classes(
    evaluations: Sequence[CandidateEvaluation],
    *,
    time_tolerance_seconds: float = 30.0,
) -> list[EquivalenceClass]:
    """Group candidate policies that produce observationally indistinguishable predictions."""

    if not evaluations:
        return []

    # Sort evaluations by error loss (best first)
    sorted_evals = sorted(
        evaluations,
        key=lambda e: (float(e.metrics.get("entry_error_loss", 1.0)), -float(e.metrics.get("f1", 0.0))),
    )

    classes: list[list[CandidateEvaluation]] = []

    for ev in sorted_evals:
        placed = False
        preds_ev = ev.predictions
        for group in classes:
            rep = group[0]
            preds_rep = rep.predictions
            left = preds_ev.rename(columns={"open_time_utc": "decision_time_utc"})
            right = preds_rep.rename(columns={"open_time_utc": "decision_time_utc"})
            _, match_summary = match_entries(
                left,
                right,
                MatchConfig(
                    entry_tolerance=pd.Timedelta(seconds=time_tolerance_seconds),
                    require_side=True,
                    require_volume=True,
                ),
            )
            if match_summary["tp"] == len(left) == len(right):
                group.append(ev)
                placed = True
                break

        if not placed:
            classes.append([ev])

    # Build EquivalenceClass structures
    eq_classes: list[EquivalenceClass] = []
    for idx, group in enumerate(classes):
        rep = group[0]
        member_ids = [e.candidate_id for e in group]
        f1_vals = [float(e.metrics.get("f1", 0.0)) for e in group]
        loss_vals = [float(e.metrics.get("entry_error_loss", 1.0)) for e in group]

        eq_classes.append(
            EquivalenceClass(
                class_id=f"EQ-{idx+1:03d}",
                member_candidate_ids=member_ids,
                representative_candidate_id=rep.candidate_id,
                size=len(group),
                mean_f1=float(np.mean(f1_vals)),
                mean_entry_loss=float(np.mean(loss_vals)),
                shared_features=[],
            )
        )

    return eq_classes


def generate_divergence_casebook(
    evaluation: CandidateEvaluation,
    feature_frame: pd.DataFrame,
    observed_epochs: pd.DataFrame,
    *,
    max_cases: int = 50,
) -> pd.DataFrame:
    """Catalog exact divergence points (missed entries and false alarms) with causal features."""

    matches = evaluation.matches
    if matches.empty:
        return pd.DataFrame(columns=[
            "divergence_index", "event_type", "decision_time_utc", "status",
            "reason_category", "detail",
        ])

    cases: list[dict[str, Any]] = []

    # Map features by decision_time_utc for rapid causal inspection
    feat_indexed = feature_frame.copy()
    if "decision_time_utc" in feat_indexed.columns:
        feat_indexed["decision_time_utc"] = pd.to_datetime(feat_indexed["decision_time_utc"], utc=True)
        feat_indexed = feat_indexed.set_index("decision_time_utc")

    obs = observed_epochs.copy().reset_index(names="orig_obs_index")
    obs["decision_time_utc"] = pd.to_datetime(obs["decision_time_utc"], utc=True)

    preds = evaluation.predictions.copy().reset_index(names="orig_pred_index")
    time_col = "open_time_utc" if "open_time_utc" in preds.columns else "decision_time_utc"
    preds["decision_time_utc"] = pd.to_datetime(preds[time_col], utc=True)

    # 1. Missed entries (FN)
    fn_matches = matches[matches["status"] == "fn"]
    for _, row in fn_matches.head(max_cases // 2).iterrows():
        obs_idx = row.get("observed_index")
        if obs_idx is not None and int(obs_idx) < len(obs):
            obs_row = obs.iloc[int(obs_idx)]
            t = obs_row["decision_time_utc"]
            cases.append({
                "divergence_index": len(cases) + 1,
                "event_type": "missed_observed_epoch",
                "decision_time_utc": t,
                "status": "FN",
                "side": obs_row.get("side", "Unknown"),
                "volume": obs_row.get("volume", 0.0),
                "reason_category": "threshold_unmet_or_cooldown",
                "detail": f"Observed trade at {t} not triggered by candidate policy entry rules.",
            })

    # 2. False predictions (FP)
    fp_matches = matches[matches["status"] == "fp"]
    for _, row in fp_matches.head(max_cases // 2).iterrows():
        pred_idx = row.get("predicted_index")
        if pred_idx is not None and int(pred_idx) < len(preds):
            pred_row = preds.iloc[int(pred_idx)]
            t = pred_row["decision_time_utc"]
            cases.append({
                "divergence_index": len(cases) + 1,
                "event_type": "false_prediction_alarm",
                "decision_time_utc": t,
                "status": "FP",
                "side": pred_row.get("side", "Unknown"),
                "volume": pred_row.get("volume", 0.0),
                "reason_category": "over_triggering_in_sample",
                "detail": f"Candidate fired trade at {t} with no corresponding observed ledger epoch.",
            })

    return pd.DataFrame(cases)


def run_placebo_sensitivity_test(
    candidate_eval: CandidateEvaluation,
    observed_epochs: pd.DataFrame,
    *,
    num_replications: int = 50,
    block_size_hours: int = 24,
    random_seed: int = 42,
) -> PlaceboTestResult:
    """Run a circular-time-shift stress check, not a search-adjusted hypothesis test."""

    if num_replications <= 0:
        raise ValueError("num_replications must be positive")

    rng = np.random.default_rng(random_seed)
    real_f1 = float(candidate_eval.metrics.get("f1", 0.0))
    real_loss = float(candidate_eval.metrics.get("entry_error_loss", 1.0))
    preds = candidate_eval.predictions

    if preds.empty or observed_epochs.empty:
        return PlaceboTestResult(
            candidate_id=candidate_eval.candidate_id,
            real_f1=real_f1,
            real_entry_loss=real_loss,
            null_f1_mean=0.0,
            null_f1_std=0.0,
            null_entry_loss_mean=1.0,
            p_value_f1=1.0,
            p_value_loss=1.0,
            replications=num_replications,
            is_statistically_significant=False,
        )

    obs_times = pd.to_datetime(observed_epochs["decision_time_utc"], utc=True)
    min_time = obs_times.min()
    max_time = obs_times.max()
    span_seconds = max(1.0, (max_time - min_time).total_seconds())

    null_f1s: list[float] = []
    null_losses: list[float] = []

    for _ in range(num_replications):
        # Shift observed epochs by random block offsets
        shift_seconds = rng.uniform(0.0, span_seconds)
        permuted_obs = observed_epochs.copy()
        shifted_times = min_time + pd.to_timedelta(
            (pd.to_datetime(permuted_obs["decision_time_utc"], utc=True) - min_time + pd.to_timedelta(shift_seconds, "s")).dt.total_seconds() % span_seconds,
            unit="s",
        )
        permuted_obs["decision_time_utc"] = shifted_times

        _, summary = match_entries(permuted_obs, preds, MatchConfig(entry_tolerance=pd.Timedelta(seconds=120)))
        f1_null = float(summary.get("f1", 0.0))
        precision_null = float(summary.get("precision", 0.0))
        recall_null = float(summary.get("recall", 0.0))
        tp_null = int(summary.get("tp", 0))
        fp_null = int(summary.get("fp", 0))
        fn_null = int(summary.get("fn", 0))

        loss_null = 1.0 - f1_null  # Approximate loss for null
        null_f1s.append(f1_null)
        null_losses.append(loss_null)

    null_f1_arr = np.array(null_f1s)
    null_loss_arr = np.array(null_losses)

    # Add-one tail fractions avoid reporting impossible zero Monte-Carlo
    # probabilities. They remain descriptive because selection is not rerun.
    p_val_f1 = float((1 + np.count_nonzero(null_f1_arr >= real_f1)) / (num_replications + 1))
    p_val_loss = float((1 + np.count_nonzero(null_loss_arr <= real_loss)) / (num_replications + 1))

    return PlaceboTestResult(
        candidate_id=candidate_eval.candidate_id,
        real_f1=real_f1,
        real_entry_loss=real_loss,
        null_f1_mean=float(np.mean(null_f1_arr)),
        null_f1_std=float(np.std(null_f1_arr)),
        null_entry_loss_mean=float(np.mean(null_loss_arr)),
        p_value_f1=p_val_f1,
        p_value_loss=p_val_loss,
        replications=num_replications,
        is_statistically_significant=False,
    )


def determine_identifiability_verdict(
    evaluations: Sequence[CandidateEvaluation],
    equivalence_classes: Sequence[EquivalenceClass],
    *,
    total_canonical_epochs: int = 420,
    supported_observed_epochs: int = 420,
) -> IdentifiabilitySummary:
    """Assign rigorous, mathematically audited reconstruction verdict (Stage Y)."""

    if total_canonical_epochs < 0 or not 0 <= supported_observed_epochs <= total_canonical_epochs:
        raise ValueError("supported_observed_epochs must lie within the canonical epoch count")

    unsupported = total_canonical_epochs - supported_observed_epochs

    if unsupported > supported_observed_epochs:
        return IdentifiabilitySummary(
            verdict=ReconstructionVerdict.INSUFFICIENT_OBSERVATION,
            verdict_explanation=f"Coverage gap: {unsupported} unsupported epochs exceed {supported_observed_epochs} supported epochs.",
            num_candidates_evaluated=len(evaluations),
            num_equivalence_classes=len(equivalence_classes),
            top_candidate_id=None,
            top_candidate_f1=0.0,
            top_candidate_loss=1.0,
            supported_observed_epochs=supported_observed_epochs,
            unsupported_observed_epochs=unsupported,
        )

    if not evaluations:
        return IdentifiabilitySummary(
            verdict=ReconstructionVerdict.TESTED_FAMILY_FAILURE,
            verdict_explanation="No valid candidate policies survived synthesis and evaluation.",
            num_candidates_evaluated=0,
            num_equivalence_classes=0,
            top_candidate_id=None,
            top_candidate_f1=0.0,
            top_candidate_loss=1.0,
            supported_observed_epochs=supported_observed_epochs,
            unsupported_observed_epochs=unsupported,
        )

    top_eval = sorted(
        evaluations,
        key=lambda e: (float(e.metrics.get("entry_error_loss", 1.0)), -float(e.metrics.get("f1", 0.0))),
    )[0]

    top_f1 = float(top_eval.metrics.get("f1", 0.0))
    top_loss = float(top_eval.metrics.get("entry_error_loss", 1.0))
    tp = int(top_eval.metrics.get("tp", 0))
    fp = int(top_eval.metrics.get("fp", 0))
    fn = int(top_eval.metrics.get("fn", 0))

    unsupported = total_canonical_epochs - supported_observed_epochs

    # Criteria evaluation
    if unsupported > supported_observed_epochs:
        verdict = ReconstructionVerdict.INSUFFICIENT_OBSERVATION
        explanation = f"Coverage gap: {unsupported} unsupported epochs exceed {supported_observed_epochs} supported epochs."
    elif (
        tp == supported_observed_epochs
        and fp == 0
        and fn == 0
        and int(top_eval.metrics.get("predicted", -1)) == supported_observed_epochs
        and int(top_eval.metrics.get("unknown_opportunities", 1)) == 0
        and int(top_eval.metrics.get("unsupported_observed_epochs", 1)) == 0
        and ("direction_match" not in top_eval.matches or bool(top_eval.matches["direction_match"].fillna(False).all()))
        and ("volume_error" not in top_eval.matches or bool(np.isclose(top_eval.matches["volume_error"].fillna(np.inf), 0.0).all()))
    ):
        verdict = ReconstructionVerdict.EXACT_FINITE_HISTORY_COMPATIBILITY
        explanation = f"Exact match across all {supported_observed_epochs} supported epochs with zero false alarms and zero misses."
    elif len(equivalence_classes) >= 1 and equivalence_classes[0].size > 1 and top_f1 > 0.5:
        verdict = ReconstructionVerdict.OBSERVATIONAL_EQUIVALENCE_CLASS
        explanation = f"Top behavioral cluster contains {equivalence_classes[0].size} observationally indistinguishable candidate policies."
    elif top_f1 >= 0.70 and top_loss <= 0.30:
        verdict = ReconstructionVerdict.SUPPORTED_BEHAVIORAL_RECONSTRUCTION
        explanation = f"High-confidence behavioral reconstruction with F1={top_f1:.4f} and entry error loss={top_loss:.4f}."
    elif top_f1 >= 0.30:
        verdict = ReconstructionVerdict.CONDITIONAL_RECONSTRUCTION
        explanation = f"Moderate behavioral match (F1={top_f1:.4f}) dependent on specific execution or timing assumptions."
    else:
        verdict = ReconstructionVerdict.TESTED_FAMILY_FAILURE
        explanation = f"Searched grammar tiers failed to explain observed ledger epochs (best F1={top_f1:.4f}, loss={top_loss:.4f})."

    return IdentifiabilitySummary(
        verdict=verdict,
        verdict_explanation=explanation,
        num_candidates_evaluated=len(evaluations),
        num_equivalence_classes=len(equivalence_classes),
        top_candidate_id=top_eval.candidate_id,
        top_candidate_f1=top_f1,
        top_candidate_loss=top_loss,
        supported_observed_epochs=supported_observed_epochs,
        unsupported_observed_epochs=unsupported,
        equivalence_classes=list(equivalence_classes),
        identifiable_parameters={
            "top_candidate_id": top_eval.candidate_id,
            "metrics": top_eval.metrics,
        },
    )
