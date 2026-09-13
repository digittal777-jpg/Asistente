# Raphel

`Raphel` es un asistente de escritorio local para Windows con:

- GUI moderna en `customtkinter` con fallback a `tkinter`
- captura y analisis de pantalla
- control de mouse, teclado, ventanas y pestanas
- interpretacion de comandos en lenguaje natural sin APIs externas
- sistema de skills con triggers

## Estructura principal

```text
Asistente/
|- raphel.py
|- requirements.txt
|- pyproject.toml
|- .editorconfig
|- .gitignore
|- config/
|  |- settings.json
|- core/
|  |- assistant.py
|  |- automation.py
|  |- command_parser.py
|  |- command_router.py
|  |- config.py
|  |- gui.py
|  |- logging_utils.py
|  |- nlp.py
|  |- reminders.py
|  |- skill_manager.py
|  |- skills.py
|  |- vision.py
|- docs/
|  |- README.md
|  |- analysis/
|  |- roadmaps/
|  |- validation/
|- skills/
|  |- capture_desktop.py
|  |- google_python_automation.py
|  |- open_quick_note.py
|  |- open_work_folder.py
|  |- learned/              # generado localmente; no se versiona
|- QUICK_CHECK.bat
|- RUN_VALIDATION.bat
|- QUICK_VALIDATION_CHECK.py
|- VALIDATION_LIVE_TEST.py
```

## Instalacion

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Para OCR necesitas instalar tambien **Tesseract OCR** y dejar su ejecutable disponible en el `PATH`.

## Ejecucion

```powershell
python raphel.py
python raphel.py --gui
python raphel.py --command "skills"
```

## Parser avanzado

El motor principal ahora vive en `core/command_parser.py` y combina:

- intents por reglas y regex
- analisis secuencial de multiples acciones
- fuzzy matching con `rapidfuzz`
- aprendizaje por feedback guardado en `data/command_feedback.json`

La GUI ya esta integrada con este parser y muestra un plan detectado antes de ejecutar.

## 15 comandos compuestos que Raphel debe entender

- `Abre YouTube y buscame ponk`
- `Abre Brave, entra a YouTube y busca 'That Time I Got Reincarnated as a Slime'`
- `Abre Spotify y pon musica de anime`
- `Abre Visual Studio Code y abre el proyecto de Raphel`
- `Abre Chrome en incognito y ve a gmail`
- `Abre Firefox y busca noticias de tecnologia`
- `Abre Edge y entra a GitHub`
- `Abre Brave y luego busca slime isekai`
- `Abre YouTube y quiero ver openings de anime`
- `Reproduce lofi japones en Spotify`
- `Abre Brvae y entra a Yotube`
- `Abre Vusual Studio Cdoe y abre el proyecto Raphel`
- `Abre la carpeta de Descargas y luego abre Visual Studio Code`
- `Minimiza todas las ventanas y abre Brave`
- `Cierra la ventana actual y abre Chrome en incognito`

## Comandos directos utiles

- `skills`
- `open-browser brave https://www.youtube.com`
- `open-app notepad`
- `open-folder descargas`
- `desktop-organize` (ordena el escritorio con acciones visibles y aprendizaje)
- `desktop-organize-fast` (modo legacy por filesystem; requiere activarlo en config)
- `desktop-practice-mouse 4` (practica arrastre con archivos temporales seguros)
- `desktop-practice-mouse-move 100` (practica movimiento basico del puntero)
- `desktop-practice-mouse-click 100` (practica click simple)
- `desktop-practice-mouse-double-click 100` (practica doble click)
- `desktop-practice-mouse-right-click 100` (practica click derecho)
- `desktop-practice-mouse-selection 100` (practica deteccion de seleccion visual)
- `desktop-practice-mouse-workflow 100` (practica flujo completo con temporales)
- `input-training-start 6` (repite mouse+teclado hasta `input-training-stop`)
- `input-training-status` (estado del bucle continuo)
- `input-training-stop` (detiene el bucle continuo)
- Parada rapida del infinito: mantener `Esc` 1.2s, `Ctrl+Alt+S` o `Pause/Break`
- `desktop-undo-last` (deshace la ultima sesion visible con confirmacion)
- `learning-status` (muestra aprendizaje inteligente general)
- `doctor` (diagnostico reproducible de dependencias, runtime, datos y seguridad local)
- `p1-validation` (reporte P1 guiado sin tocar el escritorio)
- `p1-validation --execute-live` (intentos reales minimos; mueve ventanas/mouse si el flujo lo requiere)
- `write-window YouTube|slime isekai`
- `volume-set 80`
- `tab new`
- `tab next`
- `focus-window Visual Studio Code`
- `close-window`

## Skills

Cada skill usa la clase `Skill` con:

- `name`
- `description`
- `triggers`
- `execute()` mediante `handler`

Tambien puedes guardar skills aprendidas en JSON dentro de `skills/learned/`.
Ese directorio se trata como memoria local y no se sube al repositorio.

Ejemplo desde Python:

```python
from core.assistant import RaphelAssistant

assistant = RaphelAssistant()
assistant.learn_new_skill(
    "abrir_y_buscar",
    "Abre el navegador y busca una consulta concreta",
    [
        {"action": "search_google", "query": "desktop automation python"},
        {"action": "wait", "seconds": 1.0},
        {"action": "take_screenshot", "path": "screenshots/google.png"},
    ],
    triggers=["abre y busca automation", "busca automation rapido"],
)
```

Ejemplo JSON:

```json
{
  "name": "nota_rapida",
  "description": "Abre Notepad y escribe una nota.",
  "triggers": ["nota rapida", "abre nota rapida"],
  "steps": [
    {"action": "open_application", "target": "notepad"},
    {"action": "wait", "seconds": 1},
    {"action": "write_text", "text": "Hola desde Raphel"}
  ]
}
```

## Ordenado visible del escritorio

`ordena mi escritorio` usa `desktop_organizer.execution_mode = "ui_learning"` por defecto.
Raphel abre el Escritorio en Explorer, crea carpetas visibles, selecciona archivos e intenta
arrastrarlos con el mouse primero. Si el arrastre no mueve el archivo, usa `Ctrl+X`/`Ctrl+V`
como rescate visible. Cada sesion guarda:

- manifiesto en `data/desktop_organizer_sessions/`
- estrategia adaptativa de mouse en `data/desktop_mouse_strategy.json`
- movimientos en `raphel_memory.db`
- logs paso a paso para consultar desde `memory`

La estrategia adaptativa guarda perfiles de arrastre, exitos, fallos y perfil preferido por
categoria. Si un perfil falla, baja su prioridad; si funciona, Raphel lo reutiliza primero.

Para practicar sin tocar archivos reales, usa `desktop-practice-mouse 4` o pide
`practica el mouse en el escritorio`. Raphel crea archivos temporales dentro de
`_Raphel_Practica_Mouse`, intenta arrastrarlos por UI y actualiza la compuerta
`practice.real_drag_enabled` en `data/desktop_mouse_strategy.json`. Si la tasa de
exito no supera la configuracion, el drag real queda suspendido y el ordenado usa
cortar/pegar visible como metodo seguro.

Para practicar la primera habilidad base, usa `desktop-practice-mouse-move 100`
o pide `practica mover el mouse 100 veces`. Este modo solo mueve el puntero a
puntos seguros, mide el error en pixeles y guarda `practice.movement`.

Luego puedes practicar gestos separados con `practica click simple 100 veces`,
`practica doble click 100 veces` y `practica click derecho 100 veces`. Cada modo
guarda su propia seccion (`practice.click`, `practice.double_click`,
`practice.right_click`) para que Raphel no mezcle habilidades distintas.

Las ultimas etapas seguras son `practica seleccion visual 100 veces` y
`practica flujo completo seguro 100 veces`. La primera mide si Raphel detecta la
seleccion azul de Explorer; la segunda une seleccion, movimiento, drag/fallback y
verificacion usando solo archivos temporales.

`aprende a usar el mouse` usa ahora ese mismo entrenador real desde el motor de
habilidades aprendibles: conserva el historial de `desktop_mouse_strategy.json`
como experiencia, pero los niveles nuevos se verifican ejecutando practica real.

Si pides `entrena el flujo completo del mouse y teclado infinitamente`, Raphel
inicia un bucle en segundo plano que baraja siete entrenamientos de mouse
(movimiento, click, doble click, click derecho, drag seguro, seleccion y flujo
completo) junto con practica de `teclado`. Cada ciclo lee el nivel actual de
`skill:mouse` y `skill:teclado`: al subir de nivel aumenta la cantidad de
intentos, mezcla mas pruebas y vuelve a intentar los pasos que reporten fallos
o una tasa baja. Los puntos de movimiento usan jitter para no entrenar siempre
sobre las mismas coordenadas; drag baraja perfiles de arrastre y, si un intento
no funciona, prueba otros puntos/direcciones seguros antes de rendirse. Teclado
genera frases de practica distintas en Notepad, en vez de repetir siempre el
mismo texto. Se detiene con
`input-training-stop` o con una frase natural como `para el entrenamiento
continuo`; si la IA tiene tomado el teclado/mouse, manten `Esc` 1.2 segundos
o pulsa `Ctrl+Alt+S` / `Pause/Break`. Tambien puedes crear el archivo
`data/input_training_loop.stop` desde otra ventana. El ciclo actual intenta
cerrarse de forma segura antes de parar.

Al final de cada ciclo, el bucle sincroniza las sesiones nuevas de mouse con
`skill:mouse` en `data/learning_skill_profiles.json`. Eso permite que las
practicas directas de movimiento, clicks, drag, seleccion y flujo completo
cuenten para los gates de nivel sin tener que ejecutar `skill-practice mouse`
manualmente despues de cada tanda. El perfil de mouse tiene cinco niveles:
base, drag/seleccion/flujo seguro, flujo estable, avanzado y nocturno. Una misma
sesion no se vuelve a contar si el perfil sube de nivel; las sesiones nuevas si
entran en el nivel actual para enriquecer el aprendizaje.

Las habilidades de juego como `aprende a jugar Terraria` ya no quedan como
draft pasivo. Se registran como `game_foundation` y entrenan bases reales de
teclado, mouse y busqueda de controles. Eso no lanza ni domina el juego real:
solo deja lista la base hasta que exista un backend especifico de ventana/estado
del juego.

El modo rapido antiguo no se usa por defecto. Para permitirlo hay que activar
`desktop_organizer.allow_legacy_filesystem_fallback`.

## Aprendizaje inteligente general

Raphel guarda aprendizaje global en `data/intelligent_learning.json`. Esta capa observa comandos,
acciones y estrategias para:

- reutilizar comandos seguros cuando una frase nueva se parece a una anterior exitosa
- adaptar parametros, como navegador preferido o app de documentos
- priorizar estrategias que funcionaron, como targets visuales de busqueda
- penalizar estrategias que fallaron para probar otra ruta la siguiente vez

Usa `learning-status` para ver un resumen sin abrir archivos internos.

## Aprendizaje por feedback

Desde Python:

```python
assistant.learn_from_feedback(
    "Abre brvae y entra a yotube",
    [
        {"action": "open_browser", "params": {"browser": "brave"}, "summary": "Abrir brave"},
        {
            "action": "open_url",
            "params": {"url": "https://www.youtube.com", "browser": "brave"},
            "summary": "Ir a youtube",
        },
    ],
)
```

Desde consola o GUI:

```text
feedback Abre brvae y entra a yotube|[{"action":"open_browser","params":{"browser":"brave"}},{"action":"open_url","params":{"url":"https://www.youtube.com","browser":"brave"}}]
```

## Seguridad

- `pyautogui.FAILSAFE = True`
- confirmacion para cierres de ventana y comandos peligrosos
- historial en `data/action_history.jsonl`
- logs en `logs/raphel.log`

## Verificacion hecha

- compilacion de todo el proyecto con `python -m compileall .`
- validacion del parser natural contra los ejemplos principales
- validacion del sistema de triggers de skills
