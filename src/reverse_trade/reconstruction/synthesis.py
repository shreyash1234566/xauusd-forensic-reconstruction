"""Bounded, transparent search over the policy grammar.

Implements multi-tier program synthesis:
- T0: Single-feature threshold policies.
- T1: Multi-predicate conjunction policies (AndCondition).
- T2: First-crossing and persistent feature policies.
- T3: Time-windowed / diurnal conditional policies.
- Exit Synthesis: Time, TP/SL, and TrailingStop exit configurations.
- Guided Beam Search: Incremental synthesis optimizing MDL objective on training splits.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from .policy_ast import (
    Action,
    AndCondition,
    Condition,
    CrossesAboveCondition,
    CrossesBelowCondition,
    ExitRule,
    Policy,
    PriceDistanceExit,
    ThresholdCondition,
    TimeExit,
    TimeWindowCondition,
    TrailingStopExit,
    calculate_mdl_code_length,
)
from .replay import Quote
from .search import evaluate_policy


@dataclass(frozen=True)
class SearchBudget:
    max_thresholds_per_feature: int = 15
    directions: tuple[Action, ...] = (Action.OPEN_BUY, Action.OPEN_SELL)
    cooldowns_seconds: tuple[float, ...] = (0.0, 30.0, 60.0, 120.0)
    volumes: tuple[float, ...] = (0.01, 0.02, 0.03)
    max_conjunction_pairs: int = 50


def threshold_grid(values: Iterable[float], maximum: int) -> list[float]:
    finite = np.asarray([value for value in values if np.isfinite(value)], dtype=float)
    if not len(finite):
        return []
    unique = np.unique(finite)
    if len(unique) <= maximum:
        return unique.tolist()
    quantiles = np.linspace(0.05, 0.95, maximum)
    return np.unique(np.quantile(unique, quantiles)).tolist()


def enumerate_t0_policies(
    feature_frame: pd.DataFrame,
    *,
    features: Iterable[str],
    budget: SearchBudget = SearchBudget(),
    exit_rule: ExitRule | None = None,
) -> list[Policy]:
    """Enumerate single-predicate threshold policies."""

    candidates: list[Policy] = []
    for feature in features:
        if feature not in feature_frame:
            continue
        for operator, threshold, side, cooldown, volume in product(
            (">", "<"), threshold_grid(feature_frame[feature].dropna(), budget.max_thresholds_per_feature),
            budget.directions, budget.cooldowns_seconds, budget.volumes,
        ):
            condition = ThresholdCondition(feature, operator, float(threshold))
            candidates.append(Policy(
                condition, side, volume=volume, cooldown_seconds=cooldown, exit_rule=exit_rule,
                name=f"t0_{feature}_{operator}_{threshold:.12g}",
                metadata={"tier": "T0", "feature": feature, "operator": operator, "threshold": threshold},
            ))
    return candidates


def enumerate_crossing_policies(
    feature_frame: pd.DataFrame,
    *,
    features: Iterable[str],
    budget: SearchBudget = SearchBudget(),
    exit_rule: ExitRule | None = None,
) -> list[Policy]:
    """Enumerate first-crossing policies (CrossesAbove / CrossesBelow)."""

    candidates: list[Policy] = []
    for feature in features:
        if feature not in feature_frame:
            continue
        grid = threshold_grid(feature_frame[feature].dropna(), budget.max_thresholds_per_feature)
        for threshold, side, cooldown, volume in product(
            grid, budget.directions, budget.cooldowns_seconds, budget.volumes,
        ):
            c_above = CrossesAboveCondition(feature, float(threshold))
            candidates.append(Policy(
                c_above, side, volume=volume, cooldown_seconds=cooldown, exit_rule=exit_rule,
                name=f"crossing_above_{feature}_{threshold:.12g}",
                metadata={"tier": "crossing_above", "feature": feature, "threshold": threshold},
            ))
            c_below = CrossesBelowCondition(feature, float(threshold))
            candidates.append(Policy(
                c_below, side, volume=volume, cooldown_seconds=cooldown, exit_rule=exit_rule,
                name=f"crossing_below_{feature}_{threshold:.12g}",
                metadata={"tier": "crossing_below", "feature": feature, "threshold": threshold},
            ))
    return candidates


def enumerate_t1_conjunction_policies(
    feature_frame: pd.DataFrame,
    *,
    feature_pairs: Sequence[tuple[str, str]],
    budget: SearchBudget = SearchBudget(),
    exit_rule: ExitRule | None = None,
) -> list[Policy]:
    """Enumerate two-predicate conjunction policies (AndCondition)."""

    candidates: list[Policy] = []
    for f1, f2 in feature_pairs:
        if f1 not in feature_frame or f2 not in feature_frame:
            continue
        grid1 = threshold_grid(feature_frame[f1].dropna(), min(5, budget.max_thresholds_per_feature))
        grid2 = threshold_grid(feature_frame[f2].dropna(), min(5, budget.max_thresholds_per_feature))

        for (op1, t1), (op2, t2), side, cooldown, volume in product(
            product((">", "<"), grid1),
            product((">", "<"), grid2),
            budget.directions,
            budget.cooldowns_seconds[:2],
            budget.volumes[:1],
        ):
            c1 = ThresholdCondition(f1, op1, float(t1))
            c2 = ThresholdCondition(f2, op2, float(t2))
            cond = AndCondition((c1, c2))
            candidates.append(Policy(
                cond, side, volume=volume, cooldown_seconds=cooldown, exit_rule=exit_rule,
                name=f"t1_{f1}_{op1}_{t1:.6g}_and_{f2}_{op2}_{t2:.6g}",
                metadata={"tier": "T1", "f1": f1, "f2": f2},
            ))
            if len(candidates) >= budget.max_conjunction_pairs * 20:
                break
    return candidates


def enumerate_time_window_policies(
    feature_frame: pd.DataFrame,
    *,
    base_conditions: Sequence[Condition],
    budget: SearchBudget = SearchBudget(),
    exit_rule: ExitRule | None = None,
) -> list[Policy]:
    """Enumerate time-windowed policies combining base conditions with session hours."""

    candidates: list[Policy] = []
    # Common trading session hours (UTC): Asian (0-8), London (8-16), NY (13-21), Overlap (13-16)
    windows = [
        (8, 16),
        (13, 20),
        (13, 16),
        (14, 15),
    ]

    for cond, (start_h, end_h), side, cooldown in product(
        base_conditions, windows, budget.directions, budget.cooldowns_seconds[:2]
    ):
        tw = TimeWindowCondition(start_hour=start_h, end_hour=end_h)
        joint_cond = AndCondition((tw, cond))
        candidates.append(Policy(
            joint_cond, side, volume=0.01, cooldown_seconds=cooldown, exit_rule=exit_rule,
            name=f"tw_{start_h}_{end_h}_{getattr(cond, 'feature', 'cond')}",
            metadata={"tier": "time_window", "start_hour": start_h, "end_hour": end_h},
        ))
    return candidates


def enumerate_exit_rules() -> list[ExitRule]:
    """Standard search grid of candidate exit rules."""
    exits: list[ExitRule] = [
        TimeExit(holding_seconds=1.0),
        TimeExit(holding_seconds=5.0),
        TimeExit(holding_seconds=15.0),
        TimeExit(holding_seconds=30.0),
        TimeExit(holding_seconds=60.0),
        TimeExit(holding_seconds=300.0),
        PriceDistanceExit(take_profit=0.5, stop_loss=0.5),
        PriceDistanceExit(take_profit=1.0, stop_loss=0.5),
        PriceDistanceExit(take_profit=2.0, stop_loss=1.0),
        TrailingStopExit(trail_distance=0.5, activation_distance=0.2),
        TrailingStopExit(trail_distance=1.0, activation_distance=0.5),
    ]
    return exits


def synthesize_beam_search(
    feature_frame: pd.DataFrame,
    quotes: Iterable[Quote],
    observed_epochs: pd.DataFrame,
    features: Sequence[str],
    *,
    beam_width: int = 20,
    max_depth: int = 2,
    budget: SearchBudget = SearchBudget(),
) -> list[Policy]:
    """Syntax-guided beam search optimizing Minimum Description Length (MDL) objective."""

    quote_list = list(quotes)
    # Tier 0 base pool
    pool = enumerate_t0_policies(feature_frame, features=features, budget=budget, exit_rule=TimeExit(holding_seconds=10.0))
    pool += enumerate_crossing_policies(feature_frame, features=features, budget=budget, exit_rule=TimeExit(holding_seconds=10.0))

    if not pool:
        return []

    # Score base pool
    scored = []
    for idx, p in enumerate(pool):
        ev = evaluate_policy(f"beam-t0-{idx:04d}", p, quote_list, feature_frame, observed_epochs)
        f1 = float(ev.metrics.get("f1", 0.0))
        loss = float(ev.metrics.get("entry_error_loss", 1.0))
        mdl = calculate_mdl_code_length(p)
        score = loss + 0.001 * mdl  # Combined error and complexity penalty
        scored.append((score, f1, p))

    scored.sort(key=lambda x: (x[0], -x[1]))
    beam = [p for _, _, p in scored[:beam_width]]

    if max_depth <= 1:
        return beam

    # Depth 2: Combine top beam conditions into conjunctions and time windows
    base_conditions = [p.entry for p in beam]
    top_features = list(set([getattr(c, "feature", "") for c in base_conditions if hasattr(c, "feature") and getattr(c, "feature")]))
    feature_pairs = list(combinations(top_features, 2))[:budget.max_conjunction_pairs]

    depth2_pool = enumerate_t1_conjunction_policies(feature_frame, feature_pairs=feature_pairs, budget=budget, exit_rule=TimeExit(holding_seconds=10.0))
    depth2_pool += enumerate_time_window_policies(feature_frame, base_conditions=base_conditions[:10], budget=budget, exit_rule=TimeExit(holding_seconds=10.0))

    # Evaluate depth 2 pool
    depth2_scored = []
    for idx, p in enumerate(depth2_pool):
        ev = evaluate_policy(f"beam-t1-{idx:04d}", p, quote_list, feature_frame, observed_epochs)
        f1 = float(ev.metrics.get("f1", 0.0))
        loss = float(ev.metrics.get("entry_error_loss", 1.0))
        mdl = calculate_mdl_code_length(p)
        score = loss + 0.001 * mdl
        depth2_scored.append((score, f1, p))

    depth2_scored.sort(key=lambda x: (x[0], -x[1]))
    all_best = sorted(scored + depth2_scored, key=lambda x: (x[0], -x[1]))

    return [p for _, _, p in all_best[:beam_width]]


def candidate_registry(candidates: Iterable[Policy]) -> pd.DataFrame:
    rows = []
    for index, candidate in enumerate(candidates):
        payload = candidate.to_dict()
        rows.append({"candidate_id": f"t0-{index:06d}", **payload})
    return pd.DataFrame(rows)
