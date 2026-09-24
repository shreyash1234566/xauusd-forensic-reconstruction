# Streaming Tick Feature Extraction & Parity Test Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a streaming, memory-bounded two-pass tick feature extraction pipeline that processes all 4,093,881 controls without cumulative DataFrame retention, and verify exact parity against the reference implementation.

**Architecture:** Pass 1 computes discovery-only hour baselines without storing raw ticks; Pass 2 writes standardized 8-feature vectors into a compact, timestamp-indexed store in bounded batches. Downstream consumers are updated to look up features rather than raw DataFrames.

**Tech Stack:** Python 3.11+, pandas, numpy, pyarrow/parquet.

## Global Constraints
- Strictly preserve exact case/control timestamps and within-minute phase alignment.
- Strictly preserve the 310-second lookback and `tick_ts_ms < target_ms` causal boundary.
- Do not subsample, filter, or alter the 4,093,881 control timestamps.
- Zero-fill or fallback for missing data is strictly prohibited; missing features must remain `np.nan`.
- Do not run full models, freeze, or lockbox evaluation during this task.

---

### Task 1: Create Parity & Memory Test Harness

**Files:**
- Create: `E:\reverse -traid\scripts\test_tickfeat10_parity.py`

**Interfaces:**
- Consumes: `TickStore`, `extract_tick_features`, `compute_hour_baselines` from `tickfeat10.py`
- Produces: Executable parity test comparing reference vs. streaming extraction on 317 discovery cases + 1,000 deterministic controls.

- [ ] **Step 1: Write test script scaffolding**
Create `scripts/test_tickfeat10_parity.py` with deterministic sample selection, RSS tracking using `psutil` or `ctypes`, and reference extraction execution.

- [ ] **Step 2: Run test script to verify initial state / failure**
Run: `python "E:\reverse -traid\scripts\test_tickfeat10_parity.py"`
Expected: FAIL or incomplete because streaming implementation is not yet built.

---

### Task 2: Implement Streaming Baseline & Feature Extraction in `tickfeat10.py`

**Files:**
- Modify: `E:\reverse -traid\scripts\tickfeat10.py`

**Interfaces:**
- Consumes: Raw tick files in `data/market/raw_ticks/`
- Produces:
  - `compute_hour_baselines_streaming(store, timestamps, lookback_sec=310.0)`
  - `extract_tick_features_streaming(store, timestamps, baselines, batch_size=10000, output_path=None)`

- [ ] **Step 1: Add streaming hour baselines calculator**
Implement Pass 1 logic in `tickfeat10.py` to aggregate per-hour movement standard deviations and spread means on the fly without storing window DataFrames.

- [ ] **Step 2: Add streaming feature extractor with batching**
Implement Pass 2 logic in `tickfeat10.py` to extract 8-feature vectors in batches of 10,000, storing them into an in-memory dictionary or structured array and deleting the temporary DataFrames after each item.

- [ ] **Step 3: Run the parity test**
Run: `python "E:\reverse -traid\scripts\test_tickfeat10_parity.py"`
Expected: PASS with 100% numerical match (within tolerance `1e-6`, matching NaNs) and minimal memory growth.

---

### Task 3: Update `phase10_11_main.py` Downstream References

**Files:**
- Modify: `E:\reverse -traid\scripts\phase10_11_main.py`

**Interfaces:**
- Consumes: New streaming extractors from `tickfeat10.py`
- Produces: Integrated pipeline in `phase10_11_main.py` that uses compact feature lookups.

- [ ] **Step 1: Update Step 4 (Feature Extraction) and Step 5 (Baselines)**
Refactor `extract_all_tick_features` and `compute_baselines` to use the streaming implementation.

- [ ] **Step 2: Refactor Downstream Feature Accessors**
Update `assemble_feature_matrix`, `build_m4_fold_matrix`, `chronological_validation`, and `evaluate_lockbox` to look up precomputed feature arrays instead of invoking `extract_tick_features(ctd.get("ticks"), ...)` on raw tick DataFrames.

- [ ] **Step 3: Compile all modified files**
Run:
`python -m py_compile "E:\reverse -traid\scripts\tickfeat10.py"`
`python -m py_compile "E:\reverse -traid\scripts\phase10_11_main.py"`
Expected: PASS (exit code 0, no syntax errors).
