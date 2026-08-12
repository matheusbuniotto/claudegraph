"""Tests that a scaffolded plugin is a clean cookie-cutter, not a copy of claudegraph.

Run: python3 -m unittest scripts.test_scaffold_plugin -v
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCAFFOLD = Path(__file__).parent / "scaffold_plugin.py"

# Anything naming claudegraph's own identity, commands, or design history. A
# generated plugin mentioning these has inherited someone else's project.
LEAK_PATTERNS = (
    "claudegraph",
    "teacher",
    "build-graph",
    "graph-spec",
    "LEARNING_CHECKLIST",
    "ROADMAP",
    "template_skill",
)

# The one intentional mention: attribution in the generated README.
ALLOWED_LINES = ("Built with", "github.com/matheusbuniotto")


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self._tmp.name)
        proc = subprocess.run(
            [
                sys.executable,
                str(SCAFFOLD),
                "--name",
                "demo-flow",
                "--description",
                "Demo flow plugin",
                "--dest",
                str(self.dest),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.plugin = self.dest / "demo-flow"

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_claudegraph_identity_leaks(self):
        offenders = []
        for path in self.plugin.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            for lineno, line in enumerate(
                path.read_text(errors="replace").splitlines(), 1
            ):
                if any(a in line for a in ALLOWED_LINES):
                    continue
                for pat in LEAK_PATTERNS:
                    if pat.lower() in line.lower():
                        rel = path.relative_to(self.plugin)
                        offenders.append(f"{rel}:{lineno}: {line.strip()[:80]}")
        self.assertEqual(
            offenders, [], "leaked claudegraph internals:\n" + "\n".join(offenders)
        )

    def test_design_history_files_not_copied(self):
        for name in ("ROADMAP.md", "LEARNING_CHECKLIST.md"):
            self.assertFalse(
                (self.plugin / name).exists(), f"{name} should not be copied"
            )

    def test_generator_machinery_not_copied(self):
        for rel in (
            "scripts/scaffold_plugin.py",
            "commands/build-graph.md",
            "commands/graph-spec.md",
            "references",
            "templates",
        ):
            self.assertFalse(
                (self.plugin / rel).exists(), f"{rel} should not be copied"
            )

    def test_claude_md_is_a_symlink_to_fresh_agents_md(self):
        claude_md = self.plugin / "CLAUDE.md"
        self.assertTrue(
            claude_md.is_symlink(), "CLAUDE.md must be a symlink, not a copy"
        )
        # The bug this guards: copytree dereferences symlinks, so CLAUDE.md used
        # to arrive as a regular file holding the SOURCE plugin's AGENTS.md.
        self.assertIn("demo-flow", claude_md.read_text())

    def test_plugin_json_drops_inherited_identity(self):
        manifest = json.loads(
            (self.plugin / ".claude-plugin" / "plugin.json").read_text()
        )
        self.assertEqual(manifest["name"], "demo-flow")
        self.assertEqual(manifest["description"], "Demo flow plugin")
        for inherited in ("homepage", "repository", "keywords", "author"):
            self.assertNotIn(inherited, manifest)

    def test_generated_plugin_tests_pass(self):
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "scripts.test_demo_flow_skill"],
            cwd=self.plugin,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_runtime_artifacts_use_the_new_plugin_name(self):
        subprocess.run(
            [sys.executable, "scripts/demo_flow_skill.py"],
            cwd=self.plugin,
            input=json.dumps({"current_node": "explain", "data": {}}),
            capture_output=True,
            text=True,
        )
        self.assertTrue((self.plugin / "demo-flow_session.log.jsonl").exists())
        self.assertTrue((self.plugin / "demo-flow_session.checkpoint.json").exists())

    def test_refuses_to_overwrite_existing_destination(self):
        proc = subprocess.run(
            [
                sys.executable,
                str(SCAFFOLD),
                "--name",
                "demo-flow",
                "--description",
                "again",
                "--dest",
                str(self.dest),
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("already exists", proc.stderr)


if __name__ == "__main__":
    unittest.main()
