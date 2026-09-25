"""Deterministic autonomous replay for simple market-order candidate policies.

The engine is intentionally conservative: a missing quote produces no invented
fill, and candidate state is never repaired from the observed ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from .policy_ast import Action, Policy, PolicyState
from .observation import ObservationScenario


@dataclass(frozen=True)
class Quote:
    timestamp_utc: pd.Timestamp
    bid: float
    ask: float
    source_id: str = "canonical_public_ticks"

    def __post_init__(self) -> None:
        time = pd.Timestamp(self.timestamp_utc)
        if time.tzinfo is None:
            object.__setattr__(self, "timestamp_utc", time.tz_localize("UTC"))
        else:
            object.__setattr__(self, "timestamp_utc", time.tz_convert("UTC"))
        if self.bid <= 0 or self.ask <= 0 or self.bid > self.ask:
            raise ValueError("Quote requires positive bid <= ask")


@dataclass(frozen=True)
class SimulatedTrade:
    trade_id: int
    side: str
    volume: float
    open_time_utc: pd.Timestamp
    open_price: float
    close_time_utc: pd.Timestamp | None = None
    close_price: float | None = None
    close_reason: str | None = None


@dataclass(frozen=True)
class ReplayEvent:
    event_index: int
    time_utc: pd.Timestamp
    event_type: str
    state_before: PolicyState
    action: str
    state_after: PolicyState
    detail: Mapping[str, object]


class ReplayEngine:
    """Replay quotes and independent decision boundaries in stable order."""

    def __init__(self, policy: Policy, scenario: ObservationScenario | None = None):
        self.policy = policy
        self.scenario = scenario or ObservationScenario("default_replay")

    @staticmethod
    def _quote_frame(quotes: Iterable[Quote]) -> pd.DataFrame:
        rows = [
            {"timestamp_utc": item.timestamp_utc, "bid": item.bid, "ask": item.ask, "source_id": item.source_id}
            for item in quotes
        ]
        frame = pd.DataFrame(rows)
        if frame.empty:
            return pd.DataFrame(columns=["timestamp_utc", "bid", "ask", "source_id"])
        return frame.sort_values(["timestamp_utc", "bid", "ask"], kind="mergesort").drop_duplicates(
            subset=["timestamp_utc"], keep="last"
        ).reset_index(drop=True)

    def run(
        self,
        quotes: Iterable[Quote],
        decisions: pd.DataFrame,
        *,
        record_trace: bool = True,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Run a policy using decision rows with a time and causal feature fields.

        Decisions require ``decision_time_utc``. All other columns become
        feature values. Quotes at exactly a decision time are available to an
        OnTick decision because the quote is processed before the decision;
        causal feature construction is separately responsible for excluding it
        when a feature's semantic contract requires strict precedence.
        """

        required = {"decision_time_utc"}
        if not required.issubset(decisions.columns):
            raise ValueError("decisions require decision_time_utc")
        quote_frame = self._quote_frame(quotes)
        decision_frame = decisions.copy()
        decision_frame["decision_time_utc"] = pd.to_datetime(decision_frame["decision_time_utc"], utc=True)
        decision_frame = decision_frame.sort_values("decision_time_utc", kind="mergesort").reset_index(drop=True)

        quote_records = [
            Quote(row.timestamp_utc, float(row.bid), float(row.ask), str(row.source_id))
            for row in quote_frame.itertuples(index=False)
        ]

        feature_cols = [
            c for c in decision_frame.columns
            if c not in {"decision_time_utc", "feature_status", "maximum_input_time"}
        ]
        decision_times = decision_frame["decision_time_utc"].tolist()
        decision_statuses = decision_frame.get("feature_status", pd.Series(["observed"] * len(decision_frame))).tolist()
        decision_features_list = decision_frame[feature_cols].to_dict("records")

        # Quote events get priority 0, decisions priority 1 at equal time.
        events: list[tuple[pd.Timestamp, int, int, str]] = []
        for index, q in enumerate(quote_records):
            events.append((q.timestamp_utc, 0, index, "quote"))
        for index, d_time in enumerate(decision_times):
            events.append((d_time, 1, index, "decision"))
        events.sort(key=lambda item: (item[0], item[1], item[2]))

        state = PolicyState()
        last_quote: Quote | None = None
        trades: list[SimulatedTrade] = []
        trace: list[ReplayEvent] = []
        event_index = 0
        for time, _, index, event_type in events:
            before = state
            if event_type == "quote":
                last_quote = quote_records[index]
                if state.pending_order_side is not None and state.position_side is None:
                    side = state.pending_order_side
                    due = pd.Timestamp(state.pending_order_due_time or state.pending_order_time)
                    due = due.tz_localize("UTC") if due.tzinfo is None else due.tz_convert("UTC")
                    is_market = state.pending_order_kind == "market"
                    limit_price = state.pending_order_price
                    executable = last_quote.ask if side == "Buy" else last_quote.bid
                    # Market orders fill on the first quote at/after their due time.
                    # Limits use the adverse executable side, never the midpoint.
                    should_fill = time >= due and (
                        is_market
                        or (
                            limit_price is not None
                            and ((last_quote.ask <= limit_price + 1e-9) if side == "Buy" else (last_quote.bid >= limit_price - 1e-9))
                        )
                    )
                    if should_fill:
                        fill_price = executable if is_market else float(limit_price)
                        trade = SimulatedTrade(len(trades), side, state.pending_order_volume, time, fill_price)
                        trades.append(trade)
                        next_state_reg = self.policy.state_transitions.get(side, state.state_register)
                        state = PolicyState(
                            position_side=side,
                            position_volume=state.pending_order_volume,
                            entry_price=fill_price,
                            entry_time=time,
                            highest_price=fill_price,
                            state_register=next_state_reg,
                        )
                        if record_trace:
                            trace.append(ReplayEvent(event_index, time, "fill", before, Action.NONE.value, state, {"trade_id": trade.trade_id, "fill_price": fill_price, "side": side, "order_kind": "market" if is_market else "limit"}))
                        event_index += 1
                        before = state
                if state.position_side == "Buy":
                    high = max(state.highest_price if state.highest_price is not None else (state.entry_price or last_quote.bid), last_quote.bid)
                    state = replace(state, highest_price=high)
                elif state.position_side == "Sell":
                    low = min(state.highest_price if state.highest_price is not None else (state.entry_price or last_quote.ask), last_quote.ask)
                    state = replace(state, highest_price=low)
                exit_reason = self.policy.exit_rule.should_exit(state, time, last_quote.bid, last_quote.ask) if self.policy.exit_rule else None
                if exit_reason is not None:
                    if not trades or state.position_side is None:
                        raise RuntimeError("Exit rule attempted to close a nonexistent candidate position")
                    current = trades[-1]
                    if current.close_time_utc is not None:
                        raise RuntimeError("Candidate position has already been closed")
                    close = last_quote.bid if state.position_side == "Buy" else last_quote.ask
                    trades[-1] = replace(current, close_time_utc=time, close_price=close, close_reason=exit_reason)
                    cooldown = time + pd.Timedelta(seconds=self.policy.cooldown_seconds)
                    exit_state = self.policy.state_transitions.get(
                        f"exit:{exit_reason}", self.policy.state_transitions.get("Exit", state.state_register)
                    )
                    state = PolicyState(cooldown_until=cooldown, state_register=exit_state)
                    if record_trace:
                        trace.append(ReplayEvent(event_index, time, "exit", before, Action.CLOSE_ALL.value, state, {"bid": last_quote.bid, "ask": last_quote.ask, "fill_price": close, "reason": exit_reason, "trade_id": current.trade_id}))
                    event_index += 1
                    before = state
                if record_trace:
                    trace.append(ReplayEvent(event_index, time, "quote", before, Action.NONE.value, state, {"bid": last_quote.bid, "ask": last_quote.ask}))
            else:
                features = {
                    column: (None if pd.isna(value) else float(value))
                    for column, value in decision_features_list[index].items()
                    if isinstance(value, (int, float, np.number, np.integer, np.floating))
                }
                status_val = str(decision_statuses[index])
                if status_val != "observed":
                    action = Action.NONE
                    reason = "unknown_features"
                elif last_quote is None:
                    action = Action.NONE
                    reason = "no_quote_available"
                else:
                    action = self.policy.decide(features, state, time)
                    reason = "policy"
                detail: dict[str, object] = {"reason": reason, "features": features}
                if action in {Action.OPEN_BUY, Action.OPEN_SELL} and last_quote is not None:
                    side = "Buy" if action == Action.OPEN_BUY else "Sell"
                    quote_age = time - last_quote.timestamp_utc
                    due = time + self.scenario.market_order_delay
                    can_fill_now = self.scenario.market_order_delay == pd.Timedelta(0) and quote_age <= self.scenario.timestamp_tolerance
                    if can_fill_now:
                        entry = last_quote.ask if side == "Buy" else last_quote.bid
                        trade = SimulatedTrade(len(trades), side, self.policy.volume, time, entry)
                        trades.append(trade)
                        next_state_reg = self.policy.state_transitions.get(side, state.state_register)
                        state = PolicyState(
                            position_side=side,
                            position_volume=self.policy.volume,
                            entry_price=entry,
                            entry_time=time,
                            highest_price=entry,
                            state_register=next_state_reg,
                        )
                        detail.update({"trade_id": trade.trade_id, "fill_price": entry, "side": side, "execution": "fresh_quote"})
                    else:
                        state = replace(
                            state,
                            pending_order_side=side,
                            pending_order_time=time,
                            pending_order_volume=self.policy.volume,
                            pending_order_kind="market",
                            pending_order_due_time=due,
                        )
                        detail.update({"side": side, "execution": "queued_market", "due_time": due.isoformat(), "quote_age_seconds": quote_age.total_seconds()})
                elif action == Action.PLACE_LIMIT and last_quote is not None:
                    side = "Buy"
                    limit_price = last_quote.ask
                    state = replace(
                        state,
                        pending_order_side=side,
                        pending_order_price=limit_price,
                        pending_order_time=time,
                        pending_order_volume=self.policy.volume,
                        pending_order_kind="limit",
                        pending_order_due_time=time,
                    )
                    detail.update({"action": "place_limit", "limit_price": limit_price, "side": side})
                if record_trace:
                    trace.append(ReplayEvent(event_index, time, "decision", before, action.value, state, detail))
            event_index += 1
        trade_columns = [
            "trade_id", "side", "volume", "open_time_utc", "open_price",
            "close_time_utc", "close_price", "close_reason",
        ]
        trade_frame = pd.DataFrame([
            {
                "trade_id": item.trade_id, "side": item.side, "volume": item.volume,
                "open_time_utc": item.open_time_utc, "open_price": item.open_price,
                "close_time_utc": item.close_time_utc, "close_price": item.close_price,
                "close_reason": item.close_reason,
            }
            for item in trades
        ], columns=trade_columns)
        trace_frame = pd.DataFrame([
            {
                "event_index": item.event_index, "time_utc": item.time_utc, "event_type": item.event_type,
                "state_before": repr(item.state_before), "action": item.action, "state_after": repr(item.state_after),
                **item.detail,
            }
            for item in trace
        ])
        return trade_frame, trace_frame
