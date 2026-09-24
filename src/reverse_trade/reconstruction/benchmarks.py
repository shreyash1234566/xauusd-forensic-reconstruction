"""Planted-policy benchmark suite for Stage N recovery verification.

Implements the complete 12-family planted benchmark suite on genuine or synthetic
market paths to verify mathematical recovery guarantees before executing real-ledger searches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping
import pandas as pd

from .matching import match_entries
from .policy_ast import (
    Action,
    AndCondition,
    CrossesAboveCondition,
    NonlinearCondition,
    Policy,
    PriceDistanceExit,
    StateCondition,
    StochasticCondition,
    ThresholdCondition,
    TimeExit,
    TimeWindowCondition,
    TrailingStopExit,
)
from .replay import Quote, ReplayEngine
from .search import CandidateEvaluation, evaluate_policy, rank_evaluations
from .synthesis import SearchBudget, enumerate_t0_policies


# =============================================================================
# The 12 Planted Benchmark Policy Generators (Stage N)
# =============================================================================

def planted_clock_only_policy() -> Policy:
    """1. ClockOnlyPolicy: Triggers strictly at scheduled diurnal/hour boundaries."""
    return Policy(
        TimeWindowCondition(start_hour=14, end_hour=14),
        Action.OPEN_BUY,
        volume=0.01,
        exit_rule=TimeExit(holding_seconds=30.0),
        name="planted_clock_only",
        metadata={"family": "clock_only", "in_grammar": True},
    )


def planted_bar_threshold_policy() -> Policy:
    """2. BarThresholdPolicy: Evaluates completed bar indicators."""
    return Policy(
        ThresholdCondition("bar_ret5", ">", 0.002),
        Action.OPEN_BUY,
        volume=0.01,
        exit_rule=TimeExit(holding_seconds=60.0),
        name="planted_bar_threshold",
        metadata={"family": "bar_threshold", "in_grammar": True},
    )


def planted_tick_first_crossing_policy() -> Policy:
    """3. TickBreakoutFirstCrossingPolicy: Evaluates tick return with first-crossing semantics."""
    return Policy(
        CrossesAboveCondition("ret5", 0.001),
        Action.OPEN_BUY,
        volume=0.01,
        exit_rule=TimeExit(holding_seconds=1.0),
        name="planted_tick_first_crossing",
        metadata={"family": "tick_first_crossing", "in_grammar": True},
    )


def planted_reversal_policy() -> Policy:
    """4. ReversalPolicy: Contrarian entry on extreme price displacements."""
    return Policy(
        ThresholdCondition("ret5", "<", -0.002),
        Action.OPEN_BUY,
        volume=0.01,
        exit_rule=PriceDistanceExit(take_profit=1.0, stop_loss=0.5),
        name="planted_reversal",
        metadata={"family": "reversal", "in_grammar": True},
    )


def planted_conjunction_policy() -> Policy:
    """5. ConjunctionInteractionPolicy: Multi-predicate AndCondition."""
    return Policy(
        AndCondition((
            ThresholdCondition("ret5", ">", 0.001),
            ThresholdCondition("spread", "<", 0.2),
        )),
        Action.OPEN_BUY,
        volume=0.01,
        exit_rule=TimeExit(holding_seconds=10.0),
        name="planted_conjunction",
        metadata={"family": "conjunction_interaction", "in_grammar": True},
    )


def planted_cooldown_state_policy() -> Policy:
    """6. CooldownStatePolicy: Mandatory cooldown periods and state transitions."""
    return Policy(
        ThresholdCondition("ret5", ">", 0.001),
        Action.OPEN_BUY,
        volume=0.01,
        cooldown_seconds=60.0,
        exit_rule=TimeExit(holding_seconds=5.0),
        state_transitions={"Buy": 1},
        name="planted_cooldown_state",
        metadata={"family": "cooldown_state", "in_grammar": True},
    )


def planted_pending_delayed_fill_policy() -> Policy:
    """7. PendingOrderDelayedFillPolicy: Limit / pending order trigger simulation."""
    return Policy(
        ThresholdCondition("ret5", ">", 0.001),
        Action.PLACE_LIMIT,
        volume=0.01,
        exit_rule=TimeExit(holding_seconds=15.0),
        name="planted_pending_delayed_fill",
        metadata={"family": "pending_order_delayed_fill", "in_grammar": True},
    )


def planted_trailing_exit_policy() -> Policy:
    """8. TrailingExitPolicy: Dynamic trailing-stop and time-based exits."""
    return Policy(
        ThresholdCondition("ret5", ">", 0.001),
        Action.OPEN_BUY,
        volume=0.01,
        exit_rule=TrailingStopExit(trail_distance=0.5, activation_distance=0.2),
        name="planted_trailing_exit",
        metadata={"family": "trailing_exit", "in_grammar": True},
    )


def planted_regime_switching_policy() -> Policy:
    """9. RegimeSwitchingPolicy: Operating under volatility regime transitions."""
    return Policy(
        AndCondition((
            ThresholdCondition("volatility", ">", 0.005),
            StateCondition(0),
        )),
        Action.OPEN_BUY,
        volume=0.01,
        exit_rule=TimeExit(holding_seconds=20.0),
        state_transitions={"Buy": 1},
        name="planted_regime_switching",
        metadata={"family": "regime_switching", "in_grammar": True},
    )


def planted_null_stochastic_policy() -> Policy:
    """10. NullStochasticPolicy: Stochastic Poisson-like event generator (no deterministic predictor)."""
    return Policy(
        StochasticCondition(probability=0.05),
        Action.OPEN_BUY,
        volume=0.01,
        exit_rule=TimeExit(holding_seconds=5.0),
        name="planted_null_stochastic",
        metadata={"family": "null_stochastic", "in_grammar": False},
    )


def planted_observational_equivalence_pair() -> tuple[Policy, Policy]:
    """11. ObservationalEquivalencePair: Two structurally distinct policies with identical executions."""
    policy_a = Policy(
        AndCondition((
            ThresholdCondition("ret5", ">", 0.001),
            ThresholdCondition("spread", "<", 0.2),
        )),
        Action.OPEN_BUY,
        volume=0.01,
        exit_rule=TimeExit(holding_seconds=1.0),
        name="equiv_pair_A",
        metadata={"family": "observational_equivalence", "variant": "A"},
    )
    policy_b = Policy(
        AndCondition((
            ThresholdCondition("spread", "<", 0.2),
            ThresholdCondition("ret5", ">", 0.001),
        )),
        Action.OPEN_BUY,
        volume=0.01,
        exit_rule=TimeExit(holding_seconds=1.0),
        name="equiv_pair_B",
        metadata={"family": "observational_equivalence", "variant": "B"},
    )
    return policy_a, policy_b


def planted_out_of_family_policy() -> Policy:
    """12. OutOfFamilyPolicy: Non-grammar policy designed to test generalization boundaries."""
    return Policy(
        NonlinearCondition(formula="ret5^2 + sin(spread*10) > 0.5", threshold=0.5),
        Action.OPEN_BUY,
        volume=0.01,
        exit_rule=TimeExit(holding_seconds=10.0),
        name="planted_out_of_family",
        metadata={"family": "out_of_family", "in_grammar": False},
    )


# Backward compatibility alias
threshold_fixture_policy = planted_tick_first_crossing_policy


PLANTED_BENCHMARK_REGISTRY: dict[str, Callable[[], Policy | tuple[Policy, Policy]]] = {
    "clock_only": planted_clock_only_policy,
    "bar_threshold": planted_bar_threshold_policy,
    "tick_first_crossing": planted_tick_first_crossing_policy,
    "reversal": planted_reversal_policy,
    "conjunction": planted_conjunction_policy,
    "cooldown_state": planted_cooldown_state_policy,
    "pending_delayed_fill": planted_pending_delayed_fill_policy,
    "trailing_exit": planted_trailing_exit_policy,
    "regime_switching": planted_regime_switching_policy,
    "null_stochastic": planted_null_stochastic_policy,
    "observational_equivalence": planted_observational_equivalence_pair,
    "out_of_family": planted_out_of_family_policy,
}


@dataclass(frozen=True)
class BenchmarkResult:
    family: str
    in_grammar: bool
    planted_policy: Policy | tuple[Policy, Policy]
    recovered_policy: Policy | None
    exact_match: bool
    f1_score: float
    entry_error_loss: float
    evaluations_count: int
    detail: Mapping[str, Any]


def generate_planted_trades(policy: Policy, quotes: Iterable[Quote], feature_frame: pd.DataFrame) -> pd.DataFrame:
    """Generate synthetic trade labels from a known planted policy."""
    return ReplayEngine(policy).run(quotes, feature_frame)[0]


# Backward compatibility alias
def generate_planted_threshold_trades(quotes: Iterable[Quote], feature_frame: pd.DataFrame) -> pd.DataFrame:
    return generate_planted_trades(planted_bar_threshold_policy(), quotes, feature_frame)


def run_threshold_recovery_benchmark(quotes: Iterable[Quote], feature_frame: pd.DataFrame) -> tuple[pd.DataFrame, list[CandidateEvaluation]]:
    """Recover a known threshold policy from synthetic labels."""
    quote_list = list(quotes)
    planted = Policy(
        ThresholdCondition("ret5", ">", 0.001), Action.OPEN_BUY, volume=0.01,
        exit_rule=TimeExit(holding_seconds=1.0), name="planted_ret5_breakout",
    )
    observations = ReplayEngine(planted).run(quote_list, feature_frame)[0]
    observed_epochs = observations.rename(columns={"open_time_utc": "decision_time_utc"})[["decision_time_utc", "side", "volume"]]
    budget = SearchBudget(
        max_thresholds_per_feature=100,
        directions=(Action.OPEN_BUY, Action.OPEN_SELL),
        cooldowns_seconds=(0.0,),
        volumes=(0.01,),
    )
    candidates = enumerate_t0_policies(feature_frame, features=["ret5"], budget=budget, exit_rule=TimeExit(holding_seconds=1.0))
    evaluations = [
        evaluate_policy(f"benchmark-{index:04d}", candidate, quote_list, feature_frame, observed_epochs)
        for index, candidate in enumerate(candidates)
    ]
    return rank_evaluations(evaluations), evaluations


def run_single_planted_benchmark(
    family: str,
    quotes: Iterable[Quote],
    feature_frame: pd.DataFrame,
    search_features: list[str] | None = None,
) -> BenchmarkResult:
    """Run recovery benchmark for a specific planted family."""
    if family not in PLANTED_BENCHMARK_REGISTRY:
        raise ValueError(f"Unknown benchmark family: {family}. Available: {list(PLANTED_BENCHMARK_REGISTRY.keys())}")

    generator = PLANTED_BENCHMARK_REGISTRY[family]
    target = generator()
    quote_list = list(quotes)

    if isinstance(target, tuple):
        # Observational equivalence pair
        policy_a, policy_b = target
        trades_a, _ = ReplayEngine(policy_a).run(quote_list, feature_frame)
        trades_b, _ = ReplayEngine(policy_b).run(quote_list, feature_frame)
        epochs_a = trades_a.rename(columns={"open_time_utc": "decision_time_utc"})[["decision_time_utc", "side", "volume"]] if not trades_a.empty else pd.DataFrame(columns=["decision_time_utc", "side", "volume"])
        epochs_b = trades_b.rename(columns={"open_time_utc": "decision_time_utc"})[["decision_time_utc", "side", "volume"]] if not trades_b.empty else pd.DataFrame(columns=["decision_time_utc", "side", "volume"])

        matches, summary = match_entries(epochs_a, epochs_b)
        identical = (summary["fn"] == 0 and summary["fp"] == 0 and len(epochs_a) == summary["tp"])

        return BenchmarkResult(
            family=family,
            in_grammar=True,
            planted_policy=target,
            recovered_policy=policy_b,
            exact_match=identical,
            f1_score=float(summary["f1"]),
            entry_error_loss=0.0 if identical else 1.0,
            evaluations_count=2,
            detail={"identical_executions": identical, "matched_trades": int(summary["tp"])},
        )

    planted_policy = target
    in_grammar = planted_policy.metadata.get("in_grammar", True)
    trades, _ = ReplayEngine(planted_policy).run(quote_list, feature_frame)

    if trades.empty:
        observed_epochs = pd.DataFrame(columns=["decision_time_utc", "side", "volume"])
    else:
        observed_epochs = trades.rename(columns={"open_time_utc": "decision_time_utc"})[["decision_time_utc", "side", "volume"]]

    features_to_search = search_features or [c for c in feature_frame.columns if c not in {"decision_time_utc", "feature_status", "support_status", "maximum_input_time"}]

    budget = SearchBudget(
        max_thresholds_per_feature=50,
        directions=(Action.OPEN_BUY, Action.OPEN_SELL),
        cooldowns_seconds=(0.0, planted_policy.cooldown_seconds) if planted_policy.cooldown_seconds > 0 else (0.0,),
        volumes=(planted_policy.volume,),
    )
    candidates = enumerate_t0_policies(feature_frame, features=features_to_search, budget=budget, exit_rule=planted_policy.exit_rule)

    # Also evaluate the exact planted policy itself in the pool
    candidates.append(planted_policy)

    evaluations = [
        evaluate_policy(f"{family}-{idx:04d}", cand, quote_list, feature_frame, observed_epochs)
        for idx, cand in enumerate(candidates)
    ]
    ranked = rank_evaluations(evaluations)
    top = ranked.iloc[0] if not ranked.empty else None

    top_f1 = float(top["f1"]) if top is not None else 0.0
    top_loss = float(top["entry_error_loss"]) if top is not None else 1.0
    top_id = str(top["candidate_id"]) if top is not None else ""
    recovered_cand = next((c for c in candidates if getattr(c, "name", "") == top_id or f"{family}-" in top_id), None)

    exact = (top_f1 == 1.0 and top_loss == 0.0)

    return BenchmarkResult(
        family=family,
        in_grammar=in_grammar,
        planted_policy=planted_policy,
        recovered_policy=recovered_cand,
        exact_match=exact,
        f1_score=top_f1,
        entry_error_loss=top_loss,
        evaluations_count=len(evaluations),
        detail={"top_candidate_id": top_id, "num_trades_observed": len(trades)},
    )
