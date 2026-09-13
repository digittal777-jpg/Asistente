import unittest

from core.training_models import DomainTrainingState
from core.training_scheduler import SkillScheduler


class TrainingSchedulerTests(unittest.TestCase):
    def test_scheduler_prioritizes_weaker_high_priority_domain(self):
        scheduler = SkillScheduler()
        research = DomainTrainingState(
            domain="research",
            priority_rank=1,
            success_rate=0.35,
            fallback_rate=0.25,
            days_stagnant=8.0,
            freshness_score=0.8,
            operational_score=0.7,
        )
        documents = DomainTrainingState(
            domain="document_editor",
            priority_rank=4,
            success_rate=0.9,
            fallback_rate=0.0,
            days_stagnant=1.0,
            freshness_score=0.4,
            operational_score=0.1,
        )

        selected = scheduler.next_domain([documents, research])
        self.assertIsNotNone(selected)
        self.assertEqual(selected.domain, "research")


if __name__ == "__main__":
    unittest.main()
