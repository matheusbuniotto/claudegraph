"""Stdlib-only tests. Run: python3 -m unittest scripts.test_template_skill -v"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent)
)  # so `import graph` works when run as scripts.test_template_skill
from graph import load_checkpoint
from template_skill import SKILL_NAME

SCRIPT = Path(__file__).parent / "template_skill.py"


class TeacherSkillTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log_path = Path(self._tmp.name) / "test_session.log.jsonl"
        self.checkpoint_path = Path(self._tmp.name) / "test_session.checkpoint.json"

    def tearDown(self):
        self._tmp.cleanup()

    def run_skill(self, payload: dict) -> subprocess.CompletedProcess:
        full_payload = {
            **payload,
            "log_path": str(self.log_path),
            "checkpoint_path": str(self.checkpoint_path),
        }
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(full_payload),
            capture_output=True,
            text=True,
        )

    def test_linear_step_explain_to_demonstrate(self):
        result = self.run_skill(
            {"current_node": "explain", "data": {}, "retry_count": 0, "max_retries": 2}
        )
        out = json.loads(result.stdout)
        self.assertEqual(out["next_node"], "demonstrate")
        self.assertEqual(out["kind"], "task")

    def test_banner_names_node_and_goal(self):
        out = json.loads(self.run_skill({"current_node": "explain", "data": {}}).stdout)
        banner = out["banner"]
        self.assertIn("demonstrate", banner)  # the node about to run
        self.assertIn(out["goal"], banner)  # why it's running
        self.assertTrue(banner.startswith("▶"))  # task marker

    def test_banner_marks_human_gate_and_end_differently(self):
        gate = json.loads(
            self.run_skill({"current_node": "demonstrate", "data": {}}).stdout
        )
        self.assertTrue(gate["banner"].startswith("⏸"), gate["banner"])

        end = json.loads(
            self.run_skill(
                {"current_node": "check", "data": {"understood": True}}
            ).stdout
        )
        self.assertTrue(end["banner"].startswith("■"), end["banner"])

    def test_banner_shows_retry_count_only_when_retrying(self):
        first = json.loads(
            self.run_skill({"current_node": "explain", "data": {}}).stdout
        )
        self.assertNotIn("retry", first["banner"])

        looped = json.loads(
            self.run_skill(
                {"current_node": "check", "data": {"understood": False}}
            ).stdout
        )
        self.assertIn("retry 1/2", looped["banner"])

    def test_check_node_exposes_human_gate_kind(self):
        result = self.run_skill(
            {
                "current_node": "demonstrate",
                "data": {},
                "retry_count": 0,
                "max_retries": 2,
            }
        )
        out = json.loads(result.stdout)
        self.assertEqual(out["next_node"], "check")
        self.assertEqual(out["kind"], "human_gate")

    def test_step_appends_evidence_to_log(self):
        self.run_skill(
            {"current_node": "explain", "data": {}, "retry_count": 0, "max_retries": 2}
        )
        lines = self.log_path.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["from"], "explain")
        self.assertEqual(entry["to"], "demonstrate")
        self.assertIn("ts", entry)

        self.run_skill(
            {
                "current_node": "demonstrate",
                "data": {},
                "retry_count": 0,
                "max_retries": 2,
            }
        )
        self.assertEqual(
            len(self.log_path.read_text().splitlines()), 2
        )  # appended, not overwritten

    def run_skill_with_defaults(self, payload: dict) -> subprocess.CompletedProcess:
        """Like run_skill, but doesn't override log_path/checkpoint_path — exercises
        the run_id-based default paths, scoped to a throwaway cwd."""
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(payload),
            cwd=self._tmp.name,
            capture_output=True,
            text=True,
        )

    def test_run_id_generated_and_scopes_default_paths(self):
        out = json.loads(
            self.run_skill_with_defaults({"current_node": "explain", "data": {}}).stdout
        )
        self.assertIn("run_id", out)
        run_dir = Path(self._tmp.name) / "runs" / out["run_id"]
        self.assertTrue((run_dir / f"{SKILL_NAME}.log.jsonl").exists())
        self.assertTrue((run_dir / f"{SKILL_NAME}.checkpoint.json").exists())

    def test_runs_latest_recovers_a_dropped_run_id(self):
        first = json.loads(
            self.run_skill_with_defaults({"current_node": "explain", "data": {}}).stdout
        )
        latest = Path(self._tmp.name) / "runs" / "latest"
        self.assertTrue(latest.is_symlink())
        self.assertEqual(latest.resolve().name, first["run_id"])

        checkpoint = load_checkpoint(latest / f"{SKILL_NAME}.checkpoint.json")
        self.assertEqual(checkpoint.current_node, "explain")  # recovered, not guessed

        second = json.loads(
            self.run_skill_with_defaults(
                {
                    "current_node": checkpoint.current_node,
                    "data": {},
                    "run_id": first["run_id"],  # as if read via readlink runs/latest
                }
            ).stdout
        )
        self.assertEqual(second["run_id"], first["run_id"])  # same run, not a new fork

    def test_explicit_paths_skip_runs_latest(self):
        self.run_skill_with_defaults(
            {
                "current_node": "explain",
                "data": {},
                "log_path": str(self.log_path),
                "checkpoint_path": str(self.checkpoint_path),
            }
        )
        self.assertTrue(self.log_path.exists())  # explicit paths still honored
        self.assertFalse(
            (Path(self._tmp.name) / "runs").exists()
        )  # no runs/ side effect

    def test_run_id_carried_forward_reuses_same_run_dir(self):
        first = json.loads(
            self.run_skill_with_defaults({"current_node": "explain", "data": {}}).stdout
        )
        second = json.loads(
            self.run_skill_with_defaults(
                {
                    "current_node": "demonstrate",
                    "data": {},
                    "retry_count": first["retry_count"],
                    "step_count": first["step_count"],
                    "run_id": first["run_id"],
                }
            ).stdout
        )
        self.assertEqual(second["run_id"], first["run_id"])
        log_lines = (
            (
                Path(self._tmp.name)
                / "runs"
                / first["run_id"]
                / f"{SKILL_NAME}.log.jsonl"
            )
            .read_text()
            .splitlines()
        )
        self.assertEqual(len(log_lines), 2)  # both calls landed in the same run dir

    def test_actions_logged_but_not_checkpointed(self):
        self.run_skill(
            {
                "current_node": "explain",
                "data": {},
                "retry_count": 0,
                "max_retries": 2,
                "actions": [{"tool": "Read", "target": "spec.md"}],
            }
        )
        entry = json.loads(self.log_path.read_text().splitlines()[0])
        self.assertEqual(entry["actions"], [{"tool": "Read", "target": "spec.md"}])

        checkpoint = load_checkpoint(self.checkpoint_path)
        self.assertEqual(
            checkpoint.data, {}
        )  # actions never leak into State/checkpoint

    def test_actions_default_to_empty_list(self):
        self.run_skill(
            {"current_node": "explain", "data": {}, "retry_count": 0, "max_retries": 2}
        )
        entry = json.loads(self.log_path.read_text().splitlines()[0])
        self.assertEqual(entry["actions"], [])

    def test_checkpoint_round_trip(self):
        self.run_skill(
            {
                "current_node": "check",
                "data": {"understood": False},
                "retry_count": 0,
                "max_retries": 2,
            }
        )
        checkpoint = load_checkpoint(self.checkpoint_path)
        self.assertEqual(checkpoint.current_node, "check")
        self.assertEqual(checkpoint.retry_count, 1)  # on_transition already applied
        self.assertEqual(checkpoint.data, {"understood": False})

    def test_step_budget_exceeded_fails_cleanly(self):
        proc = self.run_skill(
            {"current_node": "explain", "data": {}, "step_count": 5, "max_steps": 5}
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("error", json.loads(proc.stderr))

    def test_check_not_understood_loops_and_increments_retry(self):
        result = self.run_skill(
            {
                "current_node": "check",
                "data": {"understood": False},
                "retry_count": 0,
                "max_retries": 2,
            }
        )
        out = json.loads(result.stdout)
        self.assertEqual(out["next_node"], "explain")
        self.assertEqual(out["retry_count"], 1)
        self.assertFalse(out["done"])

    def test_check_retries_exhausted_ends(self):
        result = self.run_skill(
            {
                "current_node": "check",
                "data": {"understood": False},
                "retry_count": 2,
                "max_retries": 2,
            }
        )
        out = json.loads(result.stdout)
        self.assertEqual(out["next_node"], "end")
        self.assertTrue(out["done"])
        self.assertGreaterEqual(
            out["retry_count"], out["max_retries"]
        )  # exhausted, not success

    def test_check_understood_ends_below_max(self):
        result = self.run_skill(
            {
                "current_node": "check",
                "data": {"understood": True},
                "retry_count": 1,
                "max_retries": 2,
            }
        )
        out = json.loads(result.stdout)
        self.assertEqual(out["next_node"], "end")
        self.assertLess(
            out["retry_count"], out["max_retries"]
        )  # success, not exhausted

    def test_malformed_json_fails_cleanly(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input="not json",
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("error", json.loads(proc.stderr))

    def test_missing_required_key_fails_cleanly(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)], input="{}", capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("error", json.loads(proc.stderr))


if __name__ == "__main__":
    unittest.main()
