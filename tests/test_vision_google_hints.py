from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.vision import ScreenVision, WindowContext


class GoogleResultHintTests(unittest.TestCase):
    def test_google_result_hints_stay_in_left_results_column(self):
        with TemporaryDirectory() as temp_dir:
            vision = ScreenVision(base_dir=Path(temp_dir))
            window = WindowContext(
                title="Google",
                app_name="brave",
                site_hint="google",
                left=0,
                top=0,
                width=1800,
                height=980,
                is_active=True,
            )

            hints = vision._build_google_result_hints(window)

            result_hints = [hint for hint in hints if hint.name.startswith("google_result_card_")]
            self.assertEqual(len(result_hints), 5)
            for hint in result_hints:
                right_edge = hint.x + (hint.width // 2)
                self.assertLess(hint.x, int(window.width * 0.35))
                self.assertLess(right_edge, int(window.width * 0.52))
                self.assertGreater(hint.width, 300)

    def test_google_ui_hints_include_reading_regions(self):
        with TemporaryDirectory() as temp_dir:
            vision = ScreenVision(base_dir=Path(temp_dir))
            window = WindowContext(
                title="Seguridad de contraseñas - Buscar con Google - Brave",
                app_name="brave",
                site_hint="google",
                left=0,
                top=0,
                width=1800,
                height=980,
                is_active=True,
            )

            hints = vision._build_ui_hints(window, "google")
            names = {hint.name for hint in hints}

            self.assertIn("browser_primary_reading_region", names)
            self.assertIn("google_results_column", names)
            self.assertIn("google_results_primary_region", names)

    def test_youtube_ui_hints_include_watch_regions(self):
        with TemporaryDirectory() as temp_dir:
            vision = ScreenVision(base_dir=Path(temp_dir))
            window = WindowContext(
                title="Tutorial Redstone Basico - YouTube - Brave",
                app_name="brave",
                site_hint="youtube",
                left=0,
                top=0,
                width=1800,
                height=980,
                is_active=True,
            )

            hints = vision._build_ui_hints(window, "youtube")
            names = {hint.name for hint in hints}

            self.assertIn("youtube_watch_primary_region", names)
            self.assertIn("youtube_watch_metadata_region", names)
            self.assertIn("youtube_watch_sidebar_region", names)
            self.assertIn("youtube_transcript_region", names)
            self.assertIn("youtube_captions_region", names)
            self.assertIn("youtube_transcript_toggle", names)
            self.assertIn("youtube_result_title_1", names)


if __name__ == "__main__":
    unittest.main()
