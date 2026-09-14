"""airbend CLI entry point.

AXI §10 fast path: a bare `-v`/`-V`/`--version` resolves from the leaf
`version` module before the command graph is imported. Everything else loads
`airbend.app` lazily so the version probe never pays for the CLI machinery.
"""

from __future__ import annotations

import sys

_VERSION_FLAGS = ("-v", "-V", "--version")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 1 and args[0] in _VERSION_FLAGS:
        from airbend.version import VERSION  # leaf module, stdlib only

        print(VERSION)
        return 0
    from airbend.app import main as app_main  # heavy graph loads only here

    return app_main(args)
