---
name: <Skill Name>
description: This skill should be used when <specific trigger phrases a user would actually say>. <One sentence on what it provides.>
version: 0.1.0
---

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
