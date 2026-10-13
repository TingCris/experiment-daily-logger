from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOGGER = ROOT / "scripts" / "experiment_logger.py"


class LoggerCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.report = self.base / "reports"
        self.project.mkdir()
        self.env = os.environ.copy()
        self.env["EXPERIMENT_DAILY_REPORT_DIR"] = str(self.report)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_logger(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(LOGGER), *args],
            cwd=self.project,
            env=self.env,
            text=True,
            capture_output=True,
            check=check,
        )

    def records(self) -> list[dict]:
        result = self.run_logger("list", "--json")
        return json.loads(result.stdout)

    def test_successful_launch_becomes_completed(self) -> None:
        result_dir = self.project / "out"
        result_dir.mkdir()
        (result_dir / "metrics.json").write_text('{"accuracy": 0.9}', encoding="utf-8")
        result = self.run_logger(
            "launch", "--source", "codex", "--title", "smoke", "--purpose", "test lifecycle",
            "--changes", "no-op", "--baseline", "none", "--result-dir", "out",
            "--", sys.executable, "-c", "pass",
        )
        self.assertEqual(result.returncode, 0)
        record = self.records()[0]
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["exit_code"], 0)
        self.assertEqual(record["result_snapshots"][0]["file_count"], 1)
        markdown = next(self.report.glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("[已完成] smoke", markdown)
        self.assertIn("已完成 1", markdown)
        self.assertIn("结果：待登记", markdown)

    def test_failed_launch_records_exit_code(self) -> None:
        result = self.run_logger(
            "launch", "--title", "failure", "--result-dir", "out",
            "--", sys.executable, "-c", "raise SystemExit(3)",
            check=False,
        )
        self.assertEqual(result.returncode, 3)
        record = self.records()[0]
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["exit_code"], 3)

    def test_interrupted_exit_code_is_not_failed(self) -> None:
        result = self.run_logger(
            "launch", "--title", "interrupted", "--result-dir", "out",
            "--", sys.executable, "-c", "raise SystemExit(130)",
            check=False,
        )
        self.assertEqual(result.returncode, 130)
        record = self.records()[0]
        self.assertEqual(record["status"], "interrupted")
        markdown = next(self.report.glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("[已中止] interrupted", markdown)
        self.assertIn("已中止 1", markdown)

    def test_update_adds_evidence_and_discard_reason(self) -> None:
        evidence = self.project / "metrics.json"
        artifact = self.project / "predictions.jsonl"
        evidence.write_text('{"accuracy": 0.812}', encoding="utf-8")
        artifact.write_text('{}\n', encoding="utf-8")
        created = self.run_logger(
            "record", "--status", "unknown", "--title", "recovered", "--result-dir", "out",
            "--command", "python train.py",
        ).stdout.strip()
        self.run_logger(
            "update", created, "--status", "discarded", "--reason", "wrong split",
            "--metric", "accuracy=0.812", "--metric-source", f"accuracy={evidence}",
            "--artifact", str(artifact), "--conclusion", "not usable",
        )
        record = self.records()[0]
        self.assertEqual(record["status"], "discarded")
        self.assertEqual(record["metrics"][0]["source"], str(evidence))
        self.assertEqual(record["metrics"][0]["source_meta"]["size"], evidence.stat().st_size)
        self.assertEqual(record["artifacts"][0]["size"], artifact.stat().st_size)
        self.assertEqual(self.run_logger("verify", created).returncode, 0)
        evidence.write_text('{"accuracy": 0.999, "note": "changed"}', encoding="utf-8")
        changed = self.run_logger("verify", created, check=False)
        self.assertEqual(changed.returncode, 1)
        self.assertIn("证据文件大小在登记后发生变化", changed.stdout)
        markdown = next(self.report.glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("已丢弃 1", markdown)

    def test_compact_update_keeps_details_and_other_entries(self) -> None:
        first_id = self.run_logger(
            "record", "--title", "first", "--changes", "batch 16 -> 32; full validation set",
            "--baseline", "batch-16", "--command", "python train.py --batch-size 32",
        ).stdout.strip()
        second_id = self.run_logger(
            "record", "--title", "second", "--command", "python evaluate.py"
        ).stdout.strip()
        self.run_logger("update", first_id, "--status", "interrupted", "--reason", "wrong split")
        markdown = next(self.report.glob("*.md")).read_text(encoding="utf-8")
        first_block = markdown.split(f"<!-- experiment:{first_id} -->", 1)[1].split(
            f"<!-- /experiment:{first_id} -->", 1
        )[0]
        visible, details = first_block.split("<details>", 1)
        self.assertIn("[已中止] first", visible)
        self.assertIn("batch 16 -> 32; full validation set", visible)
        self.assertIn("batch-16", visible)
        self.assertIn("wrong split", visible)
        self.assertNotIn("目的", visible)
        self.assertNotIn("Git", visible)
        self.assertNotIn("python train.py", visible)
        self.assertIn("python train.py --batch-size 32", details)
        self.assertEqual(markdown.count(f"<!-- experiment:{first_id} -->"), 1)
        self.assertEqual(markdown.count(f"<!-- experiment:{second_id} -->"), 1)
        record = json.loads(self.run_logger("show", first_id, "--json").stdout)
        self.assertEqual(record["command"], "python train.py --batch-size 32")
        self.assertEqual(record["status"], "interrupted")
        self.assertIn("git", record)
        self.assertIn("events", record)

    def test_reconcile_never_guesses_completion(self) -> None:
        created = self.run_logger(
            "record", "--status", "running", "--title", "lost", "--command", "python train.py"
        ).stdout.strip()
        result = self.run_logger("reconcile")
        self.assertIn("reconciled=1", result.stdout)
        record = self.records()[0]
        self.assertEqual(record["status"], "unknown")
        self.assertIn("无法可靠判断", record["status_reason"])


if __name__ == "__main__":
    unittest.main()
