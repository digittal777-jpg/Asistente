from core.skills import Skill


def build_skill() -> Skill:
    return Skill(
        name="open_work_folder",
        description="Abre una carpeta de trabajo frecuente definida en la configuracion.",
        triggers=[
            "abre mi carpeta de trabajo",
            "abre la carpeta de documentos",
            "abre mis documentos",
        ],
        handler=run,
        metadata={"category": "archivos"},
    )


def run(context, **kwargs):
    folder = kwargs.get("folder", "documents")
    return context.open_folder(folder)
