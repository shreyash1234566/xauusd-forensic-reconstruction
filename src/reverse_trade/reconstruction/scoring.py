"""Scoring helpers that retain unknown support rather than invent negatives."""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np


def entry_error_loss(tp: int, fp: int, fn: int, supported_observed: int) -> float:
    if supported_observed < 0:
        raise ValueError("supported_observed cannot be negative")
    return (fp + fn) / supported_observed if supported_observed else math.nan


def bits_per_event(candidate_log_likelihood: float, baseline_log_likelihood: float, events: int) -> float:
    if events <= 0:
        return math.nan
    return (candidate_log_likelihood - baseline_log_likelihood) / (events * math.log(2.0))


def candidate_objective(negative_log2_probability: float, code_length: float) -> float:
    if not np.isfinite(negative_log2_probability) or not np.isfinite(code_length):
        return math.inf
    if code_length < 0:
        raise ValueError("code_length cannot be negative")
    return negative_log2_probability + code_length
