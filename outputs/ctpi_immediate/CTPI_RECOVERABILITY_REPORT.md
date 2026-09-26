# CTPI Immediate Recoverability Report

## Result

**CTPI_PARTIAL_COMPONENTS_TICK_RATE_SURVIVES_RETROSPECTIVE_PLACEBO_NO_COMPLETE_POLICY**

This is a retrospective recoverability and falsification stage. It does not
restore an untouched lockbox and it does not identify the unrestricted original
source program.

## Evidence reconciliation

- Phase 13 reproduction status: **VERIFIED**.
- Exact artifact reproduction: **True**.
- External pasted placebo claim: **UNVERIFIED_EXTERNAL_CLAIM** until backed by
  executable artifacts.
- Reported direction p=0.0033: **UNVERIFIED_EXTERNAL_CLAIM**.

## `tick_rate_ratio` same-clock random-day placebo

- Included strata: **50**.
- Information versus a uniform eligible day: **0.0470 bits/event**.
- One-sided random-day p-value: **0.0035**.
- Gate: **SURVIVES_RETROSPECTIVE_PLACEBO**.
- Median stratum contribution: **-0.0043 bits**.
- Largest absolute stratum contribution: **1.5957 bits**.

The test uses causal features computed directly from genuine raw tick files at
the same UTC clock second and weekday on other dates. It does not use synthetic
ticks or M1 interpolation.

The aggregate likelihood gate passes, but the negative median contribution and
large maximum contribution show heterogeneous, concentrated evidence. This is
provisional evidence for a weak intensity component, not a threshold mechanism
or complete entry rule.

## Targeted 420-event planted recovery

| Scenario | Clock family | Clock after MDL | Contrarian family | Joint family |
|---|---:|---:|---:|---:|
| continuous_low_noise | 100.0% | 0.0% | 100.0% | 100.0% |
| censored_execution_noise | 100.0% | 0.0% | 100.0% | 100.0% |

This calibration measures whether the declared modest family is recoverable;
it is not evidence that the real account used that family.
The clock family was detectably predictive in every replicate, but it cleared
the registered MDL cost in **0%** of replicates. Median clock net MDL evidence
was **-37.52 bits**
without censoring and **-39.57 bits**
with censoring/execution noise. At this sample size, family detection is not
unique program identification.

## Availability diagnostic

- Assessment: **NO_STRONG_MAX_GAP_ANOMALY_UNDER_FROZEN_CLOCK_MODEL**.
- Clock-rescaled maximum-gap p-value: **0.9997**.

Long gaps cannot distinguish account downtime from genuine no-signal periods or
clock-model misspecification. Availability remains a named latent confound.

## Five-outcome taxonomy by component

| Component | CTPI outcome |
|---|---|
| clock_session_structure | PARTIAL_COMPONENTS_IDENTIFIED |
| tick_rate_ratio_beyond_clock | PARTIAL_COMPONENTS_IDENTIFIED |
| contrarian_direction | INSUFFICIENT_STATISTICAL_POWER |
| entry_mechanism | INSUFFICIENT_STATISTICAL_POWER |
| size_mechanism | INSUFFICIENT_STATISTICAL_POWER |
| exit_mechanism | INSUFFICIENT_STATISTICAL_POWER |
| complete_policy_within_current_search | INSUFFICIENT_STATISTICAL_POWER |
| unrestricted_original_source_policy | STRUCTURALLY_NON_IDENTIFIABLE |

## Decision

No compact complete entry/direction/size/exit algorithm is identified. A second
untouched ledger remains the most valuable possible positive confirmation, but
it is unavailable under the project constraint and is not requested. The
project must not replace it with synthetic account evidence.
