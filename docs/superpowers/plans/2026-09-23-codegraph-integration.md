# CodeGraph Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install, configure, index, and wire `@colbymchenry/codegraph` into `E:\reverse -traid` for CLI codebase intelligence and Claude Code MCP tool access.

**Architecture:** Install `@colbymchenry/codegraph` globally via npm, configure strict ignore rules in `.codegraphignore` to protect data/output partitions, initialize `.codegraph/` repository index, wire Claude Code MCP server via `codegraph install`, and verify symbol/call-graph queries.

**Tech Stack:** Node.js v24+, npm, `@colbymchenry/codegraph`, Claude Code MCP configuration.

## Global Constraints

- Never scan or index `.parquet`, `.csv`, `.bin`, `data/`, `outputs/`, `download/`, or `.venv/` folders.
- Indexing must complete non-interactively (`--yes`).
- All tool calls and commands must run cleanly in Windows 11 PowerShell environment.

---

### Task 1: Create `.codegraphignore` Configuration

**Files:**
- Create: `E:\reverse -traid\.codegraphignore`
- Create: `E:\reverse -traid\.ignore`

**Interfaces:**
- Produces: Ignore patterns parsed by `@colbymchenry/codegraph` file scanners.

- [x] **Step 1: Write `.codegraphignore` and `.ignore`**
- [x] **Step 2: Verify files exist in root**
- [x] **Step 3: Commit / Checkpoint**

---

### Task 2: Install `@colbymchenry/codegraph` Globally and in `package.json`

**Files:**
- Modify: `E:\reverse -traid\package.json`

**Interfaces:**
- Produces: Global `codegraph` binary on system PATH and local devDependency.

- [x] **Step 1: Install globally via npm**
- [x] **Step 2: Add to `package.json` devDependencies and scripts**
- [x] **Step 3: Verify binary runs**

---

### Task 3: Initialize CodeGraph Index

**Files:**
- Create: `E:\reverse -traid\.codegraph/`

**Interfaces:**
- Produces: SQLite/AST index database of Python scripts, tests, research, and source modules.

- [x] **Step 1: Run non-interactive initialization**
- [x] **Step 2: Check index status**

---

### Task 4: Configure Claude Code MCP Server Integration

**Files:**
- Modify: Claude Code MCP configuration file (`~/.claude.json` / Claude settings)

**Interfaces:**
- Produces: Active MCP server registration for `codegraph`.

- [x] **Step 1: Run CodeGraph MCP installer for Claude**
- [x] **Step 2: Verify MCP configuration snippet**

---

### Task 5: End-to-End Verification

**Files:**
- Read: `scripts/model_lib10b.py`, `scripts/tickfeat10.py`

**Interfaces:**
- Consumes: `.codegraph/` index

- [x] **Step 1: Test symbol query**
- [x] **Step 2: Test caller graph**
- [x] **Step 3: Test impact analysis**
