"""Small, serializable grammar for executable candidate policies."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Mapping, Protocol

import pandas as pd


class Action(str, Enum):
    NONE = "none"
    OPEN_BUY = "open_buy"
    OPEN_SELL = "open_sell"
    CLOSE_ALL = "close_all"
    PLACE_LIMIT = "place_limit"


class Condition(Protocol):
    def evaluate(self, features: Mapping[str, float | None], state: "PolicyState") -> bool: ...
    def to_dict(self) -> dict[str, Any]: ...
    def complexity(self) -> int: ...


class ExitRule(Protocol):
    def should_exit(self, state: "PolicyState", now: pd.Timestamp, bid: float, ask: float) -> str | None: ...
    def to_dict(self) -> dict[str, Any]: ...
    def complexity(self) -> int: ...


@dataclass(frozen=True)
class PolicyState:
    position_side: str | None = None
    position_volume: float = 0.0
    entry_price: float | None = None
    entry_time: object | None = None
    cooldown_until: object | None = None
    highest_price: float | None = None
    state_register: int = 0
    pending_order_side: str | None = None
    pending_order_price: float | None = None
    pending_order_time: object | None = None
    pending_order_volume: float = 0.0
    pending_order_kind: str | None = None
    pending_order_due_time: object | None = None


@dataclass(frozen=True)
class ThresholdCondition:
    feature: str
    operator: str
    threshold: float

    def evaluate(self, features: Mapping[str, float | None], state: PolicyState) -> bool:
        value = features.get(self.feature)
        if value is None:
            return False
        if self.operator == ">":
            return value > self.threshold
        if self.operator == ">=":
            return value >= self.threshold
        if self.operator == "<":
            return value < self.threshold
        if self.operator == "<=":
            return value <= self.threshold
        if self.operator == "==":
            return math.isclose(value, self.threshold, rel_tol=1e-7, abs_tol=1e-7)
        if self.operator == "!=":
            return not math.isclose(value, self.threshold, rel_tol=1e-7, abs_tol=1e-7)
        raise ValueError(f"Unsupported threshold operator: {self.operator}")

    def to_dict(self) -> dict[str, Any]:
        return {"type": "threshold", "feature": self.feature, "operator": self.operator, "threshold": self.threshold}

    def complexity(self) -> int:
        return 2


@dataclass(frozen=True)
class AndCondition:
    children: tuple[Condition, ...]

    def evaluate(self, features: Mapping[str, float | None], state: PolicyState) -> bool:
        return all(child.evaluate(features, state) for child in self.children)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "and", "children": [child.to_dict() for child in self.children]}

    def complexity(self) -> int:
        return 1 + sum(child.complexity() for child in self.children)


@dataclass(frozen=True)
class OrCondition:
    children: tuple[Condition, ...]

    def evaluate(self, features: Mapping[str, float | None], state: PolicyState) -> bool:
        return any(child.evaluate(features, state) for child in self.children)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "or", "children": [child.to_dict() for child in self.children]}

    def complexity(self) -> int:
        return 1 + sum(child.complexity() for child in self.children)


@dataclass(frozen=True)
class NotCondition:
    child: Condition

    def evaluate(self, features: Mapping[str, float | None], state: PolicyState) -> bool:
        return not self.child.evaluate(features, state)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "not", "child": self.child.to_dict()}

    def complexity(self) -> int:
        return 1 + self.child.complexity()


@dataclass(frozen=True)
class CrossesAboveCondition:
    feature: str
    threshold: float
    prev_feature: str | None = None

    def evaluate(self, features: Mapping[str, float | None], state: PolicyState) -> bool:
        current_val = features.get(self.feature)
        prev_key = self.prev_feature or f"prev_{self.feature}"
        prev_val = features.get(prev_key)
        if current_val is None or prev_val is None:
            return False
        return prev_val <= self.threshold < current_val

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "crosses_above",
            "feature": self.feature,
            "threshold": self.threshold,
            "prev_feature": self.prev_feature,
        }

    def complexity(self) -> int:
        return 3


@dataclass(frozen=True)
class CrossesBelowCondition:
    feature: str
    threshold: float
    prev_feature: str | None = None

    def evaluate(self, features: Mapping[str, float | None], state: PolicyState) -> bool:
        current_val = features.get(self.feature)
        prev_key = self.prev_feature or f"prev_{self.feature}"
        prev_val = features.get(prev_key)
        if current_val is None or prev_val is None:
            return False
        return prev_val >= self.threshold > current_val

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "crosses_below",
            "feature": self.feature,
            "threshold": self.threshold,
            "prev_feature": self.prev_feature,
        }

    def complexity(self) -> int:
        return 3


@dataclass(frozen=True)
class PersistsCondition:
    feature: str
    operator: str
    threshold: float
    periods: int = 2

    def __post_init__(self) -> None:
        if self.operator not in {">", "<"}:
            raise ValueError("PersistsCondition operator must be '>' or '<'")
        if self.periods < 1:
            raise ValueError("PersistsCondition periods must be positive")

    def evaluate(self, features: Mapping[str, float | None], state: PolicyState) -> bool:
        current_val = features.get(self.feature)
        if current_val is None:
            return False
        passed = (current_val > self.threshold) if self.operator == ">" else (current_val < self.threshold)
        if not passed:
            return False
        for p in range(1, self.periods):
            hist_val = features.get(f"prev_{self.feature}_{p}")
            if hist_val is None and p == 1:
                hist_val = features.get(f"prev_{self.feature}")
            if hist_val is None:
                return False
            p_passed = (hist_val > self.threshold) if self.operator == ">" else (hist_val < self.threshold)
            if not p_passed:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "persists",
            "feature": self.feature,
            "operator": self.operator,
            "threshold": self.threshold,
            "periods": self.periods,
        }

    def complexity(self) -> int:
        return 3 + self.periods


@dataclass(frozen=True)
class StochasticCondition:
    probability: float
    seed_feature: str = "decision_index"

    def evaluate(self, features: Mapping[str, float | None], state: PolicyState) -> bool:
        idx = features.get(self.seed_feature, 0.0)
        if idx is None:
            return False
        hash_val = (math.sin(float(idx) * 12.9898 + 78.233) * 43758.5453) % 1.0
        return abs(hash_val) < self.probability

    def to_dict(self) -> dict[str, Any]:
        return {"type": "stochastic", "probability": self.probability, "seed_feature": self.seed_feature}

    def complexity(self) -> int:
        return 5


@dataclass(frozen=True)
class NonlinearCondition:
    """Non-grammar / out-of-family condition."""
    formula: str
    threshold: float = 0.0

    def evaluate(self, features: Mapping[str, float | None], state: PolicyState) -> bool:
        f1 = features.get("ret5", 0.0) or 0.0
        f2 = features.get("spread", 0.0) or 0.0
        score = (f1 ** 2) + math.sin(f2 * 10.0)
        return score > self.threshold

    def to_dict(self) -> dict[str, Any]:
        return {"type": "out_of_family_nonlinear", "formula": self.formula, "threshold": self.threshold}

    def complexity(self) -> int:
        return 10


@dataclass(frozen=True)
class StateCondition:
    expected_state: int

    def evaluate(self, features: Mapping[str, float | None], state: PolicyState) -> bool:
        return state.state_register == self.expected_state

    def to_dict(self) -> dict[str, Any]:
        return {"type": "state_condition", "expected_state": self.expected_state}

    def complexity(self) -> int:
        return 2


@dataclass(frozen=True)
class TimeWindowCondition:
    start_hour: int
    end_hour: int
    days_of_week: tuple[int, ...] = (0, 1, 2, 3, 4)

    def evaluate(self, features: Mapping[str, float | None], state: PolicyState) -> bool:
        hour = features.get("hour_utc")
        dow = features.get("day_of_week")
        if hour is None:
            return False
        in_hour = self.start_hour <= int(hour) <= self.end_hour
        in_dow = (dow is None) or (int(dow) in self.days_of_week)
        return in_hour and in_dow

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "time_window",
            "start_hour": self.start_hour,
            "end_hour": self.end_hour,
            "days_of_week": list(self.days_of_week),
        }

    def complexity(self) -> int:
        return 3


@dataclass(frozen=True)
class TimeExit:
    holding_seconds: float

    def __post_init__(self) -> None:
        if self.holding_seconds <= 0:
            raise ValueError("holding_seconds must be positive")

    def should_exit(self, state: PolicyState, now: pd.Timestamp, bid: float, ask: float) -> str | None:
        if state.entry_time is None:
            return None
        return "time_exit" if now >= pd.Timestamp(state.entry_time) + pd.Timedelta(seconds=self.holding_seconds) else None

    def to_dict(self) -> dict[str, Any]:
        return {"type": "time_exit", "holding_seconds": self.holding_seconds}

    def complexity(self) -> int:
        return 2


@dataclass(frozen=True)
class PriceDistanceExit:
    take_profit: float | None = None
    stop_loss: float | None = None

    def __post_init__(self) -> None:
        if self.take_profit is not None and self.take_profit <= 0:
            raise ValueError("take_profit must be positive")
        if self.stop_loss is not None and self.stop_loss <= 0:
            raise ValueError("stop_loss must be positive")
        if self.take_profit is None and self.stop_loss is None:
            raise ValueError("price exit needs a take_profit or stop_loss")

    def should_exit(self, state: PolicyState, now: pd.Timestamp, bid: float, ask: float) -> str | None:
        if state.position_side is None or state.entry_price is None:
            return None
        executable = bid if state.position_side == "Buy" else ask
        signed_move = executable - state.entry_price if state.position_side == "Buy" else state.entry_price - executable
        if self.stop_loss is not None and signed_move <= -self.stop_loss:
            return "stop_loss"
        if self.take_profit is not None and signed_move >= self.take_profit:
            return "take_profit"
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"type": "price_distance_exit", "take_profit": self.take_profit, "stop_loss": self.stop_loss}

    def complexity(self) -> int:
        return 1 + int(self.take_profit is not None) + int(self.stop_loss is not None)


@dataclass(frozen=True)
class TrailingStopExit:
    trail_distance: float
    activation_distance: float = 0.0

    def __post_init__(self) -> None:
        if self.trail_distance <= 0:
            raise ValueError("trail_distance must be positive")
        if self.activation_distance < 0:
            raise ValueError("activation_distance cannot be negative")

    def should_exit(self, state: PolicyState, now: pd.Timestamp, bid: float, ask: float) -> str | None:
        if state.position_side is None or state.entry_price is None or state.highest_price is None:
            return None
        if state.position_side == "Buy":
            favorable_gain = state.highest_price - state.entry_price
            if favorable_gain >= self.activation_distance:
                drawdown = state.highest_price - bid
                if drawdown >= self.trail_distance:
                    return "trailing_stop"
        elif state.position_side == "Sell":
            favorable_gain = state.entry_price - state.highest_price
            if favorable_gain >= self.activation_distance:
                drawdown = ask - state.highest_price
                if drawdown >= self.trail_distance:
                    return "trailing_stop"
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "trailing_stop_exit",
            "trail_distance": self.trail_distance,
            "activation_distance": self.activation_distance,
        }

    def complexity(self) -> int:
        return 3


@dataclass(frozen=True)
class CompositeExit:
    exits: tuple[ExitRule, ...]

    def should_exit(self, state: PolicyState, now: pd.Timestamp, bid: float, ask: float) -> str | None:
        for rule in self.exits:
            reason = rule.should_exit(state, now, bid, ask)
            if reason is not None:
                return reason
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"type": "composite_exit", "exits": [e.to_dict() for e in self.exits]}

    def complexity(self) -> int:
        return 1 + sum(e.complexity() for e in self.exits)


@dataclass(frozen=True)
class Policy:
    entry: Condition
    side: Action
    volume: float = 0.01
    cooldown_seconds: float = 0.0
    exit_rule: ExitRule | None = None
    name: str = "candidate"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    state_transitions: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.side not in {Action.OPEN_BUY, Action.OPEN_SELL, Action.PLACE_LIMIT}:
            raise ValueError("A simple entry Policy side must be open_buy, open_sell, or place_limit")
        if self.volume <= 0:
            raise ValueError("volume must be positive")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds cannot be negative")

    def decide(self, features: Mapping[str, float | None], state: PolicyState, now: object) -> Action:
        if state.position_side is not None:
            return Action.NONE
        if state.pending_order_side is not None:
            return Action.NONE
        if state.cooldown_until is not None and now < state.cooldown_until:
            return Action.NONE
        return self.side if self.entry.evaluate(features, state) else Action.NONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "entry": self.entry.to_dict(),
            "condition": self.entry.to_dict(),
            "side": self.side.value,
            "volume": self.volume,
            "cooldown_seconds": self.cooldown_seconds,
            "exit_rule": self.exit_rule.to_dict() if self.exit_rule is not None else None,
            "metadata": dict(self.metadata),
            "complexity": self.complexity(),
            "state_transitions": dict(self.state_transitions),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Policy":
        entry_raw = data.get("entry") or data.get("condition")
        if entry_raw is None:
            raise ValueError("Policy dict must contain 'entry' or 'condition'")
        entry = condition_from_dict(entry_raw)
        side = Action(data["side"])
        volume = float(data.get("volume", 0.01))
        cooldown = float(data.get("cooldown_seconds", 0.0))
        exit_rule = exit_rule_from_dict(data["exit_rule"]) if data.get("exit_rule") else None
        name = str(data.get("name", "candidate"))
        metadata = dict(data.get("metadata", {}))
        state_transitions = {str(k): int(v) for k, v in data.get("state_transitions", {}).items()}
        return cls(
            entry=entry,
            side=side,
            volume=volume,
            cooldown_seconds=cooldown,
            exit_rule=exit_rule,
            name=name,
            metadata=metadata,
            state_transitions=state_transitions,
        )

    def complexity(self) -> int:
        return (
            3
            + self.entry.complexity()
            + (1 if self.cooldown_seconds else 0)
            + (self.exit_rule.complexity() if self.exit_rule else 0)
            + len(self.state_transitions)
        )


def condition_from_dict(data: Mapping[str, Any]) -> Condition:
    """Deserialize a Condition object from dictionary representation."""
    ctype = data.get("type", "threshold")
    if ctype == "threshold":
        return ThresholdCondition(
            feature=str(data["feature"]),
            operator=str(data["operator"]),
            threshold=float(data["threshold"]),
        )
    elif ctype == "and":
        return AndCondition(tuple(condition_from_dict(c) for c in data.get("children", data.get("clauses", []))))
    elif ctype == "or":
        return OrCondition(tuple(condition_from_dict(c) for c in data.get("children", data.get("clauses", []))))
    elif ctype == "not":
        return NotCondition(condition_from_dict(data.get("child", data.get("clause"))))
    elif ctype == "crosses_above":
        return CrossesAboveCondition(
            feature=str(data["feature"]),
            threshold=float(data["threshold"]),
            prev_feature=data.get("prev_feature"),
        )
    elif ctype == "crosses_below":
        return CrossesBelowCondition(
            feature=str(data["feature"]),
            threshold=float(data["threshold"]),
            prev_feature=data.get("prev_feature"),
        )
    elif ctype == "persists":
        return PersistsCondition(
            feature=str(data["feature"]),
            operator=str(data["operator"]),
            threshold=float(data["threshold"]),
            periods=int(data.get("periods", 2)),
        )
    elif ctype == "state_condition":
        return StateCondition(expected_state=int(data["expected_state"]))
    elif ctype == "time_window":
        return TimeWindowCondition(
            start_hour=int(data["start_hour"]),
            end_hour=int(data["end_hour"]),
            days_of_week=tuple(int(d) for d in data.get("days_of_week", (0, 1, 2, 3, 4))),
        )
    else:
        raise ValueError(f"Unknown condition type: {ctype}")


def exit_rule_from_dict(data: Mapping[str, Any]) -> ExitRule:
    """Deserialize an ExitRule object from dictionary representation."""
    etype = data.get("type")
    if etype == "time_exit":
        return TimeExit(holding_seconds=float(data["holding_seconds"]))
    elif etype == "price_distance_exit":
        tp = float(data["take_profit"]) if data.get("take_profit") is not None else None
        sl = float(data["stop_loss"]) if data.get("stop_loss") is not None else None
        return PriceDistanceExit(take_profit=tp, stop_loss=sl)
    elif etype == "trailing_stop_exit":
        return TrailingStopExit(
            trail_distance=float(data["trail_distance"]),
            activation_distance=float(data.get("activation_distance", 0.0)),
        )
    elif etype == "composite_exit":
        return CompositeExit(tuple(exit_rule_from_dict(e) for e in data.get("exits", [])))
    else:
        raise ValueError(f"Unknown exit rule type: {etype}")



def calculate_mdl_code_length(policy: Policy) -> float:
    """Calculate the Minimum Description Length (MDL) code length in bits.

    Grammar bit-costs:
    - Base policy frame: log2(3 actions) + 16 bits (volume) + 16 bits (cooldown) = ~34 bits
    - Condition node: 3 bits (type tag) + feature index (log2(N_features)) + operator (2 bits) + 32 bits (float threshold)
    - Compound condition: 3 bits (type tag) + 4 bits (arity) + sum(child bits)
    - Exit rule: 3 bits (type tag) + parameters (32 bits per float)
    """
    comp = policy.complexity()
    # Baseline ~ 64 bits + ~32 bits per complexity unit
    return float(64.0 + 32.0 * comp)
