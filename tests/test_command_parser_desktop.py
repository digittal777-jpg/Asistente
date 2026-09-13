from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.command_parser import CommandParser


class FakeSkillManager:
    def find_skill_by_trigger(self, _command):
        return None


class FakeConfig:
    def get(self, key, default=None):
        if key == "applications":
            return {
                "word": {"aliases": ["microsoft word"]},
                "brave": {"aliases": ["brave browser"]},
                "explorer": {"aliases": ["explorador", "explorador de archivos"]},
            }
        if key == "url_aliases":
            return {
                "google": "https://www.google.com",
                "youtube": "https://www.youtube.com",
            }
        return default


class CommandParserDesktopTests(unittest.TestCase):
    def build_parser(self) -> CommandParser:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        return CommandParser(Path(self.temp_dir.name), FakeConfig(), FakeSkillManager())

    def test_organize_desktop_defaults_to_visible_learning(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("ordena mi escritorio")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "organize_desktop")
        self.assertEqual(step.params["execution_mode"], "ui_learning")
        self.assertTrue(step.requires_confirmation)

    def test_organize_desktop_fast_requests_legacy_mode(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("ordena mi escritorio rapido")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "organize_desktop")
        self.assertEqual(step.params["execution_mode"], "legacy_filesystem")

    def test_arrange_desktop_icons_is_not_file_organization(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("ordename los iconos del escritorio")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "arrange_desktop_icons")
        self.assertEqual(step.params["sort_by"], "name")
        self.assertTrue(step.requires_confirmation)

    def test_practice_mouse_is_safe_training_command(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("practica el mouse en el escritorio 100 veces")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "practice_desktop_mouse")
        self.assertEqual(step.params["attempts"], 100)
        self.assertTrue(step.requires_confirmation)

    def test_practice_mouse_movement_is_first_skill(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("practica mover el mouse 100 veces")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "practice_mouse_movement")
        self.assertEqual(step.params["attempts"], 100)
        self.assertTrue(step.requires_confirmation)

    def test_practice_click_skills_are_separate(self):
        parser = self.build_parser()
        cases = [
            ("practica click simple 100 veces", "practice_mouse_click"),
            ("practica doble click 100 veces", "practice_mouse_double_click"),
            ("practica click derecho 100 veces", "practice_mouse_right_click"),
            ("practica seleccion visual 100 veces", "practice_mouse_selection"),
            ("practica deteccion visual 100 veces", "practice_mouse_detection"),
            ("practica flujo completo seguro 100 veces", "practice_mouse_workflow"),
        ]

        for command, action in cases:
            with self.subTest(command=command):
                interpretation = parser.interpret_command(command)
                self.assertEqual(len(interpretation.steps), 1)
                step = interpretation.steps[0]
                self.assertEqual(step.action, action)
                self.assertEqual(step.params["attempts"], 100)
                self.assertTrue(step.requires_confirmation)

    def test_undo_last_desktop_organization(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("deshacer ordenado del escritorio")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "desktop_undo_last")
        self.assertTrue(step.requires_confirmation)

    def test_learn_keyboard_routes_to_learning_engine(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("aprende a usar el teclado")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "learn_skill")
        self.assertIn("teclado", step.params["skill"].lower())

    def test_learn_research_does_not_fall_into_old_complex_task(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("aprende a investigar")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "learn_skill")
        self.assertNotEqual(step.action, "execute_complex_task")

    def test_learn_visualizacion_routes_to_learning_engine(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("aprende visualizacion")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "learn_skill")
        self.assertIn("visualizacion", step.params["skill"].lower())

    def test_learn_word_routes_to_learning_engine(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("aprende a usar word")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "learn_skill")
        self.assertIn("word", step.params["skill"].lower())

    def test_learn_brave_routes_to_learning_engine(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("aprende a usar brave")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "learn_skill")
        self.assertIn("brave", step.params["skill"].lower())

    def test_learn_mouse_routes_to_learning_engine_cleanly(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("aprende a usar el mouse")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "learn_skill")
        self.assertEqual(step.params["skill"], "mouse")

    def test_continuous_input_training_start(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command(
            "entrena infinitamente hasta que te diga que pare"
        )

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "start_input_training_loop")
        self.assertTrue(step.requires_confirmation)
        self.assertIsNone(step.params["mouse_attempts"])

    def test_reevaluate_levels_intent(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("reevalua los niveles de aprendizaje")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "reevaluate_skill_levels")

    def test_autonomous_learn_intent(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("aprende autonomamente minecraft con curriculum")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "autonomous_learn")
        self.assertIn("minecraft", step.params["objective"].lower())

    def test_learn_game_objective_promotes_to_autonomous_learning(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("aprende a jugar terraria")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "autonomous_learn")
        self.assertIn("terraria", step.params["objective"].lower())

    def test_learn_open_ended_node_objective_promotes_to_autonomous_learning(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command(
            "aprende hacer una aplicacion web basica para sumar con node.js"
        )

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "autonomous_learn")
        self.assertIn("node.js", step.params["objective"].lower())

    def test_continuous_input_training_stop(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("para el entrenamiento continuo")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "stop_input_training_loop")

    def test_practice_investigation_by_minutes(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("practica investigar 10 minutos")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "practice_skill")
        self.assertEqual(step.params["minutes"], 10)
        self.assertIn("investig", step.params["skill"].lower())

    def test_evaluate_youtube_skill(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("evalua uso de youtube")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "evaluate_skill")
        self.assertIn("youtube", step.params["skill"].lower())

    def test_use_research_skill_for_goal(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("usa investigar para averiguar Rimuru Tempest")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "use_skill")
        self.assertIn("investig", step.params["skill"].lower())
        self.assertIn("Rimuru Tempest", step.params["goal"])

    def test_research_word_phrase_cleans_topic(self):
        parser = self.build_parser()
        interpretation = parser.interpret_command("investiga sobre minecraft y haz un word con eso")

        self.assertEqual(len(interpretation.steps), 1)
        step = interpretation.steps[0]
        self.assertEqual(step.action, "execute_complex_task")
        self.assertEqual(step.params["topic"], "minecraft")
        self.assertEqual(step.params["document_app"], "word")


if __name__ == "__main__":
    unittest.main()
