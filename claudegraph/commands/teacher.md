---
name: teacher
description: "Example run: teach a topic via a small state graph (explain -> demonstrate -> check, loops on misunderstanding)."
---

Topic: $ARGUMENTS

You MUST follow this exact procedure. Do not skip the script call. Do not narrate a step's content before calling the script for it.

1. Initialize state: `{"current_node": "explain", "data": {}, "retry_count": 0, "max_retries": 2}`
2. Run: `echo '<state json>' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/template_skill.py`
   - If it exits non-zero, stop and show the user the `error` field (covers malformed input and
     the step-budget safety net tripping). Do not proceed.
   - If the node just completed used tools (e.g. `Read` on a source file) or retrieved
     something worth an evidence trail, report it on this call as
     `"actions": [{"tool": "Read", "target": "..."}]`. Optional — omit or send `[]` when
     there's nothing to report. It's logged against the transition, not carried in `data`.
3. **Print the `banner` field verbatim on its own line, before anything else**, so the user can
   see which node is running and why. It is preformatted — print it, don't rewrite or summarize
   it. Example: `▶ demonstrate (step 2) — one concrete example`
4. Read `next_node`, `kind`, and `goal` from the output. Generate content matching that node's
   `goal`. If `kind` is `human_gate` (the `check` node), ask one question and wait for the user's
   answer before continuing — don't call the script again until they've responded.
5. After a `check` question is answered, set `data.understood` to true/false based on the answer,
   carry forward `retry_count`/`max_retries`/`step_count`/`run_id` from the script's last output,
   and go back to step 2.
6. When `done` is `true`: if the last `retry_count` is below `max_retries`, congratulate — they
   got it. If it's at `max_retries`, say plainly that this needs a different approach (show code,
   suggest a debugger, or ask a human) rather than looping again.

A JSONL evidence log and a JSON checkpoint of the last state are written automatically on every
call, scoped under `runs/<run_id>/` (see README) — nothing extra to do here beyond carrying
`run_id` forward per step 5. If a session gets interrupted and `run_id` is lost (e.g. context
compaction), don't start a fresh, disconnected run: read `runs/latest/<skill>.checkpoint.json`
for `current_node` etc. and `readlink runs/latest` for `run_id`, then resume from step 2 in the
same run. For a node whose content is substantial
enough that a later node or a human should be able to reread it without scrolling back through
the conversation, write it with `Write` to `runs/<run_id>/artifacts/<node>.md` and report that
in the next call's `actions` (e.g. `{"tool": "Write", "target": "runs/<run_id>/artifacts/explain.md"}`)
— not required for this example's short explanations, but the convention any real skill built
on this template should follow rather than growing `data` to carry full node output.

Never hand-wave step 2. If you find yourself describing what the graph "would" do instead of actually running the command, stop and run it.
