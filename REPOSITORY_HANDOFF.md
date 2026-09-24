# XAUUSD Forensic Reconstruction — Repository Handoff

**Repository target:** `shreyash1234566/xauusd-forensic-reconstruction`  
**Project root:** `E:\reverse -traid`  
**Handoff status:** authoritative source package prepared locally; GitHub publication requires an authenticated GitHub client and a repository with the target name.

## 1. Purpose and evidence boundary

This repository contains a reproducible forensic reverse-engineering project for a supplied XAUUSD trading ledger. The analysis reconstructs observable market context, execution timing, market-feed alignment, conditional entry-selection evidence, and identifiability limits from physically existing files.

The repository **does not claim** to recover proprietary source code, a unique hidden strategy, or an exact broker decision rule from selected closed trades alone. Every conclusion must be read with the evidence grade and limitations in the corresponding report.

The canonical source ledger is the headerless file `data/raw/trades_raw.tsv`. It contains **423 reconciled trade records**. Phase 10/11 and the complete-ledger Phase 12 audit additionally define **420 unique decision epochs** after collapsing exactly three verified split-order pairs; they do not replace the 423-record ledger.

## 2. Authoritative analytical scope

The authoritative repository scope is limited to the analytical phases and artifacts that exist in this workspace:

1. Baseline behavioral fingerprint and evidence hierarchy.
2. Phase 2 — market/trade event panel and opportunity reconstruction.
3. Phase 3 — intrabar state, clock, direction, and sequence analyses.
4. Phase 4 — order/deal lifecycle and microstructure recovery.
5. Phase 5 — observable state space, feature ablation, negative space, and information-boundary analysis.
6. Phase 6 — native environment inventory, journal, hidden-state, sizing, and recovery analysis.
7. Phase 6b — native artifact ingestion and forensic schema/data-quality validation.
8. Phase 6c — public-source, multidimensional search, and intellectual-property verification.
9. Phase 7 — market-feed identification and structural comparison.
10. Phase 7b — tick-level feed reconciliation and depth/microstructure comparison.
11. Phase 7c — real raw-tick validation and canonical source lock using 7.1M+ ticks.
12. Phase 8b — modular strategy falsification, counterfactual controls, exit/sizing/direction decomposition, and walk-forward checks.
13. Phase 8c — adversarial reconstruction, counterfactual replay, and parameter-identifiability audit.
14. Phase 8d — hidden-trigger, latent-state, point-process intensity, and execution-provenance reconstruction.
15. Phase 8e — leakage audit, flat-state signal recovery, orthogonal two-model reconstruction, and MQL5 EA generation artifacts.
16. Base pipeline — the `src/reverse_trade` package, tests, and original baseline reports.

### Experimental extensions

Phase 10/11 and Phase 12 are retained as **research extensions evaluated in local runs**, not as proof that the source strategy has been uniquely identified. They are included because their files physically exist and because they document a discovery-frozen epoch-level model, lockbox analysis, and a complete-ledger identity audit.

Earlier or later experimental work that is not represented by physical files in this workspace is not claimed by this repository. No synthetic files, fabricated reports, or reconstructed outputs have been added to make a phase appear complete.

## 3. Canonical data and provenance

### 3.1 Trade ledger

- `data/raw/trades_raw.tsv` — canonical headerless supplied ledger.
- `outputs/market_reconstruction/phase7c_trade_reconciliation.csv` — reconciled trade ledger used by the later epoch/audit code.
- Original record count: **423**.
- Canonical epoch count: **420**.

### 3.2 Decision-epoch rule

Only these three predefined same-direction overlapping ticket pairs are collapsed:

- `36168589` / `36168590` — Buy
- `36227385` / `36227388` — Sell
- `36335183` / `36335196` — Buy

Each pair is represented by the earliest recorded UTC open. All other records remain single-record epochs. The partition is record-level first, then mapped to epochs:

- discovery records `0:320` → 317 epochs,
- one-record buffer `320:321` → 1 epoch,
- lockbox records `321:423` → 102 epochs.

The complete-ledger identity audit uses `U = E ∪ F`:

- `N_E = 420` observed entry epochs,
- `N_F = 205,646` exhaustive eligible flat non-entry minutes,
- `N_U = 206,066` total points,
- `E ∩ F = 0`.

### 3.3 Market data

The repository retains normalized/raw market files and processed panel artifacts needed by the included reports. The full raw tick archive is intentionally excluded from the Git working tree because it is oversized; its expected source location is `data/market/raw_ticks/` and the original archive is documented in the local manifest/audit notes.

## 4. Key authoritative files

### Core package and tests

- `src/reverse_trade/` — baseline ingestion, market, modeling, statistics, pipeline, and report package.
- `tests/` — baseline and phase-specific regression tests. Current local result: **44 passed**.
- `pyproject.toml`, `requirements.txt`, `package.json` — project metadata and runtime dependencies.

### Reconciliation and market reconstruction

- `scripts/clockfix10.py` — trade ingestion and decision-epoch construction helpers.
- `scripts/run_phase7_market_identification.py` — Phase 7 market identification pipeline.
- `scripts/run_phase7b_tick_reconciliation.py` — Phase 7b tick/feed reconciliation.
- `scripts/run_phase7c_raw_tick_validation.py` — Phase 7c raw-tick validation.
- `outputs/market_reconstruction/phase7c_report.md` — Phase 7c report.
- `outputs/market_reconstruction/phase7c_canonical_source_lock.md` — canonical-source lock.

### Strategy reconstruction

- `scripts/phase8b_*.py` — modular Phase 8b analyses.
- `scripts/phase8c_*.py` — adversarial Phase 8c analyses.
- `scripts/phase8d_*.py` — provenance/latent-state Phase 8d analyses.
- `scripts/phase8e_*.py` — leakage/reconstruction Phase 8e analyses.
- `outputs/strategy_reconstruction/phase8b_intermediate_report.md`.
- `outputs/strategy_reconstruction/phase8c_identifiability_report.md`.
- `outputs/strategy_reconstruction/phase8d_identifiability_report.md`.
- `outputs/strategy_reconstruction/phase8e_leakage_audit.md`.

### Phase 10/11 and Phase 12 extension

- `scripts/phase10_11_main.py` — epoch-level discovery/freeze and final lockbox pipeline.
- `scripts/phase10_11_lockbox_standalone.py` — standalone final evaluation path.
- `scripts/model_lib10b.py` — conditional-logit/model helpers.
- `scripts/tickfeat10.py` — cached causal tick ingestion and zero-allocation feature extraction.
- `scripts/phase10_audit.py` — epoch/risk-set audit.
- `scripts/phase12_exact_entry_identity_audit.py` — complete-ledger identity audit.
- `outputs/strategy_reconstruction/phase10_11_model_freeze.json` — discovery-frozen model certificate.
- `outputs/strategy_reconstruction/phase10_11_lockbox_evaluation_report.md` — lockbox report.
- `outputs/strategy_reconstruction/phase12_exact_entry_identity_report.md` — complete-ledger audit report.
- `outputs/strategy_reconstruction/phase12_exact_entry_identity_results.json` — stored final audit metrics.
- `outputs/strategy_reconstruction/phase12_rule_certificate.json` — R1 threshold and coefficient certificate.

The stored complete-ledger result is **FAIL** for exact identity, with:

- TP = 50,
- FN = 370,
- FP = 485,
- TN = 205,161,
- precision ≈ 0.0935,
- recall ≈ 0.1190,
- F1 ≈ 0.1047.

This is an important negative result: the frozen R1 threshold rule is not an exact deterministic identity for the complete observed entry ledger.

## 5. Large-file and storage policy

GitHub rejects individual blobs larger than 100 MB and regular Git history is unsuitable for multi-hundred-megabyte intermediate artifacts. The local workspace contains the following oversized artifacts:

- `outputs/strategy_reconstruction/phase10_11_risk_sets.json` — approximately 616 MB.
- `claude_handoff/xauusd_reverse_engineering_full_handoff.zip` — approximately 551 MB; staging archive, not authoritative source.
- `data/market/raw_ticks.zip` — approximately 231 MB.
- `outputs/strategy_reconstruction/phase10_11_tick_features.parquet` — approximately 127 MB.
- `outputs/market_reconstruction/phase5_feature_table.csv.gz` — approximately 101 MB.

The repository `.gitignore` excludes the staging archive, raw tick archive, generated handoff bundle, and oversized Phase 10/11 intermediates. These files remain available locally and are represented in the handoff context rather than silently committed. If future publication requires them, use an explicit Git LFS/externally versioned data policy and document the remote object store, checksum, and retrieval command before committing pointer files.

The checked-in `repository_manifest.json` records SHA-256 hashes, byte sizes, phase/category labels, and classification flags for the files admitted to the repository.

## 6. Reproduction and validation

From PowerShell at the repository root:

```powershell
# Create/use an isolated environment outside the committed tree if desired
python -m pytest
```

The current baseline verification is:

```text
44 passed in 4.81s
```

To inspect or rerun the complete-ledger construction without loading the full tick universe:

```powershell
python scripts/phase12_exact_entry_identity_audit.py --dry-run
```

Expected structural counts:

```text
N_E = 420
N_F = 205646
N_U = 206066
E ∩ F = 0
```

The full Phase 12 run is resource-intensive and should only be started when the raw tick archive and all prerequisite artifacts are present. It must not be treated as a tuning/search step: the threshold is frozen from discovery controls only.

## 7. Onboarding instructions for a future research/coding agent

1. Read this handoff and `README.md` before modifying code.
2. Inspect `repository_manifest.json` to determine whether a file is source code, raw data, derived evidence, or documentation.
3. Treat `data/raw/trades_raw.tsv` and the Phase 7c reconciliation as immutable provenance inputs.
4. Preserve the 423-record ledger and 420-epoch distinction. Do not introduce a generic proximity merge.
5. Read the relevant phase status/report before rerunning a phase. Existing reports may record negative results and evidence boundaries that must not be overwritten.
6. Keep discovery and lockbox artifacts separate. Never derive a threshold, baseline, scaler, model choice, or feature-selection decision from lockbox data.
7. Preserve strict causality in tick extraction: every tick must satisfy `tick_time < decision_time`.
8. Run focused tests first, then the full suite (`python -m pytest`).
9. Do not fabricate missing data or outputs. If a file is unavailable, report the missing provenance and stop the dependent analysis.
10. Update `repository_manifest.json` after adding or modifying tracked artifacts.

## 8. Open questions and limitations

- The exact proprietary source strategy remains non-identifiable from the supplied closed-trade ledger and available market data.
- Feed reconstruction is constrained by the available raw tick history, broker-side conventions, and timestamp alignment.
- Entry and exit behavior may depend on unobserved account state, order-management state, spread/liquidity, news/event feeds, or broker execution conditions.
- Experimental Phase 10/11 and Phase 12 results do not convert a predictive association into a source-code identity claim.
- The full raw tick archive and oversized generated intermediates are local/external data assets, not regular Git blobs.
- GitHub publication is a separate outward-facing operation; no credentials, tokens, or secret files are included in this package.

## 9. Publication checklist

Before pushing the repository:

- [ ] Confirm `.gitignore` excludes credentials, environment files, caches, virtual environments, staging archives, and oversized raw/intermediate files.
- [ ] Run `python -m pytest` and record the result.
- [ ] Regenerate `repository_manifest.json` after final file changes.
- [ ] Review `git status --short` and `git diff --cached --stat`.
- [ ] Ensure the GitHub target repository is owned by `shreyash1234566` and has the intended visibility.
- [ ] Authenticate with GitHub using the user’s preferred method; never write the token into the repository.
- [ ] Push branch `forensic-repository-handoff` and set its upstream.
- [ ] Confirm the remote commit and repository URL after publication.
