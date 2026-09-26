"""CTPI shifted-event placebo for the claimed short-horizon direction effect."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "ctpi_immediate"
LEDGER = ROOT / "data" / "raw" / "trades_raw.tsv"
EPOCH_MAP = ROOT / "outputs" / "strategy_reconstruction" / "phase10_11_decision_epoch_map.csv"
M1 = ROOT / "data" / "market" / "raw" / "xauusd_m1_utc_raw.csv"
WINDOWS = (2, 3, 5, 8, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360)
SHORT_WINDOWS = frozenset((2, 3, 5, 8, 10, 15, 20))
SEED = 20260926


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _return_vector(close: pd.Series, target: pd.Timestamp) -> np.ndarray | None:
    """Price changes ending at the last fully completed M1 bar."""

    end = target.floor("min") - pd.Timedelta(minutes=1)
    try:
        end_close = float(close.loc[end])
        values = [end_close - float(close.loc[end - pd.Timedelta(minutes=window)]) for window in WINDOWS]
    except KeyError:
        return None
    result = np.asarray(values, dtype=float)
    return result if np.all(np.isfinite(result)) else None


def _strengths(returns: np.ndarray, directions: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return momentum accuracy, contrarian accuracy, and excess over chance."""

    if returns.ndim != 2 or returns.shape[0] != len(directions):
        raise ValueError("returns must be event-by-window and align with directions")
    momentum = np.full(returns.shape[1], np.nan)
    contrarian = np.full(returns.shape[1], np.nan)
    counts = np.zeros(returns.shape[1], dtype=int)
    for column in range(returns.shape[1]):
        values = returns[:, column]
        valid = np.isfinite(values) & (values != 0)
        counts[column] = int(valid.sum())
        if valid.any():
            market_sign = np.where(values[valid] > 0, 1, -1)
            momentum[column] = float(np.mean(market_sign == directions[valid]))
            contrarian[column] = 1.0 - momentum[column]
    return momentum, contrarian, counts


def shifted_event_max_test(
    actual: np.ndarray,
    alternatives: list[np.ndarray],
    directions: np.ndarray,
    *,
    permutations: int = 2000,
    seed: int = SEED,
) -> tuple[pd.DataFrame, dict]:
    """One-sided, max-window corrected random-day placebo test."""

    if len(actual) != len(alternatives) or len(actual) != len(directions):
        raise ValueError("actual, alternatives and directions must align")
    if any(array.ndim != 2 or array.shape[1] != actual.shape[1] or not len(array) for array in alternatives):
        raise ValueError("Each event needs at least one alternative with the same windows")
    observed_momentum, observed_contrarian, counts = _strengths(actual, directions)
    observed_strength = observed_contrarian - 0.5
    rng = np.random.default_rng(seed)
    null_strength = np.zeros((permutations, actual.shape[1]), dtype=float)
    for replicate in range(permutations):
        sampled = np.vstack([values[rng.integers(0, len(values))] for values in alternatives])
        _, contrarian, _ = _strengths(sampled, directions)
        null_strength[replicate] = contrarian - 0.5
    null_max = np.nanmax(null_strength, axis=1)
    max_index = int(np.nanargmax(observed_strength))
    max_p = float((1 + np.count_nonzero(null_max >= observed_strength[max_index] - 1e-12)) / (permutations + 1))
    rows = []
    for index, window in enumerate(WINDOWS):
        pvalue = float(
            (1 + np.count_nonzero(null_strength[:, index] >= observed_strength[index] - 1e-12))
            / (permutations + 1)
        )
        rows.append({
            "window_minutes": window,
            "n_nonzero": int(counts[index]),
            "momentum_accuracy": float(observed_momentum[index]),
            "contrarian_accuracy": float(observed_contrarian[index]),
            "contrarian_strength_over_chance": float(observed_strength[index]),
            "pointwise_placebo_pvalue": pvalue,
            "null_strength_mean": float(np.mean(null_strength[:, index])),
            "null_strength_q95": float(np.quantile(null_strength[:, index], 0.95)),
        })
    table = pd.DataFrame(rows)
    short = table.loc[table.window_minutes.isin(SHORT_WINDOWS)]
    gate = bool(
        max_p <= 0.05
        and observed_strength[max_index] > 0
        and int((short.pointwise_placebo_pvalue <= 0.05).sum()) >= 5
    )
    summary = {
        "max_stat_window_minutes": int(WINDOWS[max_index]),
        "max_observed_contrarian_strength": float(observed_strength[max_index]),
        "max_stat_shifted_event_pvalue": max_p,
        "permutations": permutations,
        "resolution_floor": 1.0 / (permutations + 1),
        "short_windows_pointwise_significant": int((short.pointwise_placebo_pvalue <= 0.05).sum()),
        "predeclared_short_windows": sorted(SHORT_WINDOWS),
        "gate": "SURVIVES_SHIFTED_EVENT_PLACEBO" if gate else "FAILS_SHIFTED_EVENT_PLACEBO",
    }
    return table, summary


def run(*, permutations: int = 2000) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    mapping = pd.read_csv(EPOCH_MAP)
    mapping["decision_time_utc"] = pd.to_datetime(mapping.decision_time_utc, utc=True, format="mixed")
    epochs = mapping.loc[mapping.is_epoch_anchor.astype(bool), ["epoch_id", "side", "decision_time_utc"]].copy()
    epochs = epochs.sort_values("decision_time_utc").reset_index(drop=True)
    epochs["direction"] = epochs.side.map({"Buy": 1, "Sell": -1})
    if epochs.direction.isna().any() or len(epochs) != 420:
        raise ValueError("Expected 420 canonical Buy/Sell epochs")

    bars = pd.read_csv(M1, usecols=["timestamp", "close"])
    bars["timestamp"] = pd.to_datetime(bars.timestamp, utc=True)
    close = bars.drop_duplicates("timestamp", keep="last").set_index("timestamp").close.sort_index()
    trading_days = sorted(pd.Series(close.index.floor("D").unique()).tolist())
    first_day = epochs.decision_time_utc.min().floor("D")
    last_day = epochs.decision_time_utc.max().floor("D")
    event_ns = np.sort(epochs.decision_time_utc.astype("int64").to_numpy())

    def is_far_from_event(target: pd.Timestamp) -> bool:
        value = int(target.value)
        position = int(np.searchsorted(event_ns, value))
        neighbours = []
        if position < len(event_ns):
            neighbours.append(abs(int(event_ns[position]) - value))
        if position:
            neighbours.append(abs(int(event_ns[position - 1]) - value))
        return not neighbours or min(neighbours) > 5 * 60 * 1_000_000_000

    actual_rows: list[np.ndarray] = []
    alternative_rows: list[np.ndarray] = []
    directions: list[int] = []
    audit: list[dict] = []
    for epoch in epochs.itertuples(index=False):
        target = pd.Timestamp(epoch.decision_time_utc)
        actual = _return_vector(close, target)
        alternatives: list[np.ndarray] = []
        candidate_dates: list[str] = []
        for day in trading_days:
            if day < first_day or day > last_day or day.date() == target.date() or day.dayofweek != target.dayofweek:
                continue
            shifted = day + pd.Timedelta(
                hours=target.hour, minutes=target.minute,
                seconds=target.second, microseconds=target.microsecond,
            )
            if not is_far_from_event(shifted):
                continue
            vector = _return_vector(close, shifted)
            if vector is not None:
                alternatives.append(vector)
                candidate_dates.append(str(day.date()))
        included = actual is not None and len(alternatives) >= 5
        if included:
            actual_rows.append(actual)
            alternative_rows.append(np.vstack(alternatives))
            directions.append(int(epoch.direction))
        audit.append({
            "epoch_id": int(epoch.epoch_id),
            "decision_time_utc": target.isoformat(),
            "side": epoch.side,
            "alternative_days": len(alternatives),
            "status": "included" if included else "excluded_missing_history_or_alternatives",
            "candidate_dates": "|".join(candidate_dates),
        })
    if not actual_rows:
        raise ValueError("No direction placebo strata survived coverage requirements")
    actual_matrix = np.vstack(actual_rows)
    direction_array = np.asarray(directions, dtype=int)
    table, summary = shifted_event_max_test(
        actual_matrix, alternative_rows, direction_array,
        permutations=permutations, seed=SEED,
    )
    table.to_csv(OUT / "direction_shifted_event_windows.csv", index=False)
    pd.DataFrame(audit).to_csv(OUT / "direction_shifted_event_strata.csv", index=False)
    payload = {
        "status": "complete",
        "method": "same UTC clock second and weekday on a different real trading date; labels fixed; max statistic across 15 predeclared windows",
        "causal_contract": "Each return ends at the close of the M1 bar immediately before the entry minute.",
        "source": "data/market/raw/xauusd_m1_utc_raw.csv (public Dukascopy bid M1; no interpolation)",
        "epochs_available": 420,
        "epochs_tested": len(actual_matrix),
        "minimum_alternative_days": 5,
        "event_exclusion_seconds": 300,
        "windows_minutes": list(WINDOWS),
        "input_hashes": {
            "data/raw/trades_raw.tsv": sha256(LEDGER),
            "outputs/strategy_reconstruction/phase10_11_decision_epoch_map.csv": sha256(EPOCH_MAP),
            "data/market/raw/xauusd_m1_utc_raw.csv": sha256(M1),
        },
        **summary,
        "window_results": table.to_dict(orient="records"),
        "interpretation_limit": "A surviving direction association is a partial component, not an entry trigger or source-policy identity.",
    }
    (OUT / "direction_shifted_event_placebo.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--permutations", type=int, default=2000)
    args = parser.parse_args()
    print(json.dumps(run(permutations=args.permutations), indent=2))


if __name__ == "__main__":
    main()

