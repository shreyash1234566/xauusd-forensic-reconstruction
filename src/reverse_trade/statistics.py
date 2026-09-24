"""Small, explicit statistical helpers used by the analysis pipeline."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable

import numpy as np
from scipy import stats


def finite(values: Iterable[float]) -> np.ndarray:
    array = np.asarray(list(values), dtype=float)
    return array[np.isfinite(array)]


def percentile_ci(
    values: Iterable[float],
    statistic: Callable[[np.ndarray], float] = np.mean,
    *,
    confidence: float = 0.95,
    repetitions: int = 10_000,
    seed: int = 20260919,
) -> tuple[float, float]:
    """Return a deterministic non-parametric percentile bootstrap interval."""

    array = finite(values)
    if array.size == 0:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    batch = 1_000
    estimates: list[np.ndarray] = []
    remaining = repetitions
    while remaining:
        size = min(batch, remaining)
        samples = rng.choice(array, size=(size, array.size), replace=True)
        estimates.append(np.apply_along_axis(statistic, 1, samples))
        remaining -= size
    distribution = np.concatenate(estimates)
    alpha = (1.0 - confidence) / 2.0
    low, high = np.quantile(distribution, [alpha, 1.0 - alpha])
    return float(low), float(high)


def cluster_bootstrap_ci(
    values: Iterable[float],
    clusters: Iterable[object],
    statistic: Callable[[np.ndarray], float] = np.mean,
    *,
    confidence: float = 0.95,
    repetitions: int = 10_000,
    seed: int = 20260919,
) -> tuple[float, float]:
    """Bootstrap whole clusters, preserving within-cluster observations."""

    value_array = np.asarray(list(values), dtype=float)
    cluster_array = np.asarray(list(clusters), dtype=object)
    if value_array.size == 0 or value_array.size != cluster_array.size:
        return math.nan, math.nan
    unique = np.unique(cluster_array)
    members = {cluster: value_array[cluster_array == cluster] for cluster in unique}
    rng = np.random.default_rng(seed)
    estimates = np.empty(repetitions, dtype=float)
    for index in range(repetitions):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        estimates[index] = statistic(np.concatenate([members[cluster] for cluster in sampled]))
    alpha = (1.0 - confidence) / 2.0
    low, high = np.quantile(estimates, [alpha, 1.0 - alpha])
    return float(low), float(high)


def proportion_ci(successes: int, total: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""

    if total <= 0:
        return math.nan, math.nan
    z = stats.norm.ppf(1.0 - (1.0 - confidence) / 2.0)
    p = successes / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denominator
    half = z * math.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total * total)) / denominator
    return float(center - half), float(center + half)


def permutation_test(
    first: Iterable[float],
    second: Iterable[float],
    *,
    statistic: Callable[[np.ndarray], float] = np.mean,
    repetitions: int = 10_000,
    seed: int = 20260919,
) -> dict[str, float]:
    """Two-sided label-permutation test for a difference in a statistic."""

    a = finite(first)
    b = finite(second)
    if a.size == 0 or b.size == 0:
        return {"difference": math.nan, "p_value": math.nan}
    observed = float(statistic(a) - statistic(b))
    pooled = np.concatenate([a, b])
    rng = np.random.default_rng(seed)
    extreme = 0
    for _ in range(repetitions):
        permuted = rng.permutation(pooled)
        difference = float(statistic(permuted[: a.size]) - statistic(permuted[a.size :]))
        extreme += abs(difference) >= abs(observed)
    return {"difference": observed, "p_value": (extreme + 1.0) / (repetitions + 1.0)}


def permutation_binary_statistic(
    labels: Iterable[int],
    statistic: Callable[[np.ndarray], float],
    *,
    repetitions: int = 10_000,
    seed: int = 20260919,
) -> dict[str, float]:
    values = np.asarray(list(labels), dtype=int)
    observed = float(statistic(values))
    rng = np.random.default_rng(seed)
    null = np.empty(repetitions, dtype=float)
    for index in range(repetitions):
        null[index] = statistic(rng.permutation(values))
    p_value = (np.count_nonzero(np.abs(null - np.mean(null)) >= abs(observed - np.mean(null))) + 1) / (
        repetitions + 1
    )
    return {
        "observed": observed,
        "null_mean": float(np.mean(null)),
        "null_sd": float(np.std(null, ddof=1)),
        "p_value": float(p_value),
    }


def benjamini_hochberg(p_values: Iterable[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values, preserving input order."""

    raw = np.asarray(list(p_values), dtype=float)
    adjusted = np.full(raw.shape, np.nan, dtype=float)
    valid = np.isfinite(raw)
    if not valid.any():
        return adjusted.tolist()
    valid_values = raw[valid]
    order = np.argsort(valid_values)
    ranked = valid_values[order]
    m = ranked.size
    scaled = ranked * m / np.arange(1, m + 1)
    scaled = np.minimum.accumulate(scaled[::-1])[::-1]
    scaled = np.clip(scaled, 0.0, 1.0)
    restored = np.empty(m, dtype=float)
    restored[order] = scaled
    adjusted[valid] = restored
    return adjusted.tolist()


def runs_test(binary_values: Iterable[int]) -> dict[str, float]:
    values = np.asarray(list(binary_values), dtype=int)
    if values.size < 2:
        return {"runs": math.nan, "expected": math.nan, "z": math.nan, "p_value": math.nan}
    n1 = int(np.count_nonzero(values == 1))
    n0 = int(np.count_nonzero(values == 0))
    if n1 == 0 or n0 == 0:
        return {"runs": 1.0, "expected": 1.0, "z": math.nan, "p_value": math.nan}
    runs = int(1 + np.count_nonzero(values[1:] != values[:-1]))
    total = n1 + n0
    expected = 1.0 + 2.0 * n1 * n0 / total
    variance = 2.0 * n1 * n0 * (2.0 * n1 * n0 - total) / (total * total * (total - 1.0))
    z = (runs - expected) / math.sqrt(variance)
    p_value = 2.0 * stats.norm.sf(abs(z))
    return {"runs": float(runs), "expected": float(expected), "z": float(z), "p_value": float(p_value)}


def longest_streak(values: Iterable[bool], target: bool) -> int:
    best = current = 0
    for value in values:
        if bool(value) is target:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def cramer_v(table: np.ndarray) -> float:
    table = np.asarray(table, dtype=float)
    if table.ndim != 2 or table.sum() == 0:
        return math.nan
    chi2 = stats.chi2_contingency(table, correction=False)[0]
    n = table.sum()
    denominator = min(table.shape[0] - 1, table.shape[1] - 1)
    return float(math.sqrt((chi2 / n) / denominator)) if denominator > 0 else math.nan


def json_number(value: float | np.floating | int | np.integer | None) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    number = float(value)
    return number if math.isfinite(number) else None
