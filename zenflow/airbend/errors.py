"""Structured errors and exit codes (AXI §6).

Exit codes: 0 success (incl. no-ops), 1 error, 2 usage error. Errors go to
stdout in the same structured format as normal output; tracebacks and raw
dependency noise never leak.
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


class AirbendError(Exception):
    """Operational error → `error:` on stdout, exit 1."""

    def __init__(self, message: str, help_text: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.help_text = help_text

    def toon(self) -> str:
        from airbend.toon import dumps

        doc: dict[str, str] = {"error": self.message}
        if self.help_text:
            doc["help"] = self.help_text
        return dumps(doc)
