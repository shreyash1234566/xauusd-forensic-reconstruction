# Hidden Trading Algorithm Reconstruction: A-to-Z Implementation Plan

Version 1.0 — 24 September 2026

Project: E:/reverse -traid

Status: implementation specification only. Creating this document does not run the investigation, download data, create the proposed modules, or establish any new strategy result.

## Purpose and honest success condition

Find the most accurate, compact, executable explanation of the recorded XAUUSD trading behavior that the available evidence can support.

The working framework is system identification of a partially observed, stateful trading policy. It combines marked event models, constrained program search, explicit execution uncertainty, and autonomous sequential replay.

The objective is to reconstruct when the policy trades, which direction it chooses, how much it trades, and how it exits. Similar profit alone does not satisfy that objective.

This plan is a reasoned recommendation, not a theorem that no better method exists. Its competing search methods must earn their place through the benchmarks and validation described below. A finite historical record cannot guarantee recovery of a unique original program.

## Non-negotiable constraints

1. The only account evidence is the existing 423-record trade ledger. Do not request or wait for account access, native orders, journals, account quotes, magic numbers, balances, or additional account trades.
2. Public historical market data may be obtained. Availability and provenance must be checked; a normal MT5 installation does not guarantee that a broker offers the required historical tick period.
3. Keep all new project work under E:/reverse -traid.
4. Preserve data/raw/trades_raw.tsv unchanged.
5. Preserve outputs/market_reconstruction/phase7c_trade_reconciliation.csv unchanged as the canonical trade-to-market alignment.
6. Preserve data/market/raw_ticks/xauusd_ticks_<ISO>.json as genuine historical source evidence. Never overwrite or substitute synthetic ticks or M1 interpolation.
7. Store additional downloads, alternative feeds, revised alignments, and synthetic calibration experiments separately and label them.
8. Preserve the 423-record ledger and the documented 420-epoch grouping. Grouping is an analytical convention, not direct observation of the original decision times.
9. Do not place trades, connect an execution account, publish files, or claim profitability as part of this research plan.
10. Never exclude an inconvenient trade merely because it contradicts a proposed rule.

Older documents that request unavailable account artifacts remain historical records. Those requests are not prerequisites for this plan.

## How to follow the plan

Complete A–M to establish evidence, a validation design, and tested infrastructure. Complete N–U to calibrate the methods and search for executable policies. Complete V–Z to validate, determine what is identifiable, and produce the final reconstruction package.

Each letter specifies work, outputs, and a completion gate. A failed technical gate is a reason to repair that component. An irreducible observation limit narrows the supported claim; it is not permission to invent data.

N is executed in two passes: first build the planted generators and benchmark specification; then develop O–U on toy/synthetic cases and complete the end-to-end N benchmark. Only after that benchmark passes do O–U search the real ledger. This avoids depending on an unbuilt search engine or using real outcomes to debug recovery.

The detailed engineering choices below are proposed adaptations for this project. The cited papers support particular methods; they do not validate these exact module names, parameter grids, budgets, or expected performance.

All output filenames below are proposed unless explicitly identified as existing. They are relative to the project root. New research outputs belong under outputs/reconstruction_v1/<run_id>/, so existing reports are not overwritten.

## A. Register the objective, scope, and allowed claims

### Work

1. Define three separate questions:
   - Does a candidate explain the observed entry process?
   - Does its complete replay reproduce the recorded transactions?
   - Is it distinguishable from other allowed candidates?
2. Define the observation interval from verified ledger timestamps and the declared clock conversion. Include market warm-up before it. Do not extend claimed account observation beyond the ledger's evidence boundary.
3. Record the fact that the old discovery and lockbox periods have already influenced research. New historical splits are internal validation, not a new untouched lockbox.
4. Register a search protocol before examining new candidate performance: feature families, grammar tiers, nuisance scenarios, validation folds, metrics, candidate budgets, and stopping rules.
5. Explicitly distinguish the original program, its behavior on this history, and a useful approximate reconstruction.

### Outputs

- research_protocol.json
- evidence_boundary.md
- analyst_exposure_log.md
- success_criteria.json

### Gate

Every requested conclusion has a metric and an evidence grade. No claim requires unavailable account records. No promised accuracy percentage is entered as an expected result.

## B. Audit and freeze the canonical evidence

### Work

1. Hash the ledger, reconciliation, epoch mapping, and source-lock files. Compare against the existing canonical lock.
2. Verify exactly 423 ledger records and their one-to-one correspondence to the reconciliation. Check duplicate tickets, malformed timestamps, direction, symbol, volume, recorded price, and P&L.
3. Preserve both the source row order and a separately derived chronological order.
4. Retain the three documented split pairs only:
   - 36168589 / 36168590
   - 36227385 / 36227388
   - 36335183 / 36335196
5. Produce 420 entry epochs using the existing grouping convention, while preserving all 423 records and their individual marks. Do not merge additional nearby trades.
6. Preserve raw timestamps alongside derived UTC timestamps and transformation IDs.
7. Inventory source files with hashes, sizes, actual timestamp bounds, provider IDs, and parser versions.

The existing lock records this ledger SHA-256:

    3B22B24C5F7BEB2118FFEC613640A9AB1472C3D04E4503229D00771277E4B6BD

Verify that value during implementation; do not merely copy it into a new report.

### Outputs

- evidence_manifest.json
- ledger_audit.json
- records.parquet
- epochs.parquet
- record_epoch_map.parquet

### Tests and gate

- Exactly 423 source records and 420 convention-based epochs.
- Each source record maps to one epoch.
- No original field silently changes.
- Hash discrepancies stop dependent scoring until their cause is resolved.

## C. Separate observed facts from derived quantities and inherited claims

### Work

Build a field dictionary with origin, units, semantic confidence, derivation, dependencies, and earliest availability time.

The current loader reads eight fields: ticket, side, open time, close time, symbol, volume, recorded price, and P&L. There is one recorded price, not two independently observed entry and exit prices. Phase 7C supports an entry-price interpretation; public-tick execution estimates remain derived observations.

Classify each old finding:

| Status | Meaning |
| --- | --- |
| Verified file fact | Directly checked against immutable evidence |
| Reproducible conditional result | Valid under listed assumptions |
| Exploratory hypothesis | Worth testing, not fixed truth |
| Invalidated result | Known implementation or inference defect |
| Unavailable | Cannot be established from these observations |

Audit, in particular:

- Earlier near-perfect classification affected by target/ticket leakage.
- Trade-conditioned hourly tick acquisition and coverage-dependent controls.
- Missing feature scores being classified as no action.
- Session gates that exclude actual entry epochs.
- Treating a non-significant timing test as proof against all bar-driven rules.
- Treating a feature-screen result as a universal information ceiling.
- Comparing planted raw coefficients with standardized fitted coefficients.
- The field called p_value_vs_null in the existing planted test: its calculation is a relative likelihood improvement, not a p-value.
- Existing R1 failure counts: retain the failure record, but recompute coverage-aware rates before using them as a benchmark.

### Outputs

- field_dictionary.json
- prior_claims_audit.csv
- inherited_hypotheses.json
- forbidden_predictors.json

### Gate

Every feature and target has a provenance label. No derived exit price or assumed account balance is presented as directly recorded evidence.

## D. Reconstruct market coverage before reconstructing opportunities

### Work

1. Read actual timestamp ranges inside each raw file; do not infer coverage from filenames alone.
2. Build expected hourly acquisition slots across the declared interval and warm-up.
3. Distinguish request failure, corrupt file, empty response, market closure, unverified outage, and valid low-activity periods.
4. Record tick count, bid/ask validity, monotonicity, duplicate timestamps, largest observed quote gap, and whether a request covered the intended interval.
5. Compute feature-specific coverage. A ten-second return and a one-hour indicator require different historical support.
6. Compare the original download-selection mechanism with the full interval. Explicitly document that initial files were selected largely around known trades.

A long gap between quotes is not automatically a failed download. Equally, a successful file read is not proof that the provider delivered a complete hour. Preserve both acquisition status and observable quote continuity.

### Outputs

- coverage_hours.parquet
- coverage_intervals.parquet
- feature_support_intervals.parquet
- coverage_report.md

### Gate

Every evaluated interval has an explicit coverage status. Unknown coverage cannot become a true negative. Reports provide both evaluated and unevaluable trade counts.

## E. Acquire missing public market history

### Work

1. Generate a date-based acquisition plan from D, independently of whether an hour contains a trade.
2. Estimate disk and runtime needs with a small, label-independent pilot.
3. Download missing genuine public bid/ask ticks using the provider's documented interface, permitted access, and rate limits.
4. Use resumable requests, bounded retries, checksums, and append-only storage. Never overwrite the locked archive.
5. Where feasible, obtain a second public feed over a predeclared common interval for sensitivity testing.
6. Verify the provider's timestamp units, timezone, quote convention, revisions, and historical coverage.
7. Retry technically failed requests. If history is genuinely unavailable, record that limit and continue supported analyses.

Suggested new raw location:

    data/market/supplemental_raw_ticks/<provider>/<retrieval_batch>/

For provider comparisons use the intersection of supported times, and separately report each feed's additional coverage. Do not select whichever feed happens to fit each individual trade best.

### Outputs

- acquisition_plan.json
- acquisition_log.jsonl
- supplemental_source_manifest.json
- revised_coverage_report.md

### Gate

Full-interval replication claims require coverage of all relevant decision, execution, and feature-history intervals. Partial coverage permits a partial evaluation, with its scope stated. The plan never switches to invented ticks to pass this gate.

## F. Normalize quotes and define deterministic event ordering

### Work

1. Preserve raw responses. Create an immutable normalized view indexed by provider and UTC time.
2. Store integer timestamps at the provider's actual resolution; do not claim nanosecond accuracy merely because the storage type supports it.
3. Retain bid, ask, source timestamp, optional provider sequence, flags, original-file reference, and any documented volume semantics.
4. Define duplicate handling. Exact duplicate records can be indexed once with provenance; different quotes with the same timestamp require stable ordering or an explicit ambiguity scenario.
5. Validate bid <= ask, positive prices, and plausible units. Quarantine invalid records without silently repairing them.
6. Do not treat quote volume as actual exchange trading volume unless the source documentation establishes that interpretation.
7. Aggregate completed M1/M5/M15/H1 bars from supported genuine ticks where useful. Label those bars as derived. They are feature inputs, not replacement execution observations.

### Outputs

- normalized tick partitions
- normalization_manifest.json
- quote_quality_report.md
- event_ordering_spec.md

### Tests and gate

Repeat normalization produces identical hashes. DST boundaries, equal timestamps, empty periods, and price-unit errors have explicit tests. Every normalized quote traces back to raw evidence.

## G. Define the observation and execution models

### Work

Keep separate:

    strategy decision -> order instruction -> possible execution -> recorded ledger row

Construct a small registered set of explanations for:

- Broker timestamp convention and DST rule.
- Timestamp rounding/truncation.
- Market-order delay.
- Pending-order placement and later execution.
- Public-feed versus original-feed price disagreement.
- Contract multiplier, cost, and rounding assumptions relevant to P&L.

The original broker's execution parameters are unknown. Use constrained scenarios or a declared probability model; do not fit an arbitrary offset, spread, or delay for each record.

The canonical alignment remains unchanged. Alternative assumptions create separate analysis views.

For a simplified P&L identity:

    recorded_pnl ~= side_sign * volume * multiplier * (exit_price - entry_price) - costs

This equation does not independently identify exit price, multiplier, and costs. If one is inferred from the others, it cannot then be counted as independent confirmation.

Distinguish the uncertainty band used for event matching from the entry-rule threshold. Estimate or choose bands using instrument precision, source comparisons, training data, and planted tests; freeze them before evaluation.

### Outputs

- observation_scenarios.json
- execution_semantics.md
- timestamp_intervals.parquet
- nuisance_parameter_constraints.json
- observation_sensitivity_design.json

### Gate

All observations use the same declared model within a scenario. Extra flexibility has an explicit complexity cost. Uncertainty limits are not widened after seeing test errors.

## H. Register competing decision clocks

### Work

Implement opportunity schedules for:

1. Every available quote event.
2. Fixed timers with registered periods and phase conventions.
3. Completed-bar events, including the first quote after a boundary.
4. Sparse market events, such as a crossing of a registered condition.
5. Pending-order execution driven by quotes after a previous placement.

For timer discovery, a reasonable starting grid is 1, 5, 10, 30, and 60 seconds. For bar clocks, start with M1, M5, M15, and H1. These are search-design choices, not evidence about the EA. Add alternatives only through a logged protocol version.

Do not reject a bar-based signal solely because fill seconds are dispersed. Delay and pending-order placement can separate the signal clock from the fill clock.

Preserve the project's strict causal extraction rule: quote_time < decision_boundary. To represent an OnTick decision using the triggering quote, define a boundary after that quote's arrival, with deterministic sequence ordering; never use a later quote. Recorded fill timestamps are observations, not automatically decision boundaries.

### Outputs

- decision_clocks.json
- clock_opportunities.parquet or deterministic iterators
- clock_boundary_tests.json

### Gate

The same clock-generation code applies to event and non-event periods. Case timestamps are never injected into a clock to create privileged candidate opportunities.

## I. Represent eligibility without inventing account access

### Work

Separate three concepts:

- Market observation: whether suitable public quotes exist.
- Strategy availability: whether the original EA was operating, which is not directly observed.
- Policy action eligibility: whether a candidate's own state allows an action.

Use explicit scenarios:

- E0: ledger completeness and continuous operation are assumed within the declared interval, except documented market unavailability.
- E1: operation follows a small recurring schedule inferred in training.
- E2: a tightly bounded change in operating regime, tested only if residuals justify it.

E0 is an assumption, not a recovered account fact. Do not allow an arbitrary on/off switch for every missed or extra trade.

The export contains completed records. Boundary censoring matters: a candidate position still open at the end is not automatically an observed extra completed trade, but its entry is an extra entry only if the declared ledger-completeness assumption includes all entries. Register whether the observation model is a complete entry ledger or a closed-record export, model unclosed positions accordingly, and report sensitivity. Do not infer completeness solely from the absence of a row.

Position restrictions belong to the candidate policy. For autonomous replay, evaluate them from the candidate's own positions. For conditional diagnostic analysis, observed position history may be used only with that limitation prominently labelled.

Preserve documented split records and other verified overlaps. A hard single-position rule cannot simply discard them.

### Outputs

- eligibility_scenarios.json
- observed_position_intervals.parquet
- eligibility_contradictions.csv
- availability_assumptions.md

### Gate

No deterministic gate excludes an actual event without a declared observation explanation. No-event conclusions state their availability and ledger-completeness assumptions.

## J. Define historical validation before feature selection

### Work

1. Split by calendar blocks, not randomly shuffled ticks or trades.
2. Recommended initial structure: a chronologically first training segment followed by four expanding-window outer evaluation blocks, with approximately 40–60 entry epochs per block where feasible. Derive exact boundaries once from the verified chronology and seal them before candidate scoring.
3. If calendar clustering makes that design unstable, use fewer, larger blocks and record why. Do not split a grouped epoch across partitions.
4. Perform feature, grammar, nuisance, and hyperparameter selection inside each outer training segment using inner chronological folds.
5. Enforce a label-availability cutoff. A trade that has opened but has not closed cannot supply its final P&L or holding duration to training at that cutoff.
6. Purge training labels whose outcome horizons cross the evaluation boundary. Account for lookback, pending-order lifetime, holding horizon, and state memory.
7. Allow past market warm-up across a boundary; never allow future labels into that warm-up.
8. Define initialization before testing: candidate-generated burn-in, bounded initial-state scenarios, or an explicitly conditional observed-state initialization. Report these separately.

Historical reuse limits remain even after technically correct nested validation. Do not call these folds a pristine new lockbox.

### Outputs

- splits.json
- information_cutoffs.parquet
- validation_protocol.md
- fold_provenance.json

### Gate

Every transform and selected parameter identifies its training scope. All methods receive the same outer test blocks and observation scenarios.

## K. Build a causal feature registry

### Work

Start with a compact, interpretable registry. A reasonable initial window grid is 1, 5, 15, 30, 60, and 300 seconds, plus completed-bar features. Validate the grid on planted rules before expanding.

| Family | Initial candidates | Main caution |
| --- | --- | --- |
| Clock | UTC/broker hour, weekday, elapsed bar time | Clock conversion is a hypothesis |
| Price movement | Return, displacement, range, distance to prior high/low | Correct bid/ask or midpoint convention |
| Volatility | Trailing absolute returns, range, completed-bar ATR | No future bar extremes |
| Tick activity | Quote counts, interquote times, short/long activity ratios | Public provider activity is feed-specific |
| Spread | Current spread, trailing spread rank, spread change | Never synthesize unknown historical spread |
| Shape | Reversal, directional run, breakout/return inside range | Every component must be causal |
| Policy state | Time since own close, own last result, running extrema | Use candidate state in autonomous replay |

For each feature register formula, unit, time support, missingness rule, normalization, source fields, and complexity cost.

Use fixed training estimates or online past-only baselines. Never standardize using the full data period. Correlated variants count toward the search budget.

Unknown account equity, other-symbol positions, manual intervention, and native broker rejection state are not available predictors.

### Outputs

- feature_registry.json
- feature_support.parquet
- fold_specific_transformers/
- causal_feature_tests.json

### Tests and gate

Appending or altering future quotes cannot change a past feature. Chunked computation equals full-prefix computation. Missing input stays explicitly unknown. Post-entry P&L, future holding duration, ticket identifiers, and reconciliation errors cannot enter pre-entry predictors.

## L. Build opportunities and sampled controls correctly

### Work

1. Construct opportunities from coverage and the chosen clock, independently of observed labels.
2. For diagnostic conditional models, define comparable candidate times with compatible feature support and the same clock semantics.
3. Store control inclusion probabilities, matching strata, time exposure, and source coverage.
4. Match on nuisance variables only when justified. Matching on a potential trigger can remove the signal being investigated.
5. Record all dropped cases and controls with reasons. Report the coverage and time-of-day differences between retained and dropped observations.
6. Use full supported exposure for absolute-rate calibration and final replay.

For a case-control design with case density proportional to intensity lambda(t), and background density q(t), the case-versus-control log odds contains log(lambda(t)) - log(q(t)) plus a constant, under that design's assumptions. A matching or inclusion-probability correction must be derived for the actual sampler. Do not apply a generic weight without checking its likelihood.

When q(t)=0 over an interval, weighting cannot reconstruct that interval. The relationship between background sampling and point-process models is discussed by [Warton and Shepherd](https://arxiv.org/abs/1011.3319).

### Outputs

- opportunity_manifest.json
- sampled_controls.parquet
- sampling_design.json
- retained_dropped_audit.csv

### Gate

The pipeline distinguishes relative event preference from absolute event rate. A clock-only or coverage-only diagnostic cannot exploit a case/control construction artifact. Unknown feature scores never become no-action labels.

For a head-to-head candidate comparison, freeze a common supported evaluation domain from input availability before scoring. If a longer lookback or an alternative feed reduces support, report the reduced common-domain comparison and each candidate's full-domain coverage separately. Never let a candidate improve its score by dropping precisely the periods or events where its features fail.

## M. Implement and independently test the replay engine

### Work

Create one event-driven simulator used by planted policies, learned policies, and all final comparisons.

At each ordered event:

1. Advance the clock and process due execution/timer events under declared ordering.
2. Ingest only the current and earlier quotes.
3. Update market features and pending-order conditions.
4. Apply fills according to the observation scenario.
5. Update candidate positions and realized state.
6. Evaluate allowed policy decisions at the appropriate clock boundary.
7. Schedule new orders, cancellations, stops, and timers.
8. Append an auditable trace.

Specify ordering for simultaneous fills, stops, signals, and timers. If the data cannot determine ordering, evaluate a small registered set of orderings.

Market buy fills use the ask-side convention and sells the bid-side convention; closing directions reverse those sides. Pending-order triggers, stop gaps, price precision, and costs follow the declared scenario, not an assumed perfect original broker.

Public historical quotes are treated as exogenous: the candidate does not alter the market path. Record this as an approximation.

### Outputs

- replay_semantics.md
- toy_replay_fixtures/
- replay_test_report.json
- deterministic replay interface

### Required tests and gate

- Flat, long, short, overlapping positions, and split transactions.
- Buy/sell bid–ask accounting.
- Pending order placement, expiry, cancellation, and fill.
- Crossing versus first crossing and hysteresis.
- Cooldown beginning at close versus at entry.
- Trailing extrema and stop updates.
- Missing quotes without invented fills.
- Equal timestamps and bar boundaries.
- Day boundary does not reset state unless the policy says so.
- Deliberately changing an earlier candidate action changes later candidate state.
- Repeated runs and streamed chunks reproduce the same trace.

No real-rule search begins before these tests pass. Full-year speed is optimized only after correctness is established.

## N. Build an end-to-end planted-policy benchmark

### Work

Use genuine public market paths as inputs to known simulated policies. Their resulting trade records are synthetic calibration data, stored separately from every canonical table.

Include at least:

1. A clock-only policy.
2. A completed-bar threshold policy.
3. Tick breakout and first-crossing policies.
4. A reversal policy.
5. A conjunction or interaction with weak individual-feature effects.
6. Cooldown and previous-result dependence.
7. Pending-order placement followed by delayed fills.
8. A trailing/time-based exit policy.
9. A small regime-switching policy.
10. A null or stochastic policy without a recoverable deterministic trigger.
11. Two policies that are observationally equivalent under the available observation model.
12. A policy deliberately outside the declared grammar.

Use approximately 420 decision epochs, realistic clustering, and a plausible split-record mechanism; record differences from the real sample. Repeat over seeds and market periods. Avoid calibrating exclusively on the exact planted structures the search was designed to recover.

Test observation scenarios with no error, rounding/delay, missing coverage, and cross-feed disagreement. Use empirical noise estimates where defensible and clearly labelled stress scenarios otherwise. Do not claim that synthetic broker errors reveal the actual broker.

Run the whole pipeline: normalization, clocks, sampling, feature selection, search, replay, and validation. A test of only the final regression fit is insufficient.

### Measurements

- Behavior recovery on separate simulated periods.
- Structural equivalence or valid observational-equivalence recovery.
- Parameter error after converting to the same units and scale.
- False recovery claims for null, ambiguous, and out-of-family policies.
- Runtime, memory, and sensitivity to sample count.

An initial development suite can use 20 independent seeds per family. Expand the final suite based on uncertainty in the measured rates. The number is a starting engineering choice, not a guarantee of sufficient calibration.

### Outputs and gate

- benchmark_generators.json
- planted_policy_catalog/
- benchmark_results.parquet
- method_comparison.md

Noiseless in-grammar fixtures must be recovered behaviorally by the exact-search path when its declared space is fully searched. No method receives a recovery claim for the deliberately indistinguishable pair. For noisy fixtures, report measured recovery rates and intervals; there is no universal percentage that proves real-world recoverability.

## O. Fit the statistical event-model benchmarks

### Work

Fit a small hierarchy:

- B0: constant event rate over declared exposure.
- B1: recurring clock/calendar structure.
- B2: B1 plus completed-bar features.
- B3: B1 plus tick features.
- B4: B1 plus both market feature families.
- B5: limited interactions and conditional history terms.

Use shrinkage and train-only model selection. A flexible reference model may be included, but it is a benchmark, not an information ceiling or a recovered program.

For a continuous marked process with supported exposure and a declared conditional intensity:

    log L = sum_i log(lambda_mark_i(t_i | history_i))
            - integral sum_m lambda_m(t | history_t) dt

The integral accounts for no-event exposure. Unobserved action state or fill delays require the observation model; do not insert recorded fills into a signal-time likelihood as if they were observed decisions.

For a discrete clock, use the appropriate categorical likelihood over no action and available actions. If multiple executions can occur at a boundary, use a batch/multi-event representation rather than an invalid single-event Bernoulli assumption.

Report held-out log-score improvement per event:

    bits_per_event = (logL_candidate - logL_baseline) / (N_events * log(2))

Use identical supported observations and a common scoring measure. Conditional matched scores are labelled conditional; they are not interchangeable with full-exposure scores. Negative estimated improvement does not imply negative true mutual information.

### Outputs and gate

- event_model_results.parquet
- calibration_report.md
- feature_family_comparison.md
- search_priority_list.json

These models prioritize search. Weak marginal effects do not permanently remove interaction or stateful hypotheses.

## P. Define the program grammar and complexity accounting

### Work

Represent a candidate with a canonical abstract syntax tree containing:

    clock
    market inputs and lookbacks
    discrete state and bounded registers
    entry conditions
    direction rule
    size rule
    exit/order-management rules
    reset conditions
    observation-scenario reference

Useful primitives include comparison, AND/OR/NOT, bounded arithmetic, crossing, first crossing, persistence, elapsed time, running high/low since entry, and a finite state transition.

Example grammar outline, not a discovered rule:

    condition := feature < threshold
               | feature > threshold
               | condition AND condition
               | condition OR condition
               | crosses_above(feature, threshold)
               | persists(condition, duration)
               | state_is(value)
               | elapsed_since(event) >= duration

    action := no_action | open_buy(size) | open_sell(size)
            | close(position) | place_pending(parameters)
            | cancel(order) | update_stop(parameters)

Suggested initial tiers:

- T0: one market predicate, one clock, simple direction/size/exit.
- T1: up to three entry predicates, first-crossing/persistence, one timer.
- T2: up to four discrete states and two bounded registers.
- T3: limited additional order-management or regime structure, opened only under the registered expansion rule.

These bounds are engineering starting points to test in N, not claims about the true EA. Charge for each feature, lookback, state, transition, constant precision, schedule, observation parameter, and exception.

Encode parameter values at a declared resolution. Data-dependent threshold grids must be constructed within each training fold. For a memoryless threshold over a fixed training feature, only intervals between distinct training values need different training labels; that shortcut is not automatically exact for thresholds that alter state and future features.

Use dimensional typing: do not silently add prices to durations or compare lot sizes with returns.

### Outputs and gate

- grammar.json
- primitive_semantics.md
- parameter_domains.json
- code_length_spec.json
- candidate_schema.json

Every candidate can be serialized, hashed, replayed, and described in plain language. [Syntax-guided synthesis](https://www.cis.upenn.edu/~alur/SyGuS13.pdf) supplies the grammar-constrained approach; our incomplete observations do not supply its universal correctness specification.

## Q. Search directly for simple entry mechanisms

### Work

1. Enumerate clock, feature-window, and condition templates from the smallest tier.
2. Fit threshold parameters on training observations only.
3. Preserve plausible alternative clock/execution scenarios.
4. Rank candidates by the registered objective while retaining diversity in mechanism families.
5. Use conditional entry-only diagnostics for cheap screening, but clearly label their reliance on recorded history.
6. Replay surviving complete candidates, including their own eligibility state.
7. Catalogue the earliest important mismatch and other training counterexamples.
8. Refine within the allowed grammar; re-evaluate against all supported training opportunities before accepting an improvement.

Do not evaluate only convenient sampled negatives after optimizing against them. Hard-negative sampling may accelerate fitting, but final scoring returns to the full supported interval.

Use exhaustive enumeration, exact constraints, or branch-and-bound for tractable families. Pruning must use a valid lower bound if a global optimality claim is intended. Approximate top-K or beam pruning is permitted only when its heuristic status is recorded.

### Outputs and gate

- direct_search_candidates.parquet
- search_trace.jsonl
- training_counterexamples.parquet
- search_coverage.json

Report which family and parameter domain were exhausted, which were sampled, and which timed out. Do not describe a heuristic search winner as the best possible program.

## R. Search interactions and stateful mechanisms

### Work

Run two additional routes under the same folds and observation assumptions:

1. Statistical guidance: use O to prioritize promising feature combinations, without banning low-marginal-signal inputs.
2. Small-state synthesis: fit a bounded state machine with entry, exit, timers, pending status, and resets.

A useful initial transition skeleton is:

    eligible -> signal_seen -> order_pending or position_open
             -> position_closed -> cooldown -> eligible

The skeleton is a candidate template, not a finding. Compete it with simpler templates. Do not require all states.

For first-crossing and persistence rules, evaluate the full historical predicate trajectory. Checking only whether a condition is true at entry does not establish that entry was its first occurrence.

Audit whether fitted state corresponds to observable causal history. An unexplained hidden state that changes separately before each real trade is memorization.

Fit state transitions and timing/observation explanations together enough to avoid locking in an incorrect clock. Penalize hidden-state complexity and conduct sensitivity to initial state.

### Outputs and gate

- interaction_candidates.parquet
- stateful_candidates.parquet
- transition_explanations.md
- state_complexity_report.md

Additional states must improve internally held-out replay and planted recovery sufficiently to justify their complexity. Similar system representations are studied in [hybrid automata learning](https://arxiv.org/abs/2301.03915); this project observes fewer internal variables and therefore requires stronger limits on flexibility.

## S. Reconstruct direction and sizing

### Work: direction

Compare simple rules such as movement continuation, reversal, alternating direction, state-dependent direction, and an explicitly probabilistic mark model.

Report direction performance both conditional on correctly matched entries and end-to-end over all observed epochs. Correct direction on a small easy subset must not masquerade as full reconstruction.

### Work: size

Start with constant size, a small discrete size table, and limited dependence on the candidate's past trades or position state.

Recheck the distribution from the ledger before evaluating. The prevailing small lot size is a mandatory baseline: rare larger sizes require their own error counts.

Do not call cumulative closed-trade P&L account equity. Any size formula involving unknown initial balance, deposits, floating P&L, or other positions is unverified. Prefer reporting a conditional sizing relationship or equivalence class over inventing these quantities.

Preserve 423-record sizes and split patterns even when entry timing is evaluated at 420 epochs.

### Outputs and gate

- direction_rules.json
- sizing_rules.json
- mark_metrics.parquet
- sizing_identifiability.md

All state-dependent inputs are computable in autonomous replay. Report rare-size errors, not just aggregate accuracy.

## T. Reconstruct exits and order management

### Work

Compare a bounded set of plausible mechanisms:

- Fixed price-distance take profit or stop.
- Fixed or volatility-scaled holding rules.
- Trailing stop.
- Break-even adjustment.
- Exit on opposite condition.
- Session/time exit.
- A limited combination of these.

For each candidate, process quotes sequentially after entry and find the first legal trigger. Do not calculate the trade's eventual maximum favorable excursion and use that future value as a decision input.

Use recorded close times as targets. Use P&L jointly with entry-price interpretation, multiplier, cost, and feed uncertainty. Do not derive an exit price from P&L and then count agreement with that same P&L as a second independent success.

Diagnostic exit fitting may start from recorded entry time/price. Final testing uses the candidate's own entry, size, path, and exit.

A missing quote interval makes barrier ordering uncertain. Branch over bounded possibilities or mark the affected outcome unevaluable; never force the sequence that best matches the ledger.

### Outputs and gate

- exit_rule_candidates.parquet
- exit_trigger_traces/
- pnl_observation_checks.parquet
- exit_uncertainty_report.md

The candidate produces exits causally and supports the next entry decision through its own resulting state. Exit price accuracy is claimed only to the extent that an independent observed target exists.

## U. Assemble and jointly fit complete policies

### Work

Combine entry, direction, size, and exit modules using a declared search budget. Avoid selecting individually best modules and assuming their combination will be best.

For each full candidate:

1. Replay the complete supported training history.
2. Propagate its own state after every decision and fill.
3. Score the entire recorded sequence through the observation model.
4. Count all extra and missing executions.
5. Refine parameters jointly within training.
6. Retain non-dominated candidates with materially different mechanisms.

A coherent MDL-style objective is:

    J(policy) = -log2 P(observed ledger | public market path, policy)
                + code_length(policy)

The observation probability must include the declared rounding, execution, missingness, and nuisance model. Additional fitted nuisance parameters also require coding/regularization or marginalization under declared priors. A convenient sum of weighted errors is a valid engineering loss, but must be labelled a loss, not a likelihood.

For nuisance uncertainty, either:

- Integrate over registered distributions and report prior sensitivity, or
- Score a finite set of declared scenarios and report their full performance range.

Do not choose each trade's best scenario independently.

For cross-clock likelihood comparisons, use a common observation representation, such as probability mass over the recorded timestamp bins and marks. Raw per-tick and per-minute likelihoods have different observation units and cannot be compared naively.

### Outputs and gate

- complete_candidate_registry.parquet
- candidate_artifacts/<candidate_id>/
- joint_fit_report.md
- likelihood_validation_tests.json

The scoring implementation is checked against toy cases with known probabilities. All candidate-generated history is distinct from recorded history. [MDL](https://arxiv.org/abs/math/0406077) motivates explicit complexity accounting; [proper scoring rules](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf) motivate honest probability evaluation.

## V. Evaluate autonomous replay with fixed event matching

### Work

Seal a candidate before each outer historical test. Run it without using test trades to repair its state or select its parameters.

Define one-to-one matching before evaluation:

1. A predicted fill and observed epoch are compatible only under the frozen timing window and observation conventions.
2. Solve a maximum-cardinality one-to-one match, with fixed minimum timing-error cost as a secondary criterion.
3. Use stable tie-breaking independent of later P&L.
4. Report timing-only matching followed by mark errors, plus a separate joint entry-and-direction match. Do not let the choice hide wrong-side trades.
5. Score transaction-level multiplicity and volume against all 423 records.
6. Match closes through the matched positions; do not independently pair each convenient predicted exit to any observed exit.

For supported entry epochs:

    TP = matched observed epochs
    FN = supported observed epochs not matched
    FP = predicted entries not matched
    precision = TP / (TP + FP)
    recall = TP / (TP + FN)
    F1 = 2 * precision * recall / (precision + recall)
    false_entry_rate = FP / covered_operational_hours

Always report unevaluable epochs separately and also TP/420 as whole-ledger coverage-adjusted recovery. Do not label TP/420 ordinary conditional recall when coverage is incomplete.

The exposure denominator is fixed for the declared comparison and availability scenario. A candidate's learned session, cooldown, or position gate changes its actions; it cannot remove its inconvenient observed events from the evaluator or silently shrink the reporting domain. Compare different availability assumptions as separate scenario results.

Include median and tail timing error, count error by period, direction errors, volume errors, exit-time errors, P&L residuals, and uncertainty intervals. With sparse observations, emphasize counts and intervals over fine decimal precision.

### Outputs and gate

- historical_outer_predictions.parquet
- event_matches.parquet
- false_entries.parquet
- missed_entries.parquet
- full_metrics.json
- autonomous_vs_conditional_report.md

No observed state is silently injected during the test. Unknown intervals are neither wins nor losses in the supported-scope score, and their exclusion is prominently quantified.

## W. Test calibration, robustness, and data-snooping sensitivity

### Work

1. Compare paired per-block performance across methods on identical supported observations.
2. Use a suitable block resampling design for temporal dependence. Do not treat millions of quote rows as millions of independent examples of the 420-event policy.
3. Evaluate clock, feed, matching-window, initial-state, and execution-scenario sensitivity without retuning on the test block.
4. Run registered placebo mechanisms, such as conditional null event generation or whole-episode/day rearrangements that preserve appropriate duration and calendar structure. Simple independent shuffling of ticks is generally not an adequate null.
5. Repeat the entire search procedure under each null replicate when calibrating a search-adjusted discovery statistic, including feature selection and candidate choice.
6. Separate conditional permutation assumptions from conclusions. If a resampling mechanism is not justified, call it a stress test, not an exact p-value.
7. For calibrated continuous event models, inspect time-rescaled gaps and serial dependence. For discrete clocks, use an appropriate discrete correction or simulation-based reference.

Parameter fitting and model selection affect goodness-of-fit reference distributions. Calibrate through appropriate held-out or fitted-model simulation procedures rather than automatically using textbook KS cutoffs. Use the candidate's declared operation and censoring semantics; do not integrate across unknown exposure as if it were observed.

[Continuous time rescaling](https://www.stat.cmu.edu/~vventura/rescaling.pdf) and [discrete-time corrections](https://pmc.ncbi.nlm.nih.gov/articles/PMC2932849/) support these diagnostics. [White's data-snooping analysis](https://bashtage.github.io/kevinsheppard.com/files/teaching/mfe/advanced-econometrics/White.pdf) motivates accounting for the search, not merely testing its winner.

### Outputs and gate

- robustness_matrix.parquet
- placebo_search_results.parquet
- calibration_report.md
- uncertainty_report.md
- multiple_search_accounting.json

Passing tests means failure to detect specified discrepancies at available power. It is not proof of identity. Reanalysis cannot erase earlier analyst exposure to this same history.

## X. Diagnose residual errors and expand only for a stated reason

### Work

For every important mismatch, save:

- The relevant market prefix and source references.
- Candidate state before the error.
- Features and thresholds used.
- The action emitted and the observed outcome.
- Coverage and observation uncertainty.
- Whether it is the first divergence or a downstream consequence.

Classify residuals into feature/clock mismatch, state divergence, execution ambiguity, unsupported coverage, mark/exit mismatch, or unresolved discrepancy.

Expand the grammar only when a recurring training/inner-validation error pattern motivates a bounded addition and the planted benchmark supports its recoverability. Possible additions include a new lookback family, a pending-order primitive, or a small reset rule.

Do not use outer-test residuals to tune a candidate and then continue reporting that outer test as untouched. Such a revision starts a new exploratory protocol version; old test results become development evidence.

Compare the added complexity against the improvement. A change point or extra hidden state is not proof that the original EA changed.

### Outputs and gate

- residual_casebook.md
- hypothesis_revision_log.jsonl
- grammar_expansion_decisions.json

Every new component has a causal rationale, a bounded domain, and a declared validation status. No post-hoc exception list is allowed.

## Y. Determine identifiability and stop at the supported claim

### Work

Group surviving policies by observable behavior within the declared uncertainty model. Report which parameters have tight ranges, which are interchangeable, and which depend strongly on assumptions.

Where practical, search for a distinguishing history or market segment on which two candidates disagree. Public data without original-account actions can expose candidate disagreement or instability, but cannot identify which candidate matches the unavailable original policy.

Apply these verdicts:

| Verdict | Required evidence |
| --- | --- |
| Exact finite-history compatibility | All supported observed records reproduced, no unsupported extra fills, under explicitly fixed tolerances/scenario; scope and missing periods stated |
| Supported behavioral reconstruction | Compact policy with credible internal-validation performance and documented remaining errors |
| Observational equivalence class | Multiple candidates survive and cannot be separated by available evidence |
| Conditional reconstruction | Result depends materially on an operating, execution, or initialization assumption |
| Tested-family failure | No candidate meets the registered criteria in the searched family |
| Insufficient observation | Coverage or hidden inputs prevent the intended discrimination |

Exact finite-history compatibility is stronger than a high AUC, but weaker than identifying original source code or proving future accuracy.

For a fixed finite family and fixed scoring specification, a certified exhaustive search can establish that no family member has a lower objective. State the family, assumptions, parameter resolution, and optimality gap. Do not generalize that certificate to all possible algorithms.

### Outputs and gate

- identifiable_parameters.csv
- surviving_equivalence_classes.json
- final_verdict.md
- search_optimality_certificate.json, if actually established

No candidate is called unique unless alternatives were excluded within a precisely stated family. General inverse-learning non-identifiability is illustrated by [Cao, Cohen, and Szpruch](https://arxiv.org/abs/2106.03498).

## Z. Package the reconstruction for reproduction and handoff

### Work

1. Export the selected policy or surviving candidates in a canonical machine-readable format.
2. Export readable executable reference code using the same primitives as replay.
3. Give a plain-language explanation of each condition, state update, and exit.
4. Include parameter ranges, source hashes, software versions, exact configuration, and candidate lineage.
5. Supply a trade-by-trade reconciliation and complete false-entry/missed-entry catalog.
6. Include a one-command reproduction entry point only after it actually exists and has been tested.
7. Regenerate the repository manifest when implementation artifacts are incorporated, without rewriting historical result files.
8. If a later MQL5 translation is requested, test it against the reference replay on identical quotes. No account login or live trading is required for the research result.

### Required final package

- README_RESULT.md
- policy.json, or candidate_set.json
- policy_reference.py
- parameter_uncertainty.csv
- evidence_manifest.json
- frozen_config.json
- event_matches.parquet
- false_entries.parquet
- missed_entries.parquet
- transaction_comparison.parquet
- validation_report.md
- robustness_report.md
- identifiability_report.md
- reproduction_instructions.md

### Final gate

A clean rerun reproduces the stated outputs from the frozen evidence and configuration. The result explains its assumptions and limitations. It contains no claim that the original broker, source code, account state, or future profitability was recovered without supporting evidence.

## Appendix 1. Proposed project structure and module responsibilities

This is a target layout, not a list of files already implemented. Keep the existing package and reports intact.

    E:/reverse -traid/
      docs/
        ALGORITHM_RECONSTRUCTION_IMPLEMENTATION_PLAN_V1.md
      configs/reconstruction_v1/
        protocol.json
        observation_scenarios.json
        grammar.json
        validation.json
      src/reverse_trade/reconstruction/
        evidence.py
        coverage.py
        acquisition.py
        normalization.py
        clocks.py
        observation.py
        features.py
        opportunities.py
        policy_ast.py
        replay.py
        matching.py
        scoring.py
        benchmarks.py
        event_models.py
        synthesis.py
        state_search.py
        validation.py
        identifiability.py
        reporting.py
        cli.py
      tests/reconstruction/
        fixtures/
        test_evidence.py
        test_coverage.py
        test_causality.py
        test_clocks.py
        test_replay.py
        test_matching.py
        test_scoring.py
        test_planted_recovery.py
        test_validation_isolation.py
      data/market/
        raw_ticks/                       existing locked archive
        supplemental_raw_ticks/          new genuine raw responses
        reconstruction_normalized/       versioned derived partitions
      data/synthetic/reconstruction_v1/   calibration data only
      outputs/reconstruction_v1/<run_id>/
        evidence/
        coverage/
        splits/
        benchmarks/
        candidates/
        validation/
        certificates/
        reports/

Responsibilities:

| Module group | Responsibility | Must not do |
| --- | --- | --- |
| Evidence/coverage | Provenance, schema, support masks | Alter raw records to make a rule fit |
| Acquisition/normalization | Public downloads and deterministic derived views | Silently fill missing ticks |
| Clocks/features/opportunities | Causal input and opportunity generation | Special-case known entry times |
| Observation/replay | Orders, fills, timestamps, candidate state | Repair state from later ledger rows |
| Policy/synthesis/state search | Enumerate and optimize allowed programs | Access outer test labels |
| Matching/scoring | Fixed comparisons and error decomposition | Widen tolerances after seeing errors |
| Validation/identifiability | Method assessment and competing explanations | Turn internal validation into fresh evidence |
| Reporting | Explain actual artifacts and supported conclusions | Invent results for unfinished stages |

Reuse existing code only after its relevant behavior has unit tests. The existence of an older implementation is not a correctness certificate. Dependencies and optional solvers should be pinned and recorded during implementation; install nothing merely to write this plan.

## Appendix 2. Minimum data contracts

Use typed tables and schema versions. Parquet is suggested for large tables; JSON is suitable for configurations and small manifests. UTC time is integer-valued with documented resolution; quantities carry units.

### Record

    record_id, source_row, ticket, side, symbol, volume,
    raw_open_time, raw_close_time, open_utc, close_utc,
    recorded_price, recorded_pnl, clock_view_id,
    source_hash, semantic_status

### Epoch

    epoch_id, anchor_record_id, member_record_ids,
    canonical_anchor_time, side, aggregate_volume,
    grouping_rule_id, source_hash

The canonical anchor is not automatically the true signal time.

### Quote

    provider_id, instrument_id, timestamp_utc, timestamp_resolution,
    sequence_id, bid, ask, optional_documented_volume,
    source_file_hash, source_row, quality_flags

### Coverage interval

    provider_id, start_utc, end_utc, acquisition_status,
    quote_count, largest_gap, market_status,
    source_hashes, support_flags, uncertainty_reason

### Feature definition/value

    feature_id, formula_version, unit, window, source_fields,
    available_at, decision_boundary, value,
    coverage_status, transformer_id, maximum_input_time

### Candidate

    candidate_id, parent_id, grammar_version, clock_id,
    canonical_ast, parameters, parameter_units,
    observation_scenario_id, training_fold_id,
    complexity_code_length, search_method,
    training_score, inner_validation_score,
    source_hashes, config_hash, code_version

### Replay event

    run_id, candidate_id, event_index, event_time,
    event_type, quote_reference, prior_state_hash,
    feature_references, condition_values, emitted_action,
    order_id, position_id, fill_details, resulting_state_hash

### Match/error

    fold_id, candidate_id, observed_epoch_id, predicted_entry_id,
    observed_record_ids, match_status, timing_error,
    side_error, volume_error, close_time_error, pnl_error,
    support_status, observation_scenario_id,
    first_divergence_reference

Unknown is a distinct status, never an implicit zero, negative class, or successful match.

## Appendix 3. Freeze the scoring and candidate-selection contract

### Primary reconstruction reporting

Report a vector, not a single flattering number:

    covered epoch count / 420
    entry TP, FP, FN
    precision, recall, F1
    TP / 420
    false entries per covered hour
    timing error distribution
    joint entry-and-direction recall
    transaction multiplicity and size errors
    exit-time error distribution
    P&L residual distribution
    code length and assumption sensitivity

The evaluator must export all underlying counts. Aggregate minute accuracy and profitability are not primary reconstruction criteria.

### Default selection procedure

Before the real search, choose one complete-policy fit objective:

1. A validated observation likelihood plus code length, if the likelihood implementation passes toy normalization/probability checks; or
2. A declared engineering loss based on one-to-one event and mark mismatches if a reliable likelihood is not yet available.

For the engineering fallback, the initial entry loss is (FP + FN) / N_supported_epochs. Keep direction, size, and exit losses as separately registered objectives and retain the non-dominated candidate set. Use shorter code to prefer otherwise comparable candidates. Do not quietly label this a full marked likelihood or MDL code.

The benchmark in N selects and seals the objective profile before searching the real data. An objective change afterwards is a new protocol version.

Within each outer fold:

- Select the method, model complexity, parameters, and observation treatment using only its training/inner folds and the declared benchmark-informed procedure.
- Evaluate the resulting frozen policy on the outer block.
- Pool paired outer predictions and report period variation.
- Do not select an overall winner on outer scores and then report that same score as an unbiased estimate of the winner's future accuracy.

After the methodological evaluation, a final policy may be fitted on all available history using the frozen procedure. Its full-history fit is descriptive. Its evidence for generalization comes from the earlier evaluation, with the historical-reuse limitation stated.

### Acceptance rules

There is no scientific justification for promising 90%, 95%, or 100% reconstruction before these experiments. Therefore:

- Exact finite-history compatibility requires no unmatched supported entries, no unexplained extra fills, and compatible recorded marks under the declared observation model. A complete-ledger claim additionally requires support for all 423 records and all relevant intervening opportunities.
- An approximate reconstruction reports its measured accuracy and uncertainty. Before calling it practically sufficient, register the acceptable missed/extra entry counts and mark/exit tolerances; do not pick those limits after seeing a candidate.
- The default project objective remains to reduce errors across the supported interval while controlling complexity and validation degradation, not to stop automatically upon reaching an arbitrary headline percentage.
- If several candidates trade off errors and complexity, report the frontier rather than hiding it behind newly chosen weights.
- No claim of source-code identity follows from any of these outcomes.

This is a fully specified evaluation workflow even when the eventual attainable accuracy is unknown.

## Appendix 4. Required test matrix

| Test | Deliberate setup | Required result |
| --- | --- | --- |
| Canonical preservation | Re-ingest locked files | Counts, field values, and hashes unchanged |
| Future leakage | Change all quotes after time t | Features and decisions before t unchanged |
| Label leakage | Change test trade labels | Training artifacts unchanged |
| Missing control | Remove an input hour | Affected opportunities unknown, not true negatives |
| Missing event | Remove input support for a real entry | Event listed as unevaluable, never silently dropped |
| Case privilege | Generate opportunities with labels unavailable | Same base opportunities as labelled run |
| Clock precision | Rounded fills near a bar boundary | Candidate evaluated under declared rounding/order semantics |
| Duplicate quote time | Two different quotes at one timestamp | Stable documented ordering or explicit ambiguity |
| Buy/sell symmetry | Mirror a toy price path and side | Bid/ask accounting and sign transform consistently |
| Pending order | Place before trigger, fill later | Placement clock and fill time remain distinct |
| First crossing | Condition stays true for many ticks | One trigger if the rule specifies first crossing |
| Hysteresis | Oscillate around threshold | Reset/rearm behavior matches specification |
| Cooldown | Close at t, cross again before expiry | Entry blocked only for the specified duration |
| Own-state replay | Force candidate to miss first entry | Later state follows the candidate, not the ledger |
| Missing interval state | Position spans a quote gap | No invented stop/fill; uncertainty persists appropriately |
| One-to-one matching | Many predicted entries near one real entry | At most one match; remaining predictions are FP |
| Split records | Use the three fixed split pairs | 420 timing epochs and 423 transaction targets preserved |
| P&L circularity | Derive exit from P&L | Derived exit not counted as independent validation |
| Parameter scaling | Standardize a planted feature | Compare coefficients after correct unit conversion |
| In-grammar planted rule | Search a fully enumerated noiseless family | Recover an equivalent executable policy |
| Interaction rule | Plant XOR-like dependence | Individual-feature screening does not eliminate the solution |
| Null policy | No recoverable trigger | False recovery claims measured and controlled |
| Ambiguous pair | Two policies yield same observable ledger | Return ambiguity, not false uniqueness |
| Out-of-grammar policy | True structure excluded | Report family limitation instead of exact recovery |
| Search multiplicity | Repeat full search on null data | Null score reflects the whole search |
| Chunk equivalence | Replay in chunks and in one pass | Identical state/event trace |
| Restart/resume | Resume a checkpoint mid-position | Identical subsequent trace |
| Reproducibility | Same code, inputs, seeds, configuration | Identical deterministic outputs |

Do not interpret the previous repository's recorded test count as evidence that these new tests already exist or pass.

## Appendix 5. Execution order and milestone checklist

### Milestone 1: evidence readiness — A, B, C

Deliver the frozen evidence manifest, schema/semantics dictionary, old-claim audit, and research protocol.

Decision: are the source records valid and correctly linked? Resolve mismatches before dependent modelling.

### Milestone 2: public market support — D, E, F

Deliver coverage maps, missing-hour acquisition results, and normalized source-indexed quotes.

Decision: full-scope research or explicitly partial-scope research? Keep this distinction in every later report.

### Milestone 3: experiment definition — G, H, I, J, K, L

Deliver observation/clock/availability scenarios, sealed folds, feature registry, and auditable opportunities.

Decision: can each proposed measurement be made without future information or unsupported assumptions?

### Milestone 4: simulator and search prototypes — M, N first pass, O–U prototypes

Implement the interpreter, matching/scoring, planted generators, and the three search routes using toy/synthetic cases. Establish the minimal policy AST before connecting the simulator and solvers.

Decision: do semantics and causal-isolation tests pass?

### Milestone 5: recovery calibration — N completion

Run the end-to-end planted benchmark. Compare direct, guided, and stateful search. Freeze practical grammar tiers, parameter grids, score profile, candidate budgets, and expansion rules.

Decision: which methods recover which kinds of policy under which observation conditions? Repair failed methods before using them as evidence on the real ledger.

### Milestone 6: real reconstruction — O, P, Q, R, S, T, U

Run the sealed search procedure inside historical folds. Keep complete candidate traces and counterexamples. Search smallest adequate rules first, while preserving bounded interaction/state routes.

Decision: which policies survive autonomous inner-validation replay?

### Milestone 7: historical evaluation — V, W

Produce frozen outer predictions, matched transactions, false/missed-entry catalogs, uncertainty, and sensitivity tests.

Decision: does a candidate explain behavior beyond its fitting period, under the declared internal-validation limitation?

### Milestone 8: controlled refinement or final verdict — X, Y

Expand only under the registered protocol. Track any reuse of evaluation results. Identify surviving parameter ranges and equivalent explanations.

Decision: accept a qualified reconstruction, retain an equivalence class, or report family/observation failure.

### Milestone 9: final package — Z

Provide executable reference policy, detailed reconciliation, evidence manifest, reproduction instructions, and the honest verdict.

Decision: can a clean rerun reproduce every reported result?

## Appendix 6. Runner interface to implement later

The commands below are interface specifications only. The reconstruction CLI is not implemented by this document. Do not paste these commands into the current project expecting them to work.

Proposed common interface:

    python -m reverse_trade.reconstruction.cli <command>
        --config configs/reconstruction_v1/protocol.json
        --run-id <unique_run_id>

Proposed commands:

| Command | Purpose | Main prerequisite |
| --- | --- | --- |
| audit | A–D evidence and coverage inventory | Existing canonical files |
| acquire | E resumable public downloads | Approved public source and acquisition plan |
| normalize | F normalized quote partitions | Raw-source manifests |
| prepare | G–L scenarios, folds, features, opportunities | Valid support and protocol |
| selftest | M deterministic infrastructure fixtures | Implemented components |
| benchmark | N end-to-end synthetic recovery | Toy-tested search components |
| search | O–U real-data reconstruction | Sealed benchmark-informed protocol |
| evaluate | V–W frozen historical evaluation | Sealed candidates |
| diagnose | X mismatch reports | Existing predictions and matches |
| certify | Y scope and identifiability assessment | Search/evaluation artifacts |
| export | Z reconstruction package | Recorded final verdict |

Required runner behavior:

- Fail closed on canonical hash mismatch or invalid configuration.
- Support dry-run planning for acquisition and large computations.
- Never automatically send orders or authenticate to the unavailable account.
- Keep run configurations immutable; changes create a new run/protocol version.
- Save seeds, library versions, code hashes, elapsed time, and memory estimates.
- Resume checkpoints without restarting candidate state.
- Keep training, inner-validation, and outer-evaluation outputs distinct.
- Refuse to overwrite a sealed evaluation with a retuned model.
- Produce a stage status and next eligible stage, including partial-scope status.

## Appendix 7. Computation and stopping policy

### Keep the work efficient without weakening validation

1. Normalize and index each raw file once per parser version.
2. Compute reusable market features in chronological chunks.
3. Carry rolling indicator, position, pending-order, and timer state across chunks.
4. Use sparse event representations and cached causal features; do not materialize every possible feature/window/clock combination at once.
5. Use sampled opportunities for supported screening only. Final candidates receive full supported replay.
6. Cache identical canonical programs and shared feature expressions.
7. Retain structurally distinct candidate families, not only many near-duplicate thresholds.
8. Measure pilot runtime/memory and estimate the full run before starting it.
9. Set per-tier candidate/solver budgets in configuration. A timeout is reported as incomplete search, not family rejection.
10. Separate independent experiments when resources permit, while preserving immutable shared inputs and fold isolation.

### Stop or change course for the right reason

- Data corruption: stop dependent stages and resolve provenance.
- Missing public history: continue supported analyses, but prohibit unsupported full-scope claims.
- Simulator or leakage-test failure: repair implementation before modelling.
- Planted recovery failure: improve the method or narrow its declared capability.
- More complex rules improve training only: retain the simpler validated explanation and record overfit.
- Irreducible feed/clock sensitivity: report conditional reconstruction or ambiguity.
- Exhausted registered search with no acceptable rule: report tested-family failure and the exact search scope.
- Several equally supported policies: return their equivalence class.
- Success under the registered target: package the result; do not silently broaden the claim to source-code identity or future profitability.

The absence of the old account is never a request to wait indefinitely. It is a permanent constraint already built into the experiment.

## Appendix 8. Mathematical limits and what a proof would actually establish

### Why more public market data can help

Suppose two candidate rules agree near the recorded entries but disagree during an uncovered historical hour. Obtaining genuine quotes for that hour can distinguish their implied trading behavior, conditional on the operation/completeness assumption. That adds relevant input evidence without requiring new account access.

The benefit is not automatic: if operation during that hour is unknown, or both rules remain compatible after observation uncertainty, ambiguity may remain.

### Why a high in-sample fit cannot prove the original algorithm

Let two programs agree on every history represented in the observations, including supported non-entry periods, but differ on one unobserved history. Under the same observation model, they produce the same available evidence. A procedure receiving only that evidence cannot tell which one was used.

Restricting the allowed program family can make identification possible within that family. It cannot prove that the family contains the original program.

### What an optimality certificate can say

For a fixed finite family H, fixed observation assumptions, and a fixed objective J:

    candidate_hat = argmin over candidate in H of J(candidate)

A complete certified search can prove that no member of H has a smaller J. It cannot prove maximum future accuracy over all possible algorithms. If the search is heuristic or truncated, report the best-found candidate and any valid bound, not a nonexistent certificate.

### What this means for the project

The attainable result may be a simple, accurate executable reconstruction. It may instead be several observationally equivalent rules or a clear account of which behaviors cannot be determined. The plan is designed to distinguish those outcomes, rather than assume success or failure from the count of 423 trades alone.

## Appendix 9. Research basis and how it is used

These sources inform the approach. None is claimed to have solved this exact 423-trade XAUUSD reconstruction problem.

1. [Warton and Shepherd, point-process modelling and background sampling](https://arxiv.org/abs/1011.3319): motivates exposure-aware event modelling and scrutiny of control selection.
2. [Brown and colleagues, time-rescaling](https://www.stat.cmu.edu/~vventura/rescaling.pdf): supports absolute event-model diagnostics when the required model and exposure assumptions hold.
3. [Haslinger, Pipa, and Brown, discrete-time corrections](https://pmc.ncbi.nlm.nih.gov/articles/PMC2932849/): prevents misuse of continuous residual tests on discretized clocks.
4. [Alur and colleagues, syntax-guided synthesis](https://www.cis.upenn.edu/~alur/SyGuS13.pdf): supports a grammar of executable candidate programs and counterexample-guided search.
5. [Grünwald, minimum description length](https://arxiv.org/abs/math/0406077): motivates explicit accounting for program and parameter complexity.
6. [Ross, Gordon, and Bagnell, sequential imitation learning](https://proceedings.mlr.press/v15/ross11a.html): motivates evaluation under the candidate's own induced state. Their expert-query mechanism is not available here.
7. [Gurung, Waga, and Suenaga, hybrid automata learning](https://arxiv.org/abs/2301.03915): informs state, transition, and reset representations, with important differences in observability.
8. [Mahfouz and colleagues, imitation of simulated trading agents](https://arxiv.org/abs/2110.01325): supports benchmarking on known agent families rather than assuming that a predictive model recovers a program.
9. [Gneiting and Raftery, proper scoring rules](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf): informs probability scoring and calibration.
10. [White, data-snooping assessment](https://bashtage.github.io/kevinsheppard.com/files/teaching/mfe/advanced-econometrics/White.pdf): informs search-adjusted comparison and the need to account for model selection.
11. [Cao, Cohen, and Szpruch, inverse-learning identifiability](https://arxiv.org/abs/2106.03498): illustrates why observed behavior need not uniquely determine the hidden mechanism.

## Start-here checklist

- [ ] Implement A–C first: evidence manifest, field dictionary, prior-claim audit, and protocol.
- [ ] Produce the real coverage map before adding another strategy model.
- [ ] Acquire supported missing public tick history without changing the canonical archive.
- [ ] Seal clocks, uncertainty scenarios, folds, features, and scoring semantics.
- [ ] Build and test the replay engine and matching rules.
- [ ] Demonstrate end-to-end recovery on planted policies and rejection/ambiguity on controls.
- [ ] Run the three search routes under the same evidence and validation contract.
- [ ] Jointly replay entry, direction, size, and exit using candidate-generated history.
- [ ] Evaluate all supported opportunities, not only moments around known trades.
- [ ] Deliver the executable reconstruction or an explicit equivalence/failure verdict.
