r"""Finite-State Machine (FSM) and regime-dependent policy search (Stage R).

Implements bounded state-space exploration for stateful execution policies:
- $K \le 4$ discrete state registers.
- State transition tables mapped to fill events and trade actions.
- State-conditioned entry rules combining AST condition predicates with StateCondition.
- Transition matrix synthesis and stateful policy evaluation against observed epochs.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Iterable, Sequence

import pandas as pd

from .policy_ast import (
    Action,
    AndCondition,
    Condition,
    ExitRule,
    Policy,
    StateCondition,
    ThresholdCondition,
    TimeExit,
)
from .replay import Quote
from .search import CandidateEvaluation, evaluate_policy
from .synthesis import SearchBudget, threshold_grid


@dataclass(frozen=True)
class StateMachineConfig:
    num_states: int = 2
    transitions: tuple[tuple[str, int], ...] = (("Buy", 1), ("Sell", 0))


def enumerate_stateful_policies(
    feature_frame: pd.DataFrame,
    *,
    features: Sequence[str],
    num_states: int = 2,
    budget: SearchBudget = SearchBudget(),
    exit_rule: ExitRule | None = None,
) -> list[Policy]:
    """Enumerate policies that maintain internal finite-state registers."""

    if num_states < 2 or num_states > 4:
        raise ValueError("State machine search supports num_states between 2 and 4.")

    candidates: list[Policy] = []
    base_exit = exit_rule or TimeExit(holding_seconds=10.0)

    # For each state s in [0, num_states-1], synthesize state-conditioned entry rules
    for feature in features:
        if feature not in feature_frame:
            continue
        grid = threshold_grid(feature_frame[feature].dropna(), min(4, budget.max_thresholds_per_feature))

        for state_val in range(num_states):
            state_cond = StateCondition(expected_state=state_val)

            for op, thresh, side in product((">", "<"), grid, budget.directions):
                t_cond = ThresholdCondition(feature, op, float(thresh))
                joint_cond = AndCondition((state_cond, t_cond))

                # Define standard alternating state transitions
                next_state_buy = (state_val + 1) % num_states
                next_state_sell = (state_val + 1) % num_states
                transitions = {"Buy": next_state_buy, "Sell": next_state_sell}

                candidates.append(Policy(
                    joint_cond,
                    side,
                    volume=0.01,
                    cooldown_seconds=0.0,
                    exit_rule=base_exit,
                    name=f"fsm_s{state_val}_{feature}_{op}_{thresh:.6g}",
                    metadata={
                        "tier": "FSM",
                        "num_states": num_states,
                        "state_val": state_val,
                        "feature": feature,
                        "transitions": transitions,
                    },
                    state_transitions=transitions,
                ))

    return candidates


def search_stateful_policies(
    feature_frame: pd.DataFrame,
    quotes: Iterable[Quote],
    observed_epochs: pd.DataFrame,
    features: Sequence[str],
    *,
    num_states: int = 2,
    top_k: int = 10,
    budget: SearchBudget = SearchBudget(),
) -> list[CandidateEvaluation]:
    """Search and score stateful candidate policies on historical epochs."""

    candidates = enumerate_stateful_policies(
        feature_frame, features=features, num_states=num_states, budget=budget
    )
    quote_list = list(quotes)
    summaries: list[CandidateEvaluation] = []

    for idx, cand in enumerate(candidates):
        ev = evaluate_policy(
            f"fsm-{idx:04d}",
            cand,
            quote_list,
            feature_frame,
            observed_epochs,
        )
        summaries.append(ev)

    summaries.sort(key=lambda x: (float(x.metrics.get("entry_error_loss", 1.0)), -float(x.metrics.get("f1", 0.0))))
    return summaries[:top_k]
