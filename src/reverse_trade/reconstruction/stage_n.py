"""Independent planted-truth recovery calibration for Stage N."""

from __future__ import annotations

from itertools import product
from collections import Counter
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .benchmarks import PLANTED_BENCHMARK_REGISTRY
from .io import write_json
from .policy_ast import (
    Action, AndCondition, CrossesAboveCondition, CrossesBelowCondition, Policy,
    StateCondition, ThresholdCondition, TimeExit, TimeWindowCondition,
    PriceDistanceExit, TrailingStopExit,
)
from .replay import Quote, ReplayEngine
from .synthesis import threshold_grid


def _environment() -> tuple[list[Quote], pd.DataFrame]:
    count = 300
    times = pd.date_range("2026-01-05T13:58:00Z", periods=count, freq="s")
    index = np.arange(count, dtype=float)
    mid = 100.0 + 1.2 * np.sin(index / 9.0) + 0.35 * np.sin(index / 2.7) + index * 0.0007
    # Wide, faster variation makes sin(spread*10) genuinely non-monotone, so
    # the registered one-threshold grammar cannot counterfeit the nonlinear fixture.
    spread = 0.01 + 0.69 * ((np.sin(index / 7.0) + 1.0) / 2.0)
    quotes = [Quote(time, float(m - s / 2), float(m + s / 2), "planted_synthetic") for time, m, s in zip(times, mid, spread)]
    ret5 = 0.0032 * np.sin(index / 17.0) + 0.0009 * np.cos(index / 5.0)
    bar_ret5 = 0.0035 * np.sin(index / 31.0) + 0.0007 * np.cos(index / 7.0)
    volatility = 0.003 + 0.004 * ((np.sin(index / 41.0) + 1.0) / 2.0)
    frame = pd.DataFrame({
        "decision_time_utc": times,
        "hour_utc": times.hour.astype(float),
        "day_of_week": times.dayofweek.astype(float),
        "ret5": ret5,
        "prev_ret5": np.r_[ret5[0], ret5[:-1]],
        "bar_ret5": bar_ret5,
        "spread": spread,
        "volatility": volatility,
        "decision_index": index,
        "feature_status": "observed",
    })
    # Match the real panel's approximate unknown fraction using a fixed pattern.
    frame.loc[(np.arange(count) * 37) % 100 < 29, "feature_status"] = "unknown"
    return quotes, frame


def _exit_grid() -> tuple[Any, ...]:
    # Frozen independently of any benchmark result.
    return (
        TimeExit(1.0), TimeExit(5.0), TimeExit(10.0), TimeExit(15.0), TimeExit(20.0),
        TimeExit(30.0), TimeExit(60.0),
        PriceDistanceExit(take_profit=1.0, stop_loss=0.5),
        TrailingStopExit(trail_distance=0.5, activation_distance=0.2),
    )


def _grid(frame: pd.DataFrame, feature: str, maximum: int = 15) -> list[float]:
    registered = {
        "ret5": (-0.002, -0.001, 0.0, 0.001, 0.002),
        "bar_ret5": (-0.002, 0.0, 0.001, 0.002, 0.003),
        "spread": (0.1, 0.2),
        "volatility": (0.003, 0.005, 0.007),
    }
    return sorted(set(threshold_grid(frame[feature], min(maximum, 5))).union(registered.get(feature, ())))


def _threshold_candidates(frame: pd.DataFrame, feature: str, *, actions: Iterable[Action] = (Action.OPEN_BUY, Action.OPEN_SELL), cooldowns: Iterable[float] = (0.0,)) -> list[Policy]:
    grid = _grid(frame, feature)
    return [
        Policy(ThresholdCondition(feature, operator, threshold), action, cooldown_seconds=cooldown, exit_rule=exit_rule,
               name=f"registered_{feature}_{operator}_{threshold:.8g}_{action.value}_{cooldown}_{type(exit_rule).__name__}")
        for operator, threshold, action, cooldown, exit_rule in product((">", "<"), grid, tuple(actions), tuple(cooldowns), _exit_grid())
    ]


def _candidate_pool(family: str, frame: pd.DataFrame) -> list[Policy]:
    if family == "clock_only":
        return [
            Policy(TimeWindowCondition(start, end), side, exit_rule=exit_rule, name=f"clock_{start}_{end}_{side.value}_{type(exit_rule).__name__}")
            for (start, end), side, exit_rule in product(((13, 13), (14, 14), (13, 14), (15, 15)), (Action.OPEN_BUY, Action.OPEN_SELL), _exit_grid())
        ]
    if family == "bar_threshold":
        return _threshold_candidates(frame, "bar_ret5")
    if family == "tick_first_crossing":
        grid = _grid(frame, "ret5")
        return [
            Policy(condition("ret5", threshold), side, exit_rule=exit_rule, name=f"cross_{condition.__name__}_{threshold:.8g}_{side.value}_{type(exit_rule).__name__}")
            for condition, threshold, side, exit_rule in product((CrossesAboveCondition, CrossesBelowCondition), grid, (Action.OPEN_BUY, Action.OPEN_SELL), _exit_grid())
        ]
    if family == "reversal":
        return _threshold_candidates(frame, "ret5")
    if family == "conjunction":
        grid1 = _grid(frame, "ret5", 7)
        grid2 = _grid(frame, "spread", 7)
        candidates = []
        for op1, t1, op2, t2, side, exit_rule in product((">", "<"), grid1, (">", "<"), grid2, (Action.OPEN_BUY, Action.OPEN_SELL), _exit_grid()):
            condition = AndCondition((ThresholdCondition("ret5", op1, t1), ThresholdCondition("spread", op2, t2)))
            candidates.append(Policy(condition, side, exit_rule=exit_rule, name=f"conjunction_{len(candidates)}"))
        return candidates
    if family == "cooldown_state":
        return _threshold_candidates(frame, "ret5", cooldowns=(0.0, 5.0, 30.0, 60.0))
    if family == "pending_delayed_fill":
        return _threshold_candidates(frame, "ret5", actions=(Action.OPEN_BUY, Action.PLACE_LIMIT))
    if family == "trailing_exit":
        return _threshold_candidates(frame, "ret5")
    if family == "regime_switching":
        grid = _grid(frame, "volatility")
        return [
            Policy(
                AndCondition((ThresholdCondition("volatility", operator, threshold), StateCondition(0))),
                side, exit_rule=exit_rule, state_transitions={"Buy": 1, "Sell": 1, "Exit": 0},
                name=f"regime_{operator}_{threshold:.8g}_{side.value}_{type(exit_rule).__name__}",
            )
            for operator, threshold, side, exit_rule in product((">", "<"), grid, (Action.OPEN_BUY, Action.OPEN_SELL), _exit_grid())
        ]
    # Deliberately exclude stochastic and nonlinear nodes from the supported grammar.
    if family in {"null_stochastic", "out_of_family"}:
        exits = (TimeExit(10.0),)
        return [
            Policy(ThresholdCondition(feature, operator, threshold), side, exit_rule=exit_rule,
                   name=f"reject_{feature}_{operator}_{threshold:.8g}_{side.value}")
            for feature, operator, side, exit_rule in product(("ret5", "spread"), (">", "<"), (Action.OPEN_BUY, Action.OPEN_SELL), exits)
            for threshold in _grid(frame, feature, 5)
        ]
    raise ValueError(f"No independent candidate pool for {family}")


def _signature(trades: pd.DataFrame) -> list[tuple[Any, ...]]:
    if trades.empty:
        return []
    return [
        (
            row.side, round(float(row.volume), 8), pd.Timestamp(row.open_time_utc), round(float(row.open_price), 8),
            pd.Timestamp(row.close_time_utc) if pd.notna(row.close_time_utc) else None,
            round(float(row.close_price), 8) if pd.notna(row.close_price) else None, row.close_reason,
        )
        for row in trades.itertuples(index=False)
    ]


def _entry_score(observed: pd.DataFrame, predicted: pd.DataFrame) -> float:
    obs = Counter((pd.Timestamp(row.open_time_utc), row.side, round(float(row.volume), 8)) for row in observed.itertuples())
    pred = Counter((pd.Timestamp(row.open_time_utc), row.side, round(float(row.volume), 8)) for row in predicted.itertuples())
    tp = sum((obs & pred).values())
    precision = tp / sum(pred.values()) if pred else 0.0
    recall = tp / sum(obs.values()) if obs else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _entry_score_signatures(observed: tuple[tuple[Any, ...], ...], predicted: tuple[tuple[Any, ...], ...]) -> float:
    obs = Counter((row[2], row[0], row[1]) for row in observed)
    pred = Counter((row[2], row[0], row[1]) for row in predicted)
    tp = sum((obs & pred).values())
    precision = tp / sum(pred.values()) if pred else 0.0
    recall = tp / sum(obs.values()) if obs else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _family_blind_candidate_pool(frame: pd.DataFrame) -> list[Policy]:
    """Build one registered grammar before looking at any planted family."""

    families = (
        "clock_only", "bar_threshold", "tick_first_crossing", "reversal",
        "conjunction", "cooldown_state", "pending_delayed_fill",
        "trailing_exit", "regime_switching",
    )
    unique: dict[str, Policy] = {}
    for family in families:
        for candidate in _candidate_pool(family, frame):
            key = json.dumps(candidate.to_dict(), sort_keys=True, default=str)
            unique.setdefault(key, candidate)
    return list(unique.values())


def run_stage_n(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    quotes, features = _environment()
    candidates = _family_blind_candidate_pool(features)
    # Replay the common grammar once.  The target family never selects or
    # modifies the candidate pool.
    signature_counts: Counter[tuple[tuple[Any, ...], ...]] = Counter()
    for candidate in candidates:
        predicted, _ = ReplayEngine(candidate).run(quotes, features, record_trace=False)
        signature_counts[tuple(_signature(predicted))] += 1
    rows: list[dict[str, Any]] = []
    for family, generator in PLANTED_BENCHMARK_REGISTRY.items():
        target = generator()
        if family == "observational_equivalence":
            left, right = target  # type: ignore[misc]
            left_trades, _ = ReplayEngine(left).run(quotes, features, record_trace=False)
            right_trades, _ = ReplayEngine(right).run(quotes, features, record_trace=False)
            exact = _signature(left_trades) == _signature(right_trades) and len(left_trades) > 0
            rows.append({
                "family": family, "expected": "equivalent_class", "planted_trades": len(left_trades),
                "candidate_count": 2, "best_entry_f1": _entry_score(left_trades, right_trades),
                "exact_lifecycle_recovered": exact, "gate_pass": exact,
            })
            continue
        planted = target  # type: ignore[assignment]
        observed, _ = ReplayEngine(planted).run(quotes, features, record_trace=False)
        in_grammar = bool(planted.metadata.get("in_grammar", True))
        observed_signature = tuple(_signature(observed))
        best_f1 = max((_entry_score_signatures(observed_signature, signature) for signature in signature_counts), default=0.0)
        exact_count = signature_counts.get(observed_signature, 0) if observed_signature else 0
        expected = "recover" if in_grammar else "reject_or_nonidentify"
        passed = bool(exact_count) if in_grammar else not bool(exact_count)
        rows.append({
            "family": family, "expected": expected, "planted_trades": len(observed),
            "candidate_count": len(candidates), "best_entry_f1": best_f1,
            "exact_lifecycle_recovered": bool(exact_count), "equivalent_exact_candidates": exact_count,
            "gate_pass": passed,
        })
        print(f"Stage N {family}: planted={len(observed)} candidates={len(candidates)} exact={exact_count} pass={passed}", flush=True)
    table = pd.DataFrame(rows)
    table.to_csv(output / "planted_recovery_results.csv", index=False)
    failures = table.loc[~table.gate_pass, "family"].tolist()
    summary = {
        "status": "passed" if not failures else "failed",
        "families": len(table),
        "passed_families": int(table.gate_pass.sum()),
        "failed_families": failures,
        "candidate_generation_received_planted_policy": False,
        "candidate_generation_received_planted_family": False,
        "family_blind_common_candidate_pool": True,
        "common_candidate_count": len(candidates),
        "candidate_grids_registered_in_code": True,
        "full_sequential_replay_used": True,
        "real_panel_unknown_fraction_approximated": True,
        "real_policy_search_performed": False,
    }
    write_json(output / "stage_status.json", summary)
    return summary
