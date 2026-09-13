# BUGS ESPECIFICOS ENCONTRADOS - RAPHEL PROJECT

**Fecha verificada:** 2026-05-18  
**Nota:** este archivo ya no conserva como verdad los bugs historicos que quedaron desactualizados

## Bugs historicos que ya no aplican

### 1. `Memory.get_preference() NO EXISTE`
- Ya no aplica.
- `core/memory.py` si tiene `get_preference`.

### 2. `Recovery Strategy Selection Siempre Default`
- Ya no aplica como estaba descrito.
- `core/recovery_engine.py` ya usa playbooks y preferencias aprendidas.

### 3. `Desktop Drag & Drop Siempre Falla`
- Ya no es una descripcion correcta del estado actual.
- El organizer ya tiene rutas de seleccion visual/directa y pruebas para practicas controladas.

## Bugs vigentes o limites reales

### 1. Research puede parecer accion sin resultado
**Severidad:** Alta  
**Modulo:** `core/learning_skill_engine.py`

Riesgo real:
- abrir Google o una fuente y marcar exito aunque no se haya capturado texto util de la sesion actual

Estado actual:
- ya se endurecio la evidencia
- ya no debe contar como exito si sigue en Google, cae en modal o captura poco texto

Lo pendiente:
- validacion viva con sitios reales

### 2. Word bajo `strict_real` puede bloquear el dominio
**Severidad:** Alta  
**Modulo:** `core/learning_skill_engine.py`

Riesgo real:
- foco equivocado
- modal inesperado
- captura vacia
- mismatch entre texto escrito y texto capturado

Estado actual:
- ya falla de forma honesta en esos casos
- ya no se desbloquea por historial suave
- solo una sesion fresca verificada debe limpiar el bloqueo

Lo pendiente:
- revalidar en runtime real que `app:word` salga de `blocked`

### 3. YouTube aun no equivale a comprension de video completa
**Severidad:** Media-Alta  
**Modulo:** `core/learning_skill_engine.py`, `core/task_executor.py`, `core/vision.py`

Estado actual:
- ahora usa `transcript + OCR`
- prioriza transcript, captions, metadata y sidebar util

Limite real:
- eso mejora investigacion visible
- no resuelve comprension de audio, escenas ni timeline completo

### 4. El sistema autonomo podia inflar assets debiles
**Severidad:** Media  
**Modulo:** `core/autonomous_learning_system.py`

Estado actual:
- ya se filtran assets de investigacion flojos
- transcript/OCR insuficiente ya no deberia promocionarse como conocimiento fuerte

### 5. Falta validacion viva obligatoria
**Severidad:** Alta  
**Impacto:** confianza real del proyecto

Aunque la suite actual pasa con `180` pruebas, todavia falta comprobar en Windows real:
- `aprende a investigar`
- `aprende a usar youtube`
- `aprende a usar word`
- `desktop-practice-mouse-workflow`

## Prioridad real de seguimiento

1. Correr validacion viva de navegador/research.
2. Revalidar Word hasta sacar `app:word` de `blocked`.
3. Probar YouTube con transcript disponible y transcript ausente.
4. Confirmar que Explorer no vuelva a contaminar practica controlada con ventanas de busqueda.
