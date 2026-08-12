#!/usr/bin/env python3
"""Scaffold a new graph-style plugin from claudegraph.

Deterministic, mechanical part only: copies graph.py/skill_runner.py verbatim
(never touched per-plugin — they're skill-agnostic by design), renames the
template skill/test/command files, and rewrites plugin.json's name/description.
It does NOT write any graph logic (nodes, router, command procedure) — that's
domain knowledge only the requester has, and stays /build-graph's job to guide.

Usage:
  python3 scaffold_plugin.py --name my-plugin --description "..." --dest /path/to/parent
  [--source /path/to/claudegraph]  # defaults to this plugin's own root
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

# This script lives at <plugin-root>/scripts/scaffold_plugin.py
DEFAULT_SOURCE = Path(__file__).resolve().parents[1]

# Not copied: .git internals, caches, and session-specific history that doesn't
# apply to a new plugin.
EXCLUDE_NAMES = {"LEARNING_CHECKLIST.md", "__pycache__", ".git", ".ruff_cache"}

# Runtime artifacts from running the source template (evidence logs, checkpoints).
# Copying them would hand a new plugin someone else's session history.
EXCLUDE_SUFFIXES = (".log.jsonl", ".checkpoint.json", ".pyc")

# The generator's own machinery. A plugin built by claudegraph is a graph plugin,
# not another copy of claudegraph — without this, every generated plugin would
# ship a /build-graph command it has no business owning.
EXCLUDE_RELPATHS = {
    Path("scripts/scaffold_plugin.py"),
    Path("commands/build-graph.md"),
    Path("commands/graph-spec.md"),
    Path("references/graph-spec.md"),
    Path("references"),
    Path("templates"),
}


def _make_ignore(source: Path):
    def _ignored(current_dir: str, names: list[str]) -> list[str]:
        rel_dir = Path(current_dir).resolve().relative_to(source)
        return [
            n
            for n in names
            if n in EXCLUDE_NAMES
            or n.endswith(EXCLUDE_SUFFIXES)
            or (rel_dir / n) in EXCLUDE_RELPATHS
        ]

    return _ignored


def scaffold(name: str, description: str, dest_parent: Path, source: Path) -> Path:
    if not source.is_dir():
        raise SystemExit(f"source template not found: {source}")

    dest = dest_parent / name
    if dest.exists():
        raise SystemExit(f"destination already exists, refusing to overwrite: {dest}")

    shutil.copytree(source, dest, ignore=_make_ignore(source.resolve()))

    # Verify the engine files landed byte-identical — if this ever fails, the
    # copy logic above is broken, not something to silently work around.
    for engine_file in ("scripts/graph.py", "scripts/skill_runner.py"):
        src_bytes = (source / engine_file).read_bytes()
        dst_bytes = (dest / engine_file).read_bytes()
        assert src_bytes == dst_bytes, f"{engine_file} diverged during copy"

    # Python module/file names can't contain hyphens (breaks `-m unittest a.b`
    # and `import`), but plugin names are conventionally kebab-case everywhere
    # else (plugin.json, marketplace.json, command files) — so derive a
    # separate underscore-safe stem for the two Python files only.
    py_stem = name.replace("-", "_")

    # Rename the template skill/test/command files to the new plugin's name.
    (dest / "scripts" / "template_skill.py").rename(
        dest / "scripts" / f"{py_stem}_skill.py"
    )
    test_path = dest / "scripts" / f"test_{py_stem}_skill.py"
    (dest / "scripts" / "test_template_skill.py").rename(test_path)
    command_path = dest / "commands" / f"{name}.md"
    (dest / "commands" / "teacher.md").rename(command_path)

    # Mechanical fix-up, not domain content: the renamed test/command files
    # still reference the old filenames internally (e.g. SCRIPT = ... /
    # "template_skill.py"), which would point at a file that no longer
    # exists. Repoint them so what's left to edit is runnable, not broken.
    test_path.write_text(
        test_path.read_text().replace("template_skill", f"{py_stem}_skill")
    )
    command_path.write_text(
        command_path.read_text().replace(
            "scripts/template_skill.py", f"scripts/{py_stem}_skill.py"
        )
    )

    plugin_json_path = dest / ".claude-plugin" / "plugin.json"
    plugin_json = json.loads(plugin_json_path.read_text())
    plugin_json["name"] = name
    plugin_json["description"] = description
    plugin_json_path.write_text(json.dumps(plugin_json, indent=2) + "\n")

    if (dest / "CLAUDE.md").is_symlink():
        (dest / "CLAUDE.md").unlink()
        (dest / "CLAUDE.md").symlink_to("AGENTS.md")

    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="kebab-case plugin name")
    parser.add_argument("--description", required=True)
    parser.add_argument(
        "--dest", required=True, type=Path, help="parent directory for the new plugin"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()

    dest = scaffold(args.name, args.description, args.dest, args.source)
    py_stem = args.name.replace("-", "_")

    print(f"Scaffolded {dest}")
    print("Still needed (mechanical copy stops here, this part is domain-specific):")
    print(f"  - scripts/{py_stem}_skill.py: build_graph()/router/on_transition")
    print(f"  - commands/{args.name}.md: rewrite as a literal numbered procedure")
    print(f"  - scripts/test_{py_stem}_skill.py: rewrite scenarios for the real graph")
    print("  - .claude-plugin/plugin.json, AGENTS.md, README.md: replace 'teacher'/")
    print("    explain-demonstrate-check mentions with the real domain")
    print(f"  - run: cd {dest} && python3 -m unittest scripts.test_{py_stem}_skill -v")


if __name__ == "__main__":
    main()
