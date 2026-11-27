import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


HARNESS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS_DIR))

import evaluation_runner
from model_registry import MODEL_REGISTRY


class EvaluationHarnessTests(unittest.TestCase):
    def test_spec_prompts_and_schemas_exist_and_parse(self):
        spec_path = HARNESS_DIR / "track_a_benchmark_spec.json"
        manifest_path = HARNESS_DIR / "track_a_dataset_manifest.json"
        snapshot_manifest_path = HARNESS_DIR / "snapshot_manifest.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        json.loads(manifest_path.read_text(encoding="utf-8"))
        json.loads(snapshot_manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(len(spec["tasks"]), 5)
        for task in spec["tasks"]:
            prompt_path = HARNESS_DIR / task["prompt"]
            schema_path = HARNESS_DIR / task["schema"]
            self.assertTrue(prompt_path.is_file(), task["prompt"])
            self.assertTrue(schema_path.is_file(), task["schema"])
            prompt = prompt_path.read_text(encoding="utf-8")
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            self.assertEqual(prompt.count("{evidence_json}"), 1)
            self.assertIsInstance(schema, dict)

        catalogue = json.loads(
            (HARNESS_DIR / "schemas" / "approved_action_catalogue.json")
            .read_text(encoding="utf-8")
        )
        self.assertIsInstance(catalogue, dict)

    def test_registry_entries_are_loadable_and_cli_choices_are_dynamic(self):
        self.assertIn("ministral3_8b", MODEL_REGISTRY)
        for config in MODEL_REGISTRY.values():
            self.assertTrue(config["model_id"])
            self.assertIn(config["loader"], {"causal", "multimodal"})

        result = subprocess.run(
            [sys.executable, str(HARNESS_DIR / "evaluation_runner.py"), "--help"],
            cwd=HARNESS_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
        for model_key in MODEL_REGISTRY:
            self.assertIn(model_key, result.stdout)
        self.assertNotIn("--skip-freeze-check", result.stdout)

    def test_prompts_are_common_and_hashes_match_assets(self):
        spec = json.loads(
            (HARNESS_DIR / "track_a_benchmark_spec.json")
            .read_text(encoding="utf-8")
        )
        tasks = evaluation_runner.prepare_tasks(spec["tasks"])
        hashes = evaluation_runner.task_prompt_hashes(tasks)
        snapshot = {
            "case": {"Case_ID": "CASE_TEST"},
            "evidence": [{"Transaction_ID": "TX_TEST"}],
        }

        self.assertEqual(
            evaluation_runner.OFFICIAL_PROMPT_MODE,
            "official_common",
        )
        self.assertEqual(set(hashes), {task["name"] for task in tasks})
        for task in tasks:
            prompt_hashes = hashes[task["name"]]
            self.assertEqual(
                prompt_hashes["prompt_sha256"],
                evaluation_runner.sha256_file(Path(task["prompt_path"])),
            )
            self.assertEqual(
                prompt_hashes["schema_sha256"],
                evaluation_runner.sha256_file(Path(task["schema_path"])),
            )
            rendered = {
                evaluation_runner.build_prompt(
                    task["template"], snapshot, task["schema"]
                )
                for _model_key in MODEL_REGISTRY
            }
            self.assertEqual(len(rendered), 1)

    def test_prompt_builder_never_receives_ground_truth(self):
        template = "Assess the case: {evidence_json}"
        snapshot = {
            "case": {"Case_ID": "CASE_TEST"},
            "evidence": [{"Transaction_ID": "TX_TEST"}],
        }
        prompt = evaluation_runner.build_prompt(template, snapshot, {})
        self.assertIn("CASE_TEST", prompt)
        self.assertNotIn("Scenario_ID", prompt)
        self.assertNotIn("Fraud_type", prompt)
        self.assertNotIn("Validation_notes", prompt)

    def test_missing_private_data_is_reported_before_any_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "track_a_dataset_manifest.json").write_text(
                json.dumps({"snapshot_sha256": {"CASE_TEST.json": "0" * 64}}),
                encoding="utf-8",
            )
            (root / "snapshots").mkdir()
            with patch.object(evaluation_runner, "HARNESS_DIR", root):
                mismatches = evaluation_runner.verify_dataset_freeze()

        self.assertIn("missing:CASE_TEST.json", mismatches)
        self.assertIn(
            "missing:ground_truth/Ground_Truth.csv",
            mismatches,
        )

    def test_cli_reports_missing_private_data_clearly(self):
        result = subprocess.run(
            [
                sys.executable,
                str(HARNESS_DIR / "evaluation_runner.py"),
                "--mode",
                "smoke",
                "--models",
                "qwen3_1_7b",
            ],
            cwd=HARNESS_DIR,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertEqual(report["error"], "dataset freeze mismatch")
        self.assertIn("missing:snapshots directory", report["mismatches"])
        self.assertIn(
            "missing:ground_truth/Ground_Truth.csv",
            report["mismatches"],
        )

    def test_dataset_hash_mismatches_are_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshots = root / "snapshots"
            ground_truth = root / "ground_truth"
            snapshots.mkdir()
            ground_truth.mkdir()
            (snapshots / "CASE_TEST.json").write_text(
                '{"case":"changed"}', encoding="utf-8"
            )
            (ground_truth / "Ground_Truth.csv").write_text(
                "Case_ID\nCASE_TEST\n", encoding="utf-8"
            )
            manifest = {
                "snapshot_sha256": {
                    "CASE_TEST.json": hashlib.sha256(
                        b'{"case":"expected"}'
                    ).hexdigest()
                },
                "ground_truth_sha256": hashlib.sha256(
                    b"Case_ID\nEXPECTED\n"
                ).hexdigest(),
            }
            (root / "track_a_dataset_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            with patch.object(evaluation_runner, "HARNESS_DIR", root):
                mismatches = evaluation_runner.verify_dataset_freeze()

        self.assertIn("changed:CASE_TEST.json", mismatches)
        self.assertIn("ground_truth:changed", mismatches)


if __name__ == "__main__":
    unittest.main()
