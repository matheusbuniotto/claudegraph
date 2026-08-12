---
name: graph-spec
description: Interrogate for a complete graph plan and write it to a spec file — the input /build-graph implements.
---

Request: $ARGUMENTS

Produce one artifact: a complete, confirmed graph spec written to
`./<plugin-name>.graph-spec.md`. Write no plugin code — that is `/build-graph`'s job, and
reaching for it here is how the spec ends up half-specified.

Read `${CLAUDE_PLUGIN_ROOT}/references/graph-spec.md` first. It holds the field schema, a
worked example, how each field maps to code, and the rules for when a node warrants an
agent/skill/MCP attachment.

## Interrogate

**Every field in the schema must be filled by the user's answer, never by invention.** An
unfilled field is a question still owed. This holds whether the user arrives with nothing or
with a written spec — a supplied spec is a starting point, not a finished interrogation.
Read what they gave, then drive out what it left implicit: unstated edge cases, goals too
vague to generate from, outputs nothing downstream reads, loops with no termination.

Ask in this order, in small batches rather than one overwhelming block:

1. **Identity** — plugin name (kebab-case) and one-line description.
2. **Node inventory** — what are the steps, in order? Names only, first.
3. **Per node** — `kind`, `goal`, `expected_output`, any extra `log_fields`. Use
   AskUserQuestion for `kind` (fixed choice: task / human_gate / end); ask open questions for
   goals and domain logic.
4. **Edges** — the plain path, then for every branching node: the exact condition and the
   exact destination for each branch.
5. **Loop/retry policy** — for any edge returning to an earlier node: trigger, termination
   condition, and which transition increments the retry counter.
6. **External systems** — does any node need a database, API, issue tracker, or anything
   outside the conversation? If yes: which node, which system, and does the user already have
   that MCP server installed?
7. **Node attachments** — apply the judgment rules in `references/graph-spec.md` rather than
   asking the user to guess. Default is inline with no attachment and most nodes should stay
   there; propose one only for nodes the rules actually flag, and say why.
8. **Observability** — anything beyond the default evidence log (`from`/`to`/`data`/
   `retry_count`/`step_count` are already logged).

Stop and flag, rather than designing around it, if the request needs concurrent branches:
this engine is single-active-node (see `${CLAUDE_PLUGIN_ROOT}/ROADMAP.md`'s Terraform/DAG
section). A parallel graph is a different, unbuilt foundation.

## Write the spec

Write `./<plugin-name>.graph-spec.md` in the structured form shown in
`references/graph-spec.md`'s worked example, then **show it to the user and get explicit
confirmation.** The restatement is where mismatched assumptions surface cheaply — a spec the
user skimmed is not a confirmed spec.

Close by telling them the file path and that `/build-graph <path>` implements it. They can
edit the file by hand first; it is the source of truth from here.
