# Learning Checklist — LangGraph-style /teacher

Running record of what's been covered and confirmed. Updated as we go.

## 1. The Problem
- [x] Why the current `/teacher` (plain markdown, 3 fixed steps) isn't actually a "graph" — confirmed: it's advisory prose, nothing enforces the structure
- [x] What capability is missing: state, conditional routing, loops — confirmed: it's a cyclic graph (not a DAG), and cycles require explicit loop-termination logic
- [x] The branches considered (full `langgraph` dep / custom stdlib graph / no graph, just prose) — confirmed: picked stdlib graph to keep the plugin pip-install-free (langgraph *can* do cycles, it's just heavier than needed)
- [x] The edge case that motivates a loop: student doesn't understand on first pass — confirmed: needs an explicit exit condition (max retries) or it can loop forever

## 2. The Solution
- [x] Design decision: split into generic reusable `graph.py` (engine, skill-agnostic) vs. `teacher_skill.py` (one example skill built on it) — so /teacher is a demo, not the only thing this can do
- [x] Design decision: assume `python3` present — confirmed via docs search: Claude Cowork runs Claude Code inside a bundled Linux VM (Lima/macOS, WSL2/Windows) with Python 3.10 + Node.js preinstalled, so it's guaranteed by the platform, not just a good bet. Still fail loudly with a clear message for the non-Cowork/CLI-only case.
- [x] The `State` shape — confirmed: `current_node` (in), `next_node` (out of routing, not stored), `data: dict` (skill payload, engine never inspects it), `retry_count` + `max_retries` (loop termination). `node_position`/terminal-ness deliberately left OUT of State — it's graph structure, not per-run state (State = what changes per run; Graph = what's fixed by definition)
- [ ] Node functions (explain / demonstrate / check) — what they do vs. what they *don't* do
- [x] The `Graph` class surface — confirmed: `add_node`/`add_edge`/`add_conditional_edge` for building, one resolving `step(state)` method for querying (not two — "list possible next nodes" has no caller yet, YAGNI'd out; add later if a real debug/visualize use case shows up)
- [x] The conditional edge logic — confirmed: `check` router returns `end` on understood=True OR retries exhausted (no new field needed — compare `retry_count` vs `max_retries` at `end` to tell success from give-up), else `explain`. Router stays a pure predicate; `retry_count += 1` lives in the driver script (skill-specific policy), not in `step()` (skill-agnostic engine) or the router itself.
- [x] Design decision: routing-only — verified directly in code: `teacher_skill.py` main() only ever prints `{next_node, retry_count, max_retries, done}` JSON, never any teaching text. Claude generates all actual content inline, reading `next_node` to know what to say.
- [x] Design decision: zero third-party deps — verified: only stdlib imports across both files (`json`, `sys`, `dataclasses`, `typing`)
- [x] Edge cases: retry count ✓ (tested). Malformed/missing JSON on stdin ✓ (tested: bad JSON and missing keys both fail with a clean `{"error": ...}` on stderr + exit 1, instead of a raw traceback) — validated at the system boundary (stdin), per "validate at boundaries, not internally." "understood" signal = still just Claude's own judgment, passed in as `data.understood`.

- [x] Enforcement, revisited (corrected from an initial wrong guess) — the script makes *routing* deterministic given a call, but nothing forces Claude to actually call it instead of free-forming; that still rests on prose in `commands/teacher.md`. We shrank the advisory surface (whole step order → just "consult the router"), we didn't eliminate it. True enforcement would need a `PreToolUse` hook — out of scope for this KISS example, but noted as a real option.

## 3. Broader Context
- [x] How `commands/teacher.md` invokes the script — a literal numbered procedure (init state → run exact `echo | python3` command → read `next_node` → generate only that node's content → loop), not abstract prose, to minimize drift. Also handles the script's error path (non-zero exit → stop, show error, don't proceed) and the two different `end` outcomes (success vs. exhausted retries) using the same `retry_count`/`max_retries` comparison from Section 2 — no new signal needed.
- [x] What this unlocks — confirmed: `graph.py` is untouched, reusable machinery; any future multi-step command writes a thin `*_skill.py` on top of it instead of re-solving enforcement/statelessness/retries from scratch
- [x] What does NOT change — no pip installs (stdlib only, verified in Section 2), portable via `${CLAUDE_PLUGIN_ROOT}/scripts/teacher_skill.py` in the command file, works wherever the plugin is installed regardless of path
