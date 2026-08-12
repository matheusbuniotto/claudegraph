---
name: teacher
description: Teach a topic via a small state graph (explain -> demonstrate -> check, loops on misunderstanding).
---

Topic: $ARGUMENTS

You MUST follow this exact procedure. Do not skip the script call. Do not narrate a step's content before calling the script for it.

1. Initialize state: `{"current_node": "explain", "data": {}, "retry_count": 0, "max_retries": 2}`
2. Run: `echo '<state json>' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/teacher_skill.py`
   - If it exits non-zero, stop and show the user the `error` field. Do not proceed.
3. Read `next_node` from the script's output. Generate content for that node only:
   - `explain`: 3-5 sentence plain-language explanation
   - `demonstrate`: one concrete example
   - `check`: ask one question, wait for the user's answer
   - `end`: wrap up (see step 5)
4. After a `check` question is answered, set `data.understood` to true/false based on the answer, carry forward the `retry_count`/`max_retries` the script last returned, and go back to step 2.
5. When `next_node` is `end`: if the last `retry_count` is below `max_retries`, congratulate — they got it. If it's at `max_retries`, say plainly that this needs a different approach (show code, suggest a debugger, or ask a human) rather than looping again.

Never hand-wave step 2. If you find yourself describing what the graph "would" do instead of actually running the command, stop and run it.
