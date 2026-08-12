---
name: <kebab-case-name>
description: <What it does and when to use it. Claude reads this to decide when to apply the skill — lead with the key use case. Combined with when_to_use, truncated at 1536 chars in the listing.>
---

<!--
Frontmatter notes (see https://code.claude.com/docs/en/skills):

  - Goes at `skills/<kebab-case-name>/SKILL.md` in the plugin root. The file must be
    named SKILL.md exactly.
  - For a PLUGIN skill, `name` sets the last segment of the invoking command and the
    plugin prefix stays in place — so use kebab-case, not Title Case.
  - Only these six fields survive packaging for claude.ai / the Skills API:
    name, description, license, compatibility, metadata, allowed-tools.
    Any other field is a HARD ERROR there, not a silently ignored one. Claude Code
    itself accepts more (when_to_use, argument-hint, disable-model-invocation,
    user-invocable, model, context, paths, ...) — add them only if this skill will
    never be packaged. There is no `version` field.
  - Tool pre-approval is `allowed-tools` (hyphenated) here. Subagents use `tools`
    (no hyphen). Mixing them up silently does nothing.
  - `${CLAUDE_SKILL_DIR}` points at THIS skill's directory, not the plugin root — use
    it for files bundled beside this SKILL.md. Use `${CLAUDE_PLUGIN_ROOT}` for anything
    elsewhere in the plugin.

Delete this comment block when adapting.
-->

<One paragraph: what this skill provides that the node's inline `goal` can't carry —
usually domain knowledge, a schema, or a procedure reused across several nodes. If it's
only used by one node and adds no reusable knowledge, that node's `goal` is enough and
this skill should not exist.>

## When this applies

<The branch(es) of the graph that reach for this. A skill tied to a single node's happy
path is usually the node's `goal` in disguise.>

## Procedure

1. <Imperative steps.>
2. <...>

## Reference

<Schemas, field meanings, domain rules the procedure depends on. Keep detail here rather
than in the steps, so the steps stay scannable.>
