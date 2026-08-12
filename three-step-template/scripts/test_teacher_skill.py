"""Stdlib-only tests. Run: python3 -m unittest scripts.test_teacher_skill -v"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent)
)  # so `import graph` works when run as scripts.test_teacher_skill
from graph import load_checkpoint

SCRIPT = Path(__file__).parent / "teacher_skill.py"


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
