# CTPI terminal closure report

Status: **authoritative final project verdict**  
Closed: 27 September 2026

This document supersedes earlier narrative conclusions about whether the
original trading algorithm was recovered. The underlying artifacts remain the
evidence record; this report consolidates their permitted claims and stopping
rules.

## Final answer

The unique original trading algorithm cannot be determined from the 423-trade
ledger and available public market data.

The investigation identified three partial behavioral components: session or
clock structure, weak tick-rate structure beyond the clock, and short-horizon
contrarian direction. None identifies the entry trigger, and their frozen
combination does not reproduce the observed entries. No tested exit-state or
peak-distance hazard provides an absolutely calibrated exit model. The exact
unrestricted source policy remains structurally non-identifiable from any
finite ledger because distinct programs can agree on every observed history
and differ elsewhere.

The evidence base is closed for data-driven discovery. This is an evidentiary
boundary, not proof that the account had no systematic policy.

## Evidence and provenance

- Canonical account ledger: `data/raw/trades_raw.tsv`
- Canonical ledger SHA-256:
  `3B22B24C5F7BEB2118FFEC613640A9AB1472C3D04E4503229D00771277E4B6BD`
- Canonical trade-to-market reconciliation:
  `outputs/market_reconstruction/phase7c_trade_reconciliation.csv`
- Genuine historical tick archive:
  `data/market/raw_ticks/xauusd_ticks_<ISO>.json`
- Permanent methodology: `docs/CTPI_METHODOLOGY.md`

Public quotes are not same-account broker quotes. Account availability,
eligibility, balance, margin, pending orders, execution instructions, stop and
target modifications, costs and internal EA state remain unobserved. M1
interpolation and synthetic/modelled feeds are not substitutes for the
canonical raw-tick evidence.

The old `scripts/phase8c_exit_falsification.py` candidate table is excluded
from evidence because multiple candidate rows contain literal hard-coded
results rather than computed measurements.

## 1. What is identified

### Clock and session structure

The frozen clock model carries real but modest timing information. On the
lockbox it achieved 0.32648 bits/event against a constant full-exposure model.
Within the supported matched risk sets it achieved 0.04582 bits/event against
a uniform eligible-time reference, with randomization p=0.0149.

These numbers answer different comparisons and must not be added together.
They identify nonuniform trading intensity, not an entry command.

### Weak tick-rate structure

The same-clock random-day placebo retained 50 supported strata and produced
0.04697 bits/event with p=0.0035. The median stratum contribution was negative
and the largest stratum supplied most of the positive evidence. The permitted
claim is therefore a weak, heterogeneous intensity component. No tick-rate
threshold or complete entry rule is identified.

### Short-horizon contrarian direction

The shifted-event direction placebo retained 406 of 420 supported epochs. The
maximum contrarian strength was 0.1148 above chance at 20 minutes, the
search-corrected p-value was 0.00049975, and all seven predeclared windows from
2 to 20 minutes were significant. The effect decayed toward chance at long
horizons.

This identifies a directional tendency conditional on a trade occurring. It
does not identify when a trade occurs or the exact formula used for direction.

### Combined replay boundary

The discovery-frozen clock plus tick-rate projection produced complete-ledger
entry precision 0.0177, recall 0.0167 and F1 0.0172. Adding the contrarian
direction requirement produced F1 0.00735. Both lockbox F1 values were zero.

The components are real associations but do not combine into a deterministic
entry trigger.

## 2. What is frozen and why

### Entry mechanism

At approximately 420 events, the planted clock-plus-direction mechanism was
detected as a family but failed the project's MDL acceptance gate in every
replicate under both tested noise scenarios. This establishes limited power
for that mechanism class under the current MDL specification; it is not a
universal sample-size theorem.

The frozen sample-size curve produced:

| Total events | Continuous low noise | Censored/execution noise |
| ---: | ---: | ---: |
| 800 | 21% joint MDL acceptance | 32% joint MDL acceptance |
| 1,600 | 100% | 100% |
| 3,200 | 100% | 100% |

The first tested grid point with at least 80% joint acceptance was **1,600
total events**. Starting from about 420 usable events, that is approximately
**1,180 additional comparable events**. The actual crossing lies somewhere
between the tested 800- and 1,600-event points and depends on the declared
mechanism and noise model.

No more entry features, thresholds, clocks, grammars or replay calibrations may
be selected from this ledger.

### Exit mechanism

The raw-tick exit investigation retained 394 trades with adequate paths,
including 296 discovery and 98 chronological lockbox trades. None of nine
predeclared causal state variables survived the Holm-corrected lockbox gate.

- Closest single feature, 15-second tick rate: 0.02744 bits/exit; raw p=0.02405;
  Holm p=0.24049.
- Combined market state: 0.03379 bits/exit; Holm p=0.58317.
- Combined-model absolute time-rescaling test: KS p=0.00030344.

The terminal exposure-corrected diagnostic then tested the one remaining
mechanistically motivated coordinate: nonlinear distance from the running
favorable peak.

| Exit hazard | Bits/exit versus age | KS p | Result |
| --- | ---: | ---: | --- |
| Age and calendar | 0 | 0.00067807 | Fail |
| Peak distance and calendar | -0.01923 | 0.01006446 | Fail |
| Age plus peak distance | -0.01641 | 0.00690516 | Fail |

The peak-distance model improved the KS statistic relative to age alone but
still failed the predeclared p>=0.05 calibration gate and reduced predictive
likelihood. Exit reconstruction is frozen. No further exit variables or
reparameterizations may be selected from this ledger.

### Size and complete lifecycle policy

No causal size mechanism or complete entry-direction-size-exit state machine
passed CTPI's placebo, MDL, absolute goodness-of-fit and autonomous replay
requirements. Descriptive lot-size and holding-time patterns are not policy
identification.

## 3. What is non-identifiable in principle

Let `D` be the finite set of observed market histories. For any policy `pi`
that matches the observations, another policy `pi'` can be constructed such
that

    pi'(h) = pi(h) for every h in D

while `pi'` differs on an unobserved history. Both policies have the same
likelihood on `D` but are different programs. Therefore no finite ledger can
prove identity with an unrestricted original source program.

Observed event intensity also combines hidden account availability and policy
intensity:

    observed intensity = availability * policy intensity * execution mapping

Different decompositions can produce the same observed trades. More events can
shrink an equivalence class and may identify a behavioral rule within a frozen
grammar, but they cannot establish unique unrestricted source code without
additional assumptions or native artifacts.

## Permanent reopening conditions

This project may be reopened only under one of the following conditions.

### Independent external hypothesis

A specific policy claim must originate outside this ledger and be written down
before testing. Valid origins include an account-owner statement, native EA
configuration, source fragment or vendor documentation. Before any execution,
the record must freeze:

1. the executable entry, direction, size and/or exit rule;
2. all parameters and state transitions;
3. required market and account inputs;
4. timestamp and execution tolerance;
5. coverage and exclusion rules;
6. acceptance criteria and multiplicity treatment.

The hypothesis receives one frozen evaluation. It may be confirmed, rejected
or declared untestable. It may not be tuned on these trades and tested again on
the same evidence. Because all current periods have influenced the
investigation, a positive result on this ledger remains retrospective.

### New independent trade evidence

New public ticks without new account trades do not reopen identification. A
new same-system ledger can be evaluated once with the CTPI pipeline frozen
before inspection. For the planted mechanism and noise models actually tested,
1,600 total comparable events was the first grid point with high joint MDL
acceptance. This is a planning threshold, not a guarantee or universal floor.

### Native broker or EA artifacts

Previously unavailable orders, deals, journals, stop/target modifications,
same-account quotes, configuration or source material may change the
observation model. Such evidence must be preserved and hashed before analysis;
it cannot be synthesized or approximated by a public feed.

## Prohibited work on the frozen ledger

- no additional feature hunting or threshold search;
- no new entry or exit functional forms chosen after reviewing current results;
- no reuse of the opened lockbox as independent confirmation;
- no substitution of synthetic, interpolated or M1-modelled feeds for genuine
  raw ticks;
- no promotion of descriptive correlations into algorithm claims;
- no use of the excluded hard-coded Phase 8C table as evidence.

## The preserved framework

CTPI remains useful beyond this ledger. Its reusable architecture is:

1. immutable provenance and observation-model audit;
2. exposure-aware marked point-process or survival likelihood;
3. causal risk sets and negative-space accounting;
4. mechanism-specific placebos with family-wise correction;
5. planted-truth recovery and sample-size calibration;
6. constrained symbolic synthesis with MDL;
7. absolute time-rescaling goodness-of-fit;
8. autonomous sequential replay with false-positive penalties;
9. adversarial equivalent-policy search and an identifiability certificate.

AI may propose hypotheses and adversarial alternatives, but it cannot add
information to a ledger or waive these gates.

## Terminal component taxonomy

| Component | Final status |
| --- | --- |
| Clock/session structure | `PARTIAL_COMPONENTS_IDENTIFIED` |
| Tick-rate structure | `PARTIAL_COMPONENTS_IDENTIFIED` (weak and heterogeneous) |
| Contrarian direction | `PARTIAL_COMPONENTS_IDENTIFIED` |
| Entry mechanism | `INSUFFICIENT_STATISTICAL_POWER` under the tested MDL mechanism class |
| Exit mechanism | `INSUFFICIENT_STATISTICAL_POWER` / tested functional families rejected |
| Size mechanism | `INSUFFICIENT_STATISTICAL_POWER` |
| Complete lifecycle policy | `INSUFFICIENT_STATISTICAL_POWER` within the tested grammar |
| Unique unrestricted source policy | `STRUCTURALLY_NON_IDENTIFIABLE` |

## Authoritative supporting artifacts

- `outputs/ctpi_immediate/CTPI_RECOVERABILITY_REPORT.md`
- `outputs/ctpi_immediate/recoverability_verdict.json`
- `outputs/ctpi_next_tracks/CTPI_NEXT_TRACKS_REPORT.md`
- `outputs/ctpi_next_tracks/sample_size_power_curve.json`
- `outputs/ctpi_next_tracks/validated_component_replay.json`
- `outputs/ctpi_exit_investigation/CTPI_EXIT_REPORT.md`
- `outputs/ctpi_exit_investigation/exit_recoverability_verdict.json`
- `outputs/ctpi_exit_peak_distance/CTPI_PEAK_DISTANCE_REPORT.md`
- `outputs/ctpi_exit_peak_distance/peak_distance_verdict.json`

Earlier reports remain historical audit records. If their narrative conflicts
with this document, this terminal closure report governs.
