---
name: teacher
description: Teach a topic via a small state graph (explain -> demonstrate -> check, loops on misunderstanding).
---

Topic: $ARGUMENTS

You MUST follow this exact procedure. Do not skip the script call. Do not narrate a step's content before calling the script for it.

1. Initialize state: `{"current_node": "explain", "data": {}, "retry_count": 0, "max_retries": 2}`
2. Run: `echo '<state json>' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/teacher_skill.py`
   - If it exits non-zero, stop and show the user the `error` field (covers malformed input and
     the step-budget safety net tripping). Do not proceed.
3. Read `next_node`, `kind`, and `goal` from the output. Generate content matching that node's
   `goal`. If `kind` is `human_gate` (the `check` node), ask one question and wait for the user's
   answer before continuing — don't call the script again until they've responded.
4. After a `check` question is answered, set `data.understood` to true/false based on the answer,
   carry forward `retry_count`/`max_retries`/`step_count` from the script's last output, and go
   back to step 2.
5. When `done` is `true`: if the last `retry_count` is below `max_retries`, congratulate — they
   got it. If it's at `max_retries`, say plainly that this needs a different approach (show code,
   suggest a debugger, or ask a human) rather than looping again.

A JSONL evidence log and a JSON checkpoint of the last state are written automatically on every
call (see README) — nothing extra to do here, but if a session gets interrupted, the checkpoint
file is where a fresh session can recover `current_node` etc. from.

Never hand-wave step 2. If you find yourself describing what the graph "would" do instead of actually running the command, stop and run it.
