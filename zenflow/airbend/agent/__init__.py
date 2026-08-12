"""Agent executor package — the runner is an agent (LLM-driven, tool-using).

Lazy-imported: the CLI fast path and non-agent runs never pay for this code.
"""

from airbend.agent.loop import AgentResult, run_agent

__all__ = ["AgentResult", "run_agent"]
