import unittest

from core.command_parser import CommandAction, CommandInterpretation
from core.task_planner import TaskPlanner


class FakeConfig:
    def get(self, _key, default=None):
        return default


class FakeMemory:
    pass


class TaskPlannerSkillTests(unittest.TestCase):
    def setUp(self):
        self.planner = TaskPlanner(FakeConfig(), FakeMemory())

    def test_should_not_plan_when_learning_skill_action_is_present(self):
        interpretation = CommandInterpretation(
            original="aprende a investigar",
            steps=[CommandAction(action="learn_skill", params={"skill": "investigar"})],
        )
        self.assertFalse(self.planner.should_plan("aprende a investigar", interpretation))

    def test_should_plan_for_explicit_complex_task(self):
        interpretation = CommandInterpretation(
            original="investiga sobre Rimuru",
            steps=[CommandAction(action="execute_complex_task", params={"topic": "Rimuru"})],
        )
        self.assertTrue(self.planner.should_plan("investiga sobre Rimuru", interpretation))


if __name__ == "__main__":
    unittest.main()
