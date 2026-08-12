# AGENTS.md

Cookie-cutter builder for LangGraph-style Claude Code plugins: a stdlib-only
routing engine (`scripts/graph.py` + `scripts/skill_runner.py`), a generator
skill (`skills/scaffold-graph-plugin/`) that interrogates for a graph spec and
produces real plugins from it, and one worked example
(`scripts/template_skill.py`) that both proves the pattern and serves as the
hand-copy starting point. Full rationale lives in
`README.md` (structure/install/customize), `ROADMAP.md` (ideas considered and
deliberately deferred, with why), and `LEARNING_CHECKLIST.md` (the design
decisions behind the current shape). Read those before re-deriving anything
they already answer.

## Adding a skill or feature

- New plugin built on this engine: use `skills/scaffold-graph-plugin/` — it
  interrogates for the full graph spec first, which is the step that decides
  output quality. Hand-copying `scripts/template_skill.py` per `README.md`'s
  Customize section is the fallback, not the default.
- New skill inside this plugin: copy `scripts/template_skill.py`, follow
  `README.md`'s Customize section. Never edit `graph.py`/`skill_runner.py` to
  fit one skill's needs — they're skill-agnostic on purpose.
- New engine capability (`graph.py`/`skill_runner.py`): add it once a real,
  proven caller needs it, not because it might be useful later. Every YAGNI
  call already made is logged in `ROADMAP.md` — check it before
  re-litigating the same idea from scratch.
- Stdlib only. No new dependency without first checking `ROADMAP.md`'s
  reasoning on why this stays pip-install-free.
- One meaning, one place. If a fact already lives in `README.md`/`ROADMAP.md`/
  the code itself, point to it instead of restating it in a new doc or comment.
- Skill-agnostic logic goes in `graph.py`; driver/CLI plumbing goes in
  `skill_runner.py`; everything skill-specific stays in the skill's own file.
  Misplacing new code across this boundary is the most common way this
  template rots.

## Guardrails — flag risk before implementing

Surface the tradeoff to the user, with a smaller alternative, before building
a request that would: add a third-party dependency; add concurrency/parallel
execution (the DAG-scheduler idea in `ROADMAP.md` is real but is its own
project, not an addition here); weaken or remove boundary validation
(malformed-input handling, the step budget); generalize from a single
example before a second real caller exists; or change the CLI contract
`skill_runner.py` promises (stdin/stdout JSON shape) without updating every
consumer and the tests. State the risk plainly, the way this project's own
history already does in `ROADMAP.md`, and let the user decide with that in
view — agreement without that context is the risk, not the pushback.

Every change ships with passing tests
(`python3 -m unittest scripts.test_template_skill -v` from `claudegraph/`)
and, if behavior changed, an updated `README.md`/`ROADMAP.md` — a stale doc
here is worse than no doc.
