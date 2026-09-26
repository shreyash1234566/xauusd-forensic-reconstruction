# Censored Trading-Policy Identification (CTPI)

Status: canonical, permanent methodology

Adopted: 26 September 2026

## Purpose

CTPI is the governing scientific methodology for this project. It asks what
features or policy classes are identifiable from the 423-record trade ledger
and independent public market data. It does not presume that the original
source program is recoverable.

The older A-to-Z implementation plan remains an engineering reference. Where
sequencing or claims conflict, this document governs the scientific standard
and `CTPI_IMMEDIATE_EXECUTION_PLAN.md` governs the next work.

## Permanent evidence constraints

1. The only account evidence is the canonical 423-record ledger at
   `data/raw/trades_raw.tsv`.
2. `outputs/market_reconstruction/phase7c_trade_reconciliation.csv` is the
   canonical reconciliation against genuine historical raw XAUUSD ticks.
3. The hourly `data/market/raw_ticks/xauusd_ticks_<ISO>.json` files are genuine
   source evidence and must not be replaced by M1 interpolation or synthetic
   feeds.
4. Public quotes are not same-account broker quotes. Account uptime,
   eligibility, balance, margin, pending orders, execution instructions and
   internal state are unobserved.
5. All historical periods have influenced the investigation. They may support
   retrospective falsification and cross-validation, but none is a new,
   untouched lockbox for a positive discovery claim.
6. Pasted narratives are research context, not project evidence, unless their
   calculations, inputs and outputs are reproducible from the project.

## Mathematical target

The observed marked-event intensity is represented as

    mu(t, m) = a(t) * integral lambda_pi(s, m | F_s)
                            * p(t | s, execution) ds

where `a(t)` is latent account availability or eligibility, `lambda_pi` is the
candidate policy intensity, and the execution kernel maps an intended decision
to a recorded transaction.

The decomposition is not identifiable without assumptions. In particular,
availability and signal intensity can trade off while preserving the same
observed intensity. The project must therefore report assumptions and
equivalence classes rather than silently attributing every trade-free period to
the policy.

For any finite observed-history set D, two policies can agree on every history
in D and differ elsewhere. They then have the same likelihood on D despite
being different programs. Consequently, CTPI can establish uniqueness only
within a declared bounded grammar and observation model. It cannot prove
identity with an unrestricted original source program.

## Five permitted outcomes

Every final analysis must return exactly one of these outcomes, with its search
scope and assumptions:

1. `UNIQUE_WITHIN_DECLARED_GRAMMAR`
2. `OBSERVATIONAL_EQUIVALENCE_CLASS`
3. `PARTIAL_COMPONENTS_IDENTIFIED`
4. `INSUFFICIENT_STATISTICAL_POWER`
5. `STRUCTURALLY_NON_IDENTIFIABLE`

Several outcomes may apply to different components. For example, clock
structure may be partially identified while entry identity remains structurally
non-identifiable.

## Mandatory inference order

1. Freeze provenance, clocks, coverage, causal feature timing and the bounded
   candidate grammar.
2. Apply mechanism-relevant placebos before interpreting a positive
   permutation or likelihood result.
3. Calibrate recovery on planted policies using the real market stream and a
   declared observation/noise model.
4. Fit exposure-aware marked point-process models; do not reduce the problem to
   ordinary trade-versus-nontrade classification.
5. Use constrained program synthesis or AI only to propose executable
   candidates. Statistical evidence, MDL and autonomous replay decide whether
   a proposal survives.
6. Replay candidate-generated state over all supported opportunities. Penalize
   false extra trades, not just misses near known trades.
7. Search deliberately for distinct policies with equivalent evidence. Return
   an identifiability certificate or an explicit equivalence class.

## Hard placebo gate

A feature family cannot become accepted positive evidence until it survives
pre-registered, causally valid placebos appropriate to its mechanism. These
include, where supported:

- same-clock random-day controls;
- shifted-event controls;
- direction-label randomization;
- destroyed-feature controls;
- unrelated-market controls.

Permutation significance alone is insufficient when the feature can share
session, coverage or feed-activity structure with the event clock.

Negative tests may continue to falsify existing claims on the current ledger.
New positive claims require planted-truth calibration and must be labelled
retrospective unless genuinely untouched external evidence becomes available.

## Acceptance standard

A proposed complete policy must earn its complexity and jointly reproduce
entry timing, negative space, direction, size, exits and induced state. Required
evidence includes:

- exposure-aware predictive log likelihood or information gain;
- search-adjusted placebo evidence;
- positive net MDL evidence;
- chronological stability under declared internal validation;
- one-to-one event matching at a predeclared execution tolerance;
- autonomous full-sequence replay;
- sensitivity to feed, clock, execution and availability assumptions;
- comparison against simpler and structurally different rivals.

A planted-recovery failure narrows the framework's declared capability. A
candidate that fits but does not earn its description length is rejected. A
candidate that cannot suppress extra trades is not an algorithm reconstruction.

## Role of AI

AI may generate hypotheses, candidate programs, adversarial alternatives and
diagnostic experiments. It cannot increase the information contained in the
ledger. No AI-generated explanation is accepted without passing the same
placebo, calibration, MDL and replay gates.

