import unittest

from core.command_router import CommandRouter


class CommandRouterSkillTests(unittest.TestCase):
    def setUp(self):
        self.router = CommandRouter(lambda action, args: f"{action}:{args}")

    def test_skill_learn_command(self):
        action, args = self.router.match_command("skill-learn youtube")
        self.assertEqual(action, "skill-learn")
        self.assertEqual(args, ["youtube"])

    def test_skill_practice_command(self):
        action, args = self.router.match_command("skill-practice investigar 10 minutos")
        self.assertEqual(action, "skill-practice")
        self.assertEqual(args, ["investigar 10 minutos"])

    def test_skill_evaluate_command(self):
        action, args = self.router.match_command("skill-evaluate teclado")
        self.assertEqual(action, "skill-evaluate")
        self.assertEqual(args, ["teclado"])

    def test_skill_use_command(self):
        action, args = self.router.match_command("skill-use investigar|rimuru tempest")
        self.assertEqual(action, "skill-use")
        self.assertEqual(args[0], "investigar")
        self.assertEqual(args[1], "rimuru tempest")

    def test_skill_status_command(self):
        action, args = self.router.match_command("skill-status")
        self.assertEqual(action, "skill-status")
        self.assertEqual(args, [])

    def test_input_training_loop_commands(self):
        action, args = self.router.match_command("input-training-start 6")
        self.assertEqual(action, "input-training-start")
        self.assertEqual(args, ["6"])

        action, args = self.router.match_command("input-training-status")
        self.assertEqual(action, "input-training-status")
        self.assertEqual(args, [])

        action, args = self.router.match_command("input-training-stop")
        self.assertEqual(action, "input-training-stop")
        self.assertEqual(args, [])

    def test_remote_console_commands(self):
        action, args = self.router.match_command("remote-console-start 9001")
        self.assertEqual(action, "remote-console-start")
        self.assertEqual(args, ["9001"])

        action, args = self.router.match_command("remote-console-online 8765")
        self.assertEqual(action, "remote-console-online")
        self.assertEqual(args, ["8765"])

        action, args = self.router.match_command("remote-console-status")
        self.assertEqual(action, "remote-console-status")
        self.assertEqual(args, [])

        action, args = self.router.match_command("remote-console-stop")
        self.assertEqual(action, "remote-console-stop")
        self.assertEqual(args, [])

    def test_reset_runtime_command_aliases(self):
        for command in ("reset", "reset-runtime", "runtime-reset", "assistant-reset"):
            action, args = self.router.match_command(command)
            self.assertEqual(action, "reset-runtime")
            self.assertEqual(args, [])

    def test_doctor_command_aliases(self):
        for command in ("doctor", "raphel-doctor", "raphael-doctor"):
            action, args = self.router.match_command(command)
            self.assertEqual(action, "doctor")
            self.assertEqual(args, [])

    def test_p1_validation_command_aliases(self):
        action, args = self.router.match_command("p1-validation")
        self.assertEqual(action, "p1-validation")
        self.assertEqual(args, [])

        action, args = self.router.match_command("validate-p1 --execute-live")
        self.assertEqual(action, "p1-validation")
        self.assertEqual(args, ["--execute-live"])


if __name__ == "__main__":
    unittest.main()
