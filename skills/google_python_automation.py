from core.skills import Skill


def build_skill() -> Skill:
    return Skill(
        name="google_python_automation",
        description="Abre el navegador con una busqueda sobre automatizacion en Python.",
        triggers=[
            "google python automation",
            "busca automatizacion en python",
            "abre google con automation python",
        ],
        handler=run,
        metadata={"category": "web"},
    )


def run(context, **kwargs):
    query = kwargs.get("query", "python desktop automation examples")
    return context.search_google(query)
