# CTPI Immediate Execution Plan

Status: active execution sequence

Adopted: 26 September 2026

Execution status: completed on 26 September 2026 by
`scripts/ctpi_immediate_execution.py`. The authoritative result is
`outputs/ctpi_immediate/CTPI_RECOVERABILITY_REPORT.md`; machine-readable
component results and the complete evidence manifest are stored beside it.

This six-step sequence answers the immediate recoverability question without
requiring the complete CTPI recovery phase diagram first. It is subordinate to
the permanent methodology in `CTPI_METHODOLOGY.md`.

## Step 1 — Reconcile the evidentiary record

Apply one verification standard to the external same-clock placebo claim and
the local Phase 13 clock-offset analysis:

- locate or reproduce the exact commands, inputs, seeds and environment;
- regenerate machine-readable output artifacts;
- verify canonical input hashes and causal feature timing;
- compare reported numbers with regenerated numbers;
- label each claim `VERIFIED`, `FAILED_REPRODUCTION` or
  `UNVERIFIED_EXTERNAL_CLAIM`;
- store a compact tracked evidence manifest even when bulk outputs remain
  intentionally ignored by version control.

The Phase 13 output directory exists in the current local workspace. Existence
alone is not independent verification or proof that artifacts are tracked.

## Step 2 — Test `tick_rate_ratio` with the hard placebo gate

Before treating `tick_rate_ratio` as evidence beyond the frozen clock offset,
run a same-clock random-day placebo that preserves calendar/session exposure
and uses causally available features. Freeze matching, exclusion, coverage and
test statistics before seeing the result.

The feature survives only if its real-event statistic beats the registered
placebo distribution after the declared search adjustment. Otherwise retire
the activity/tick-rate family for positive reconstruction claims.

## Step 3 — Run a narrow planted-truth calibration

Plant a modest clock-plus-direction policy in the genuine market stream and
generate approximately 420 observed trades under predeclared execution noise,
feed mismatch and availability scenarios. Do not inject the exact planted
program directly into a privileged candidate list.

Measure:

- recovery of the correct policy family;
- recovery of clock and direction components separately;
- false-extra-trade burden;
- MDL selection against simpler and rival policies;
- frequency of correct uniqueness, equivalence and non-identification verdicts.

This targeted calibration answers whether a policy of the hypothesized
complexity is recoverable at the available sample size. The broader CTPI phase
diagram remains later research, not a blocker for this test.

## Step 4 — Diagnose latent availability `a(t)`

Represent account availability explicitly in the observation model and final
claims. Analyze long trade-free gaps, calendar gaps and coverage gaps only as a
sensitivity diagnostic. Compare bounded scenarios such as continuous
availability and parsimonious availability blocks.

Do not infer downtime merely from the absence of trades, and do not allow a
highly flexible availability process to explain away every candidate failure.

## Step 5 — Issue the five-outcome recoverability report

Use the CTPI taxonomy separately for entry timing, direction, size, exits and
the complete policy. The current prior position, subject to Steps 1–4, is:

- clock/session structure: positive partial evidence;
- `tick_rate_ratio`: provisional; placebo required;
- contrarian direction: user-supplied prior claim whose reported p-value is not
  currently reproducible from a stored project artifact; reproduction and a
  suitable placebo are required before promotion to established evidence;
- entry mechanism: not identified;
- size and exit mechanisms: not identified;
- unrestricted original source policy: structurally non-identifiable.

The report must distinguish a falsified family, insufficient power, missing
observation support and structural non-identifiability.

## Step 6 — Rank independent evidence above further mining

A genuinely untouched second ledger from the same system would be more
valuable for positive confirmation than additional feature mining on these 423
trades. Such evidence is not currently available and is not requested as a
prerequisite. Under the fixed project constraint, conclude from Steps 1–5 and
do not replace absent account evidence with synthetic or interpolated data.

## Immediate stopping rule

After Steps 1–5:

- if planted recovery fails, report that the present framework/data cannot
  reliably recover even the targeted modest policy class;
- if planted recovery succeeds but the real claims fail placebos, report
  falsified feature families and partial clock structure only;
- if planted recovery succeeds and a real component survives the complete
  gate, report that component as retrospective evidence, not untouched external
  confirmation;
- if several policies survive, return their equivalence class rather than
  selecting one arbitrarily.
