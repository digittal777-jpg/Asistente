from datetime import datetime

from core.skills import Skill


def build_skill() -> Skill:
    return Skill(
        name="capture_desktop",
        description="Toma un screenshot con nombre automatico y lo guarda en screenshots/.",
        triggers=[
            "captura el escritorio",
            "toma screenshot del escritorio",
            "guarda una captura de pantalla",
        ],
        handler=run,
        metadata={"category": "vision"},
    )


def run(context, **kwargs):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = context.base_dir / "screenshots" / f"desktop_{stamp}.png"
    return context.take_screenshot(str(path))
