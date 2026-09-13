import random
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.assistant import RaphelAssistant


class AssistantInputTrainingTests(unittest.TestCase):
    def test_input_training_cycle_includes_full_autonomous_curriculum(self):
        assistant = RaphelAssistant.__new__(RaphelAssistant)
        assistant._input_training_rng = random.Random(7)
        assistant.learning_skill_engine = type(
            "LearningState",
            (),
            {
                "state": {
                    "profiles": {
                        "skill:mouse": {"current_level": 1},
                        "skill:visualizacion": {"current_level": 1},
                        "skill:teclado": {"current_level": 1},
                        "skill:investigar": {"current_level": 1},
                        "skill:window_management": {"current_level": 1},
                        "skill:youtube": {"current_level": 1},
                    }
                }
            },
        )()

        steps = assistant._build_input_training_cycle_steps(
            cycle_number=1,
            mouse_attempts=6,
            keyboard_attempts=6,
        )
        labels = {label for label, _runner in steps}

        self.assertEqual(len(steps), 12)
        self.assertEqual(
            labels,
            {
                "acomodo de ventanas",
                "interpretacion audiovisual youtube",
                "investigar",
                "mouse movimiento",
                "mouse click",
                "mouse doble click",
                "mouse click derecho",
                "mouse drag",
                "mouse flujo",
                "teclado",
                "visualizacion",
                "youtube",
            },
        )

    def test_input_training_retry_detection_flags_loop_failure_summary(self):
        self.assertTrue(
            RaphelAssistant._input_training_result_needs_retry(
                "research :: skill:investigar :: research_single_source :: status=failure verified=no"
            )
        )

    def test_input_training_retry_detection_ignores_zero_failures(self):
        self.assertFalse(
            RaphelAssistant._input_training_result_needs_retry(
                "Practica completada. Exitos: 6. Fallos: 0. Tasa: 100%"
            )
        )

    def test_input_training_retry_detection_flags_failures_and_low_rate(self):
        self.assertTrue(
            RaphelAssistant._input_training_result_needs_retry(
                "Practica completada. Exitos: 5. Fallos: 1. Tasa: 83%"
            )
        )
        self.assertTrue(
            RaphelAssistant._input_training_result_needs_retry(
                "Practica completada. Exitos: 4. Fallos: 0. Tasa: 80%"
            )
        )

    def test_input_training_step_omits_blocked_domain_without_stopping_loop(self):
        assistant = RaphelAssistant.__new__(RaphelAssistant)
        warnings = []
        assistant.emit_status = lambda message, level="info": warnings.append((message, level))

        def blocked_runner():
            raise RuntimeError(
                "El dominio perception no esta disponible ahora: "
                "todas las habilidades del dominio estan bloqueadas"
            )

        results = assistant._run_input_training_step_with_retry(
            "visualizacion",
            blocked_runner,
            3,
        )

        self.assertEqual(len(results), 1)
        self.assertIn("visualizacion=visualizacion omitido:", results[0])
        self.assertIn("perception no esta disponible", results[0])
        self.assertEqual(warnings[-1][1], "warning")

    def test_input_training_retry_omits_step_when_skill_blocks_after_failure(self):
        assistant = RaphelAssistant.__new__(RaphelAssistant)
        assistant._input_training_stop_event = threading.Event()
        assistant._input_training_stop_path = Path("missing-input-training-stop.flag")
        assistant._input_training_thread = threading.current_thread()
        assistant._input_training_hotkey_stop_requested = lambda: False
        assistant._sleep_input_training_pause = lambda _seconds: None
        assistant.emit_status = lambda _message, _level="info": None

        calls = {"count": 0}

        def runner():
            calls["count"] += 1
            if calls["count"] == 1:
                return "perception :: skill:visualizacion :: visual_context_identity :: status=failure verified=no"
            raise RuntimeError(
                "El dominio perception no esta disponible ahora: "
                "todas las habilidades del dominio estan bloqueadas"
            )

        results = assistant._run_input_training_step_with_retry(
            "visualizacion",
            runner,
            1,
        )

        self.assertEqual(calls["count"], 2)
        self.assertEqual(len(results), 2)
        self.assertIn("status=failure", results[0])
        self.assertIn("visualizacion reintento 1=visualizacion omitido:", results[1])

    def test_stale_stop_file_does_not_stop_manual_practice(self):
        with TemporaryDirectory() as temp_dir:
            assistant = RaphelAssistant.__new__(RaphelAssistant)
            assistant._input_training_stop_event = threading.Event()
            assistant._input_training_thread = None
            assistant._input_training_stop_path = Path(temp_dir) / "input_training_loop.stop"
            assistant._input_training_stop_path.write_text("stale", encoding="utf-8")

            self.assertFalse(assistant.input_training_stop_requested())

    def test_hotkey_stop_sets_stop_event(self):
        with TemporaryDirectory() as temp_dir:
            assistant = RaphelAssistant.__new__(RaphelAssistant)
            assistant._input_training_stop_event = threading.Event()
            assistant._input_training_thread = threading.current_thread()
            assistant._input_training_stop_path = Path(temp_dir) / "input_training_loop.stop"
            assistant._input_training_last_result = "corriendo"
            assistant._input_training_hotkey_stop_requested = lambda: True
            assistant.emit_status = lambda _message, _level="info": None

            self.assertTrue(assistant._input_training_should_stop())
            self.assertTrue(assistant._input_training_stop_event.is_set())
            self.assertTrue(assistant._input_training_stop_path.exists())
            self.assertIn("atajo de emergencia", assistant._input_training_last_result)

    def test_start_input_training_loop_initializes_background_thread(self):
        with TemporaryDirectory() as temp_dir:
            assistant = RaphelAssistant.__new__(RaphelAssistant)
            assistant.infinite_training_loop = type(
                "Loop",
                (),
                {"configure_budgets": lambda self, **_kwargs: None},
            )()
            assistant._input_training_lock = threading.Lock()
            assistant._input_training_thread = None
            assistant._input_training_stop_event = threading.Event()
            assistant._input_training_stop_path = Path(temp_dir) / "input_training_loop.stop"
            assistant._input_training_cycle_count = 99
            assistant._input_training_last_result = "viejo"
            assistant._run_input_training_loop = lambda *_args: None

            result = assistant.start_input_training_loop(mouse_attempts=2, keyboard_attempts=3, pause_seconds=1.0)

            self.assertIn("iniciado", result)
            self.assertIsNotNone(assistant._input_training_thread)
            assistant._input_training_thread.join(timeout=1.0)
            self.assertFalse(assistant._input_training_thread.is_alive())
            self.assertEqual(assistant._input_training_cycle_count, 0)
            self.assertEqual(assistant._input_training_last_result, "iniciando")


if __name__ == "__main__":
    unittest.main()
