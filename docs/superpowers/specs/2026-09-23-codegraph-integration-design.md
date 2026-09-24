# CodeGraph Integration Design

**Date:** 2026-09-23  
**Status:** Approved  
**Package:** `@colbymchenry/codegraph` (v1.6.0+)  

## Objective

Integrate `@colbymchenry/codegraph` into `E:\reverse -traid` to provide local code intelligence, AST symbol indexing, call/callee graphs, and MCP server tooling for Claude Code and command-line workflows.

## Scope & Target Codebase

CodeGraph will index the active code and test directories while strictly ignoring large datasets, parquet files, raw tick data, and temporary artifacts.

### Included in Index
- `scripts/` — Pipeline execution scripts (`phase10_11_main.py`, `model_lib10b.py`, `tickfeat10.py`, etc.)
- `src/` — Supporting modules and library code
- `tests/` — Test suites and verification harnesses
- `research/` — Strategy research scripts and exploratory analysis notebooks
- Configuration files in root (`package.json`, etc.)

### Ignored from Index
- `data/` (raw data, market feeds, parquet files)
- `outputs/` (generated artifacts, model freeze files, logs, charts)
- `download/` (raw tick archives)
- `.venv/` (Python virtual environment)
- `node_modules/` (Node dependencies)
- `.claude/` (Claude session state and worktrees)
- `.pytest_cache/`
- `claude_handoff/` and `claude_web_handoff/`

## Architecture & Integration Components

### 1. Global CLI Installation
Install `@colbymchenry/codegraph` globally using npm:
```bash
npm install -g @colbymchenry/codegraph
```

### 2. Ignore Configuration (`.codegraphignore` / `.ignore`)
Create a `.codegraphignore` (and `.ignore` if needed) in the root directory to guarantee worker processes do not scan or index data partitions:
```
data/
outputs/
download/
.venv/
node_modules/
.claude/
.pytest_cache/
claude_handoff/
claude_web_handoff/
*.parquet
*.csv
*.bin
*.jsonl
```

### 3. Repository Initialization & Indexing
Run non-interactive initialization:
```bash
codegraph init --yes "E:\reverse -traid"
```
This builds the SQLite/AST database under `E:\reverse -traid\.codegraph/`.

### 4. Claude Code MCP Server Configuration
Wire CodeGraph MCP server to Claude Code:
```bash
codegraph install --target=claude --location=global --yes
```
This registers the MCP tools:
- `codegraph_explore`
- `codegraph_node`
- `codegraph_context`
- `codegraph_impact`
- `codegraph_callers`
- `codegraph_callees`

## Verification & Acceptance Criteria
1. `codegraph status` executes cleanly and reports indexed symbol/file counts without error.
2. `codegraph query "fit_conditional_logit"` returns matches in `scripts/model_lib10b.py`.
3. `codegraph callers "extract_tick_features_arrays"` identifies callers in `scripts/tickfeat10.py` and `scripts/phase10_11_main.py`.
4. MCP tool configuration is verified in Claude Code configuration files.
