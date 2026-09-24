"""Evaluation of complete, executable candidates under one common contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .matching import MatchConfig, match_entries
from .policy_ast import Policy
from .replay import Quote, ReplayEngine
from .scoring import entry_error_loss


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate_id: str
    metrics: dict[str, float | int]
    matches: pd.DataFrame
    predictions: pd.DataFrame
    trace: pd.DataFrame


def evaluate_policy(
    candidate_id: str,
    policy: Policy,
    quotes: Iterable[Quote],
    feature_opportunities: pd.DataFrame,
    observed_epochs: pd.DataFrame,
    *,
    match_config: MatchConfig = MatchConfig(),
    _precomputed: tuple[set[pd.Timestamp], pd.DataFrame, int, int] | None = None,
) -> CandidateEvaluation:
    """Evaluate a candidate without injecting observed state into replay."""

    predictions, trace = ReplayEngine(policy).run(quotes, feature_opportunities)
    if _precomputed is not None:
        supported_times, supported_observed, known_opps, unknown_opps = _precomputed
        observed_len = len(observed_epochs)
    else:
        support = feature_opportunities.get("support_status", pd.Series("observed", index=feature_opportunities.index)).eq("observed")
        supported_times = set(pd.to_datetime(feature_opportunities.loc[support, "decision_time_utc"], utc=True))
        observed = observed_epochs.copy()
        observed["decision_time_utc"] = pd.to_datetime(observed["decision_time_utc"], utc=True)
        supported_observed = observed.loc[observed.decision_time_utc.isin(supported_times)].reset_index(drop=True)
        known_opps = int(support.sum())
        unknown_opps = int((~support).sum())
        observed_len = len(observed)

    matches, metrics = match_entries(supported_observed, predictions, match_config)
    metrics = dict(metrics)
    metrics.update({
        "candidate_complexity": policy.complexity(),
        "known_opportunities": known_opps,
        "unknown_opportunities": unknown_opps,
        "whole_ledger_epochs": observed_len,
        "unsupported_observed_epochs": int(observed_len - len(supported_observed)),
        "entry_error_loss": entry_error_loss(int(metrics["tp"]), int(metrics["fp"]), int(metrics["fn"]), len(supported_observed)),
    })
    return CandidateEvaluation(candidate_id, metrics, matches, predictions, trace)


def rank_evaluations(evaluations: Iterable[CandidateEvaluation]) -> pd.DataFrame:
    """Rank only the supplied common-domain evaluations; retain all raw metrics."""

    rows = [{"candidate_id": item.candidate_id, **item.metrics} for item in evaluations]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.sort_values(["entry_error_loss", "candidate_complexity", "candidate_id"], kind="mergesort").reset_index(drop=True)


def evaluate_policy_cohort(
    policies: Iterable[Policy],
    quotes: Iterable[Quote],
    feature_opportunities: pd.DataFrame,
    observed_epochs: pd.DataFrame,
    *,
    match_config: MatchConfig = MatchConfig(),
    prefix: str = "cand",
) -> list[CandidateEvaluation]:
    """Evaluate a collection/cohort of policies over the shared market timeline."""
    support = feature_opportunities.get("support_status", pd.Series("observed", index=feature_opportunities.index)).eq("observed")
    supported_times = set(pd.to_datetime(feature_opportunities.loc[support, "decision_time_utc"], utc=True))
    observed = observed_epochs.copy()
    observed["decision_time_utc"] = pd.to_datetime(observed["decision_time_utc"], utc=True)
    supported_observed = observed.loc[observed.decision_time_utc.isin(supported_times)].reset_index(drop=True)
    known_opps = int(support.sum())
    unknown_opps = int((~support).sum())
    precomputed = (supported_times, supported_observed, known_opps, unknown_opps)

    return [
        evaluate_policy(
            f"{prefix}_{idx:04d}",
            pol,
            quotes,
            feature_opportunities,
            observed_epochs,
            match_config=match_config,
            _precomputed=precomputed,
        )
        for idx, pol in enumerate(policies)
    ]

