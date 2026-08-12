# templates/

Adapted by `/build-graph` into a generated plugin — **per node, only when
`../references/graph-spec.md`'s rules flag that node**. A generated plugin where every
node has all three is a failure of that judgment, not thoroughness.

This directory is excluded from generated plugins (`EXCLUDE_RELPATHS` in
`../scripts/scaffold_plugin.py`) — it is generator machinery, not plugin content.

| Template | Copy to | Applied by |
|---|---|---|
| `plugin-README.md` | `README.md` | `scaffold_plugin.py`, automatically |
| `plugin-AGENTS.md` | `AGENTS.md` (+ `CLAUDE.md` symlink) | `scaffold_plugin.py`, automatically |
| `agent.md` | `agents/<node-name>-agent.md` | `/build-graph`, per flagged node |
| `skill.md` | `skills/<kebab-name>/SKILL.md` | `/build-graph`, per flagged node |
| `mcp.json` | `.mcp.json` (note the leading dot) | `/build-graph`, per flagged node |

`plugin-README.md` and `plugin-AGENTS.md` are rendered by the scaffold script with
`{{NAME}}`/`{{DESCRIPTION}}`/`{{PY_STEM}}` substituted — they exist so a generated plugin
documents *itself* rather than inheriting claudegraph's README, AGENTS, and ROADMAP. That
inheritance was a real bug: generated plugins shipped with claudegraph's deferred-ideas
backlog and rules about commands they don't have. `scripts/test_scaffold_plugin.py` now
fails if any claudegraph identity leaks into a scaffolded plugin.

`mcp.json` is stored without the leading dot on purpose: a real `.mcp.json` sitting in the
plugin would be auto-loaded and its placeholder server would fail to start. Rename it on
copy.

## Field traps worth knowing

Each template carries a comment block with its own frontmatter rules. The three that bite
silently:

- **`tools` (agents) vs `allowed-tools` (skills).** Different fields, not aliases. Using
  the wrong one does nothing and reports no error.
- **Plugin subagents ignore `permissionMode`, `mcpServers`, and `hooks`.** Setting them in
  a plugin's `agents/*.md` has no effect.
- **Skills packaged for claude.ai / the Skills API accept only six fields** — `name`,
  `description`, `license`, `compatibility`, `metadata`, `allowed-tools`. Anything else is
  a hard error at packaging time, not a warning. There is no `version` field.

## Verifying an MCP entry

Scaffolding `.mcp.json` writes *configuration for a server the user must already have*. It
does not install anything, and a wrong `command` surfaces as a plugin-load failure rather
than a scaffold error. Confirm the command runs before shipping, and tell the user that
part is unverified until they do.
