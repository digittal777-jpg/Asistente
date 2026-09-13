import unittest

from core.perception import PerceptionEngine


class FakeElement:
    def __init__(self, name, x=100, y=100, width=120, height=40, confidence=0.95):
        self.name = name
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.confidence = confidence


class FakeWindow:
    def __init__(self, title, app_name, site_hint="", is_active=True, left=0, top=0, width=1280, height=720):
        self.title = title
        self.app_name = app_name
        self.site_hint = site_hint
        self.is_active = is_active
        self.left = left
        self.top = top
        self.width = width
        self.height = height


class FakeSnapshot:
    def __init__(self, active_window, active_app, active_site="", elements=None, confidence=0.92, ocr_excerpt=""):
        self.captured_at = "2026-05-18T10:00:00"
        self.active_window = active_window
        self.active_app = active_app
        self.active_site = active_site
        self.elements = list(elements or [])
        self.windows = [FakeWindow(active_window, active_app, active_site, True)]
        self.confidence = confidence
        self.ocr_excerpt = ocr_excerpt


class FakeVision:
    def get_latest_snapshot(self, refresh=False):
        raise NotImplementedError


class PerceptionEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = PerceptionEngine(FakeVision())

    def test_classifies_supported_scenes(self):
        cases = [
            ("explorer", FakeSnapshot("Explorador", "explorer"), "explorer"),
            (
                "browser_serp",
                FakeSnapshot(
                    "Google Search",
                    "brave",
                    "google",
                    elements=[FakeElement("google_result_card_1")],
                ),
                "browser_serp",
            ),
            (
                "youtube_results",
                FakeSnapshot(
                    "YouTube Search",
                    "brave",
                    "youtube",
                    elements=[FakeElement("youtube_results_primary_region")],
                ),
                "youtube_results",
            ),
            (
                "youtube_watch",
                FakeSnapshot(
                    "YouTube Watch",
                    "brave",
                    "youtube",
                    elements=[FakeElement("youtube_transcript_region")],
                ),
                "youtube_watch",
            ),
            (
                "unknown",
                FakeSnapshot("Bloc de notas", "notepad", elements=[FakeElement("document_body")]),
                "unknown",
            ),
        ]

        for label, snapshot, expected in cases:
            with self.subTest(label=label):
                observation = self.engine.observe_snapshot(snapshot)
                self.assertEqual(observation.scene_kind, expected)

    def test_reacquire_matches_same_target_with_small_delta(self):
        previous = self.engine.observe_snapshot(
            FakeSnapshot(
                "Google Search",
                "brave",
                "google",
                elements=[FakeElement("google_result_card_1", x=100, y=140)],
            )
        )
        current = self.engine.observe_snapshot(
            FakeSnapshot(
                "Google Search",
                "brave",
                "google",
                elements=[FakeElement("google_result_card_1", x=112, y=148)],
            )
        )

        result = self.engine.evaluate_target_reacquire(previous, current)

        self.assertTrue(result["matched"])
        self.assertLessEqual(result["delta_px"], 24.0)

    def test_reacquire_fails_when_signature_changes_and_target_drifts(self):
        previous = self.engine.observe_snapshot(
            FakeSnapshot(
                "Google Search",
                "brave",
                "google",
                elements=[FakeElement("google_result_card_1", x=100, y=140)],
            )
        )
        current = self.engine.observe_snapshot(
            FakeSnapshot(
                "Google Search",
                "brave",
                "google",
                elements=[FakeElement("google_result_card_alpha", x=360, y=140)],
            )
        )

        result = self.engine.evaluate_target_reacquire(previous, current)

        self.assertFalse(result["matched"])
        self.assertEqual(result["reason"], "delta_or_signature_mismatch")


if __name__ == "__main__":
    unittest.main()
