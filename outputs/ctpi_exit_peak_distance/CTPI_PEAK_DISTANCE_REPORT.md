# CTPI terminal peak-distance exit diagnostic

## Decision

Peak-distance hazard fails the declared absolute calibration gate. Freeze exit reconstruction on this ledger.

This is a terminal prespecified diagnostic on the previously opened chronological
lockbox. It is not an independent confirmation test.

## Frozen acceptance rule

The primary `peak_distance_calendar` model passes only when its lockbox
time-rescaling KS p-value is at least 0.05. Failure freezes exit reconstruction
on this ledger. No further exit features are authorized by this diagnostic.

## Model

The hazard is piecewise exponential. Each risk interval contributes its exact
exposure in seconds. The primary hazard replaces holding-age terms with a
five-knot quadratic spline of `drawdown_from_mfe = MFE - unrealized_move`, while
retaining side and calendar controls. Hyperparameter selection uses discovery
data only.

| specification | bits/exit vs age model | sign-flip p | KS p | calibration |
| --- | ---: | ---: | ---: | --- |
| age_calendar | 0.0000 | 1 | 0.0006781 | FAIL |
| peak_distance_calendar | -0.0192 | 0.6013 | 0.01006 | FAIL |
| age_plus_peak_distance | -0.0164 | 0.619 | 0.006905 | FAIL |

The primary peak-distance result is -0.0192
bits per exit relative to the exposure-corrected age/calendar model, with KS
p=0.0100645.

## Interpretation

Passing calibration would show that peak-relative distance is an adequate state
coordinate for the observed exit-time distribution; it would not identify a
unique deterministic stop or original source code. Failing calibration rejects
this final motivated reparameterization under the available public-tick
observation model.
