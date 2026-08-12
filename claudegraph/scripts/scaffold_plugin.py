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
import re
import shutil
from pathlib import Path

# This script lives at <plugin-root>/scripts/scaffold_plugin.py
DEFAULT_SOURCE = Path(__file__).resolve().parents[1]

# Not copied: .git internals, caches, and claudegraph's own design history.
# LEARNING_CHECKLIST.md and ROADMAP.md record decisions and deferrals made while
# building claudegraph — a fresh plugin has neither, and inheriting them ships a
# new project with someone else's backlog.
EXCLUDE_NAMES = {
    "LEARNING_CHECKLIST.md",
    "ROADMAP.md",
    "__pycache__",
    ".git",
    ".ruff_cache",
}

# Rendered fresh from templates/ rather than copied, so the generated plugin
# documents itself instead of claudegraph. README is fully plugin-specific;
# AGENTS.md keeps the rules that genuinely transfer (don't edit the engine,
# where domain code belongs, tests must pass) and drops claudegraph's meta-rules
# about its own generator commands.
RENDERED = {
    Path("README.md"): "plugin-README.md",
    Path("AGENTS.md"): "plugin-AGENTS.md",
}

# Runtime artifacts from running the source template (evidence logs, checkpoints).
# Copying them would hand a new plugin someone else's session history.
EXCLUDE_SUFFIXES = (".log.jsonl", ".checkpoint.json", ".pyc")

# The generator's own machinery. A plugin built by claudegraph is a graph plugin,
# not another copy of claudegraph — without this, every generated plugin would
# ship a /build-graph command it has no business owning.
EXCLUDE_RELPATHS = {
    Path("scripts/scaffold_plugin.py"),
    Path("scripts/test_scaffold_plugin.py"),
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
            or (rel_dir / n) in RENDERED
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

    # Mechanical fix-up, not domain content: the renamed files still carry the
    # source plugin's filenames and identity internally (SCRIPT = ... /
    # "template_skill.py", SKILL_NAME = "teacher", `name: teacher` frontmatter).
    # Left alone, the command isn't invocable under its own name and the log and
    # checkpoint files are written under "teacher". Repoint them so what's left
    # to edit is the graph itself, not someone else's labels.
    pascal = "".join(part.capitalize() for part in name.replace("-", "_").split("_"))

    skill_path = dest / "scripts" / f"{py_stem}_skill.py"
    skill_path.write_text(
        skill_path.read_text().replace(
            'SKILL_NAME = "teacher"', f'SKILL_NAME = "{name}"'
        )
    )

    test_path.write_text(
        test_path.read_text()
        .replace("template_skill", f"{py_stem}_skill")
        .replace("class TeacherSkillTests", f"class {pascal}SkillTests")
    )

    command_text = command_path.read_text().replace(
        "scripts/template_skill.py", f"scripts/{py_stem}_skill.py"
    )
    command_text = re.sub(r"^name: teacher$", f"name: {name}", command_text, flags=re.M)
    command_text = re.sub(
        r"^description: .*$",
        f"description: {json.dumps(description)}",
        command_text,
        count=1,
        flags=re.M,
    )
    command_path.write_text(command_text)

    # Render the generated plugin's own docs, replacing (not copying) claudegraph's.
    for rel_target, template_name in RENDERED.items():
        text = (source / "templates" / template_name).read_text()
        for placeholder, value in (
            ("{{NAME}}", name),
            ("{{DESCRIPTION}}", description),
            ("{{PY_STEM}}", py_stem),
        ):
            text = text.replace(placeholder, value)
        (dest / rel_target).write_text(text)

    plugin_json_path = dest / ".claude-plugin" / "plugin.json"
    plugin_json = json.loads(plugin_json_path.read_text())
    plugin_json["name"] = name
    plugin_json["description"] = description
    # claudegraph's identity, not the new plugin's — drop rather than misattribute.
    for inherited in ("homepage", "repository", "keywords", "author"):
        plugin_json.pop(inherited, None)
    plugin_json_path.write_text(json.dumps(plugin_json, indent=2) + "\n")

    # copytree dereferences symlinks, so CLAUDE.md arrives as a regular file
    # holding the SOURCE plugin's AGENTS.md text — which then survives AGENTS.md
    # being rendered fresh. Recreate the link unconditionally rather than testing
    # is_symlink(), which is False in exactly the case that needs fixing.
    claude_md = dest / "CLAUDE.md"
    if claude_md.exists() or claude_md.is_symlink():
        claude_md.unlink()
    claude_md.symlink_to("AGENTS.md")

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
