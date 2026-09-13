import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.data_cleanup import CleanupExecutor, CleanupPlanner
from core.data_paths import DataPaths


class DataCleanupTests(unittest.TestCase):
    def test_runtime_resolution_prefers_legacy_until_canonical_exists(self):
        with TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            paths = DataPaths.from_base_dir(base_dir)
            paths.ensure_base_structure()
            paths.legacy_infinite_training_history_path.write_text("legacy\n", encoding="utf-8")

            self.assertEqual(
                paths.resolve_runtime_path("infinite_training_history"),
                paths.legacy_infinite_training_history_path,
            )

            paths.infinite_training_history_path.write_text("runtime\n", encoding="utf-8")
            self.assertEqual(
                paths.resolve_runtime_path("infinite_training_history"),
                paths.infinite_training_history_path,
            )

    def test_planner_classifies_keep_archive_quarantine_and_regenerate(self):
        with TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            paths = DataPaths.from_base_dir(base_dir)
            paths.ensure_base_structure()

            paths.learning_profiles_path.write_text("{}", encoding="utf-8")
            backup_path = paths.data_dir / "learning_skill_profiles.before_manual_cleanup_20260516.json"
            backup_path.write_text("{}", encoding="utf-8")
            smoke_path = paths.runtime_smoke_dir / "smoke.txt"
            smoke_path.parent.mkdir(parents=True, exist_ok=True)
            smoke_path.write_text("smoke", encoding="utf-8")
            legacy_history = paths.legacy_infinite_training_history_path
            legacy_history.write_text('{"ok": true}\n', encoding="utf-8")

            session_doc = paths.learning_sessions_dir / "session_a" / "keyboard_saved_note.txt"
            session_doc.parent.mkdir(parents=True, exist_ok=True)
            session_doc.write_text("nota", encoding="utf-8")
            manifest = {
                "session_id": "session_a",
                "manifest_path": str(paths.learning_sessions_dir / "session_a.json"),
                "document_path": str(session_doc),
            }
            (paths.learning_sessions_dir / "session_a.json").write_text(
                json.dumps(manifest, ensure_ascii=False),
                encoding="utf-8",
            )
            orphan_doc = paths.learning_sessions_dir / "session_b" / "orphan.txt"
            orphan_doc.parent.mkdir(parents=True, exist_ok=True)
            orphan_doc.write_text("orphan", encoding="utf-8")
            corrupt_manifest = paths.learning_sessions_dir / "broken.json"
            corrupt_manifest.write_text("{broken", encoding="utf-8")

            workflow_manifest = paths.organizer_sessions_dir / "workflow_practice_1.json"
            workflow_manifest.write_text(json.dumps({"session_id": "workflow_practice_1"}), encoding="utf-8")
            stale_practice = paths.organizer_sessions_dir / "mouse_click_practice_old.json"
            stale_practice.write_text(json.dumps({"session_id": "mouse_click_practice_old"}), encoding="utf-8")
            latest_pointer = paths.organizer_sessions_dir / "latest.json"
            latest_pointer.write_text(
                json.dumps({"session_id": "workflow_practice_1", "manifest_path": str(workflow_manifest)}),
                encoding="utf-8",
            )

            planner = CleanupPlanner(paths)
            plan = planner.build_plan()
            actions = {item.relative_path: item.action for item in plan.decisions}

            self.assertEqual(actions["learning_skill_profiles.json"], "keep")
            self.assertEqual(actions[backup_path.relative_to(paths.data_dir).as_posix()], "archive")
            self.assertEqual(actions[smoke_path.relative_to(paths.data_dir).as_posix()], "archive")
            self.assertEqual(actions[legacy_history.relative_to(paths.data_dir).as_posix()], "regenerate")
            self.assertEqual(actions["learning_skill_sessions/session_a.json"], "keep")
            self.assertEqual(actions[session_doc.relative_to(paths.data_dir).as_posix()], "keep")
            self.assertEqual(actions[orphan_doc.relative_to(paths.data_dir).as_posix()], "archive")
            self.assertEqual(actions["learning_skill_sessions/broken.json"], "quarantine")
            self.assertEqual(actions["desktop_organizer_sessions/workflow_practice_1.json"], "keep")
            self.assertEqual(actions["desktop_organizer_sessions/mouse_click_practice_old.json"], "archive")

    def test_executor_creates_snapshot_and_moves_files(self):
        with TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            paths = DataPaths.from_base_dir(base_dir)
            paths.ensure_base_structure()

            paths.learning_profiles_path.write_text("{}", encoding="utf-8")
            legacy_dataset = paths.legacy_runtime_training_dataset_path
            legacy_dataset.write_text("dataset\n", encoding="utf-8")
            orphan_doc = paths.learning_sessions_dir / "session_c" / "orphan.txt"
            orphan_doc.parent.mkdir(parents=True, exist_ok=True)
            orphan_doc.write_text("orphan", encoding="utf-8")

            planner = CleanupPlanner(paths)
            plan = planner.build_plan()
            executor = CleanupExecutor(paths)
            report = executor.execute(plan)

            snapshot_dir = Path(report["snapshot_dir"])
            self.assertTrue((snapshot_dir / "learning_skill_profiles.json").exists())
            self.assertTrue((snapshot_dir / "runtime_training_dataset.jsonl").exists())
            self.assertTrue(paths.runtime_training_dataset_path.exists())
            self.assertFalse(legacy_dataset.exists())
            self.assertFalse(orphan_doc.exists())

            archived_relpaths = {
                item["relative_path"]
                for item in report["archived"]
            }
            regenerated_relpaths = {
                item["relative_path"]
                for item in report["regenerated"]
            }
            self.assertIn("learning_skill_sessions/session_c/orphan.txt", archived_relpaths)
            self.assertIn("runtime_training_dataset.jsonl", regenerated_relpaths)
            self.assertTrue(Path(report["report_path"]).exists())


if __name__ == "__main__":
    unittest.main()
