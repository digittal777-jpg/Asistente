import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.doctor import RaphelDoctor
from core.p1_validation import P1LiveValidator
from VALIDATION_P1_LIVE import build_parser


class FakeConfig:
    def get(self, key, default=None):
        if key == "browser_paths":
            return {"brave": [], "chrome": [], "edge": []}
        if key == "applications":
            return {"word": {}, "visual studio code": {}}
        return default


class FakeAssistant:
    def __init__(self):
        self.config = FakeConfig()
        self.commands = []
        self.shutdown_called = False
        self._confirmation_provider = None

    def handle_command(self, command):
        self.commands.append(command)
        responses = {
            "learning-status": "Aprendizaje inteligente:\n- ok",
            "skill-status investigar": "Habilidad: Investigar\n- Uso real listo: no\n- Tendencia actual: estancado",
            "skill-status youtube": "Habilidad: Usar YouTube\n- Uso real listo: si",
            "skill-status word": "Habilidad: Usar Word\n- Uso real listo: no",
            "skill-status mouse": "Habilidad: Usar raton\n- Uso real listo: si",
            "input-training-status": "Entrenamiento continuo autonomo: detenido.",
            "skill-practice investigar 1 intento": "research :: status=failure verified=no",
            "skill-practice youtube 1 intento": "youtube :: status=success verified=yes",
            "skill-practice word 1 intento": "word :: status=failure verified=no",
            "skill-practice teclado 1 intento": "keyboard :: status=failure verified=no",
            "desktop-organize": "desktop :: status=success verified=yes",
            "desktop-practice-mouse-workflow 1": "Practica completada. Exitos: 1. Fallos: 0. Tasa: 100%",
        }
        return responses[command]

    def set_confirmation_provider(self, callback):
        self._confirmation_provider = callback

    def shutdown(self):
        self.shutdown_called = True


class DoctorAndP1ValidationTests(unittest.TestCase):
    def test_doctor_writes_json_report_without_secret_values(self):
        with TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            (base_dir / "config").mkdir()
            (base_dir / "logs").mkdir()
            (base_dir / "data").mkdir()
            (base_dir / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
            (base_dir / "requirements.txt").write_text("pytest\n", encoding="utf-8")
            (base_dir / "README.md").write_text("# Test\n", encoding="utf-8")
            (base_dir / "config" / "settings.json").write_text("{}", encoding="utf-8")
            (base_dir / "data" / "action_history.jsonl").write_text(
                json.dumps({"response": "http://127.0.0.1:8765/?token=secret-value"}) + "\n",
                encoding="utf-8",
            )

            doctor = RaphelDoctor(base_dir, config=FakeConfig())
            report = doctor.run()
            output_path = doctor.write_report(report)

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["project_root"], str(base_dir))
            remote_check = next(check for check in payload["checks"] if check["name"] == "remote_console_history")
            self.assertEqual(remote_check["status"], "warning")
            self.assertEqual(remote_check["data"]["possible_secret_lines"], 1)
            self.assertNotIn("secret-value", doctor.format_report(report, output_path))

    def test_p1_snapshot_does_not_shutdown_injected_assistant(self):
        with TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            (base_dir / "config").mkdir()
            (base_dir / "logs").mkdir()
            (base_dir / "data").mkdir()
            (base_dir / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
            (base_dir / "requirements.txt").write_text("pytest\n", encoding="utf-8")
            (base_dir / "README.md").write_text("# Test\n", encoding="utf-8")
            (base_dir / "config" / "settings.json").write_text("{}", encoding="utf-8")
            assistant = FakeAssistant()
            validator = P1LiveValidator(base_dir, assistant_factory=lambda: assistant)

            report = validator.run(execute_live=False)
            step_names = {step.name for step in report.steps}
            word_step = next(step for step in report.steps if step.name == "word_status")

            self.assertIn("live_attempts", step_names)
            self.assertIn("skill-status investigar", assistant.commands)
            self.assertFalse(assistant.shutdown_called)
            self.assertEqual(report.mode, "guided_snapshot")
            self.assertEqual(word_step.status, "warning")

    def test_p1_execute_live_runs_target_commands(self):
        with TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            (base_dir / "config").mkdir()
            (base_dir / "logs").mkdir()
            (base_dir / "data").mkdir()
            (base_dir / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
            (base_dir / "requirements.txt").write_text("pytest\n", encoding="utf-8")
            (base_dir / "README.md").write_text("# Test\n", encoding="utf-8")
            (base_dir / "config" / "settings.json").write_text("{}", encoding="utf-8")
            assistant = FakeAssistant()
            validator = P1LiveValidator(base_dir, assistant_factory=lambda: assistant)

            report = validator.run(execute_live=True)

            self.assertIn("skill-practice investigar 1 intento", assistant.commands)
            self.assertIn("skill-practice teclado 1 intento", assistant.commands)
            self.assertIn("desktop-organize", assistant.commands)
            self.assertIn("desktop-practice-mouse-workflow 1", assistant.commands)
            self.assertEqual(report.mode, "execute_live")

    def test_supervised_p1_mode_writes_detailed_report(self):
        with TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            (base_dir / "config").mkdir()
            (base_dir / "logs").mkdir()
            (base_dir / "data").mkdir()
            (base_dir / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
            (base_dir / "requirements.txt").write_text("pytest\n", encoding="utf-8")
            (base_dir / "README.md").write_text("# Test\n", encoding="utf-8")
            (base_dir / "config" / "settings.json").write_text("{}", encoding="utf-8")
            assistant = FakeAssistant()
            validator = P1LiveValidator(base_dir, assistant_factory=lambda: assistant)

            report = validator.run(execute_live=True, supervised=True)
            output_path = base_dir / "logs" / "p1_supervised_training.json"

            self.assertEqual(report.mode, "supervised_p1")
            self.assertTrue(output_path.exists())
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIn("research", payload["steps"])
            self.assertIn("word", payload["steps"])
            self.assertIn("keyboard", payload["steps"])
            self.assertIn("desktop_organize", payload["steps"])

    def test_validation_p1_live_cli_accepts_supervised_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--supervised"])
        self.assertTrue(args.supervised)


if __name__ == "__main__":
    unittest.main()
