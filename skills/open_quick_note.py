from core.skills import Skill


def build_skill() -> Skill:
    return Skill(
        name="open_quick_note",
        description="Abre Notepad, espera un segundo y escribe una nota rapida.",
        triggers=[
            "abre una nota rapida",
            "crea una nota rapida",
            "nota rapida en notepad",
        ],
        handler=run,
        metadata={"category": "productividad"},
    )


def run(context, **kwargs):
    message = kwargs.get("message", "Raphel listo para automatizar tareas.")
    context.open_application("notepad")
    context.automation.wait(1.0)
    return context.write_text(message)
