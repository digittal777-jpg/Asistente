# ROADMAP GEN 1: QUICK REFERENCE
## Resumen Ejecutivo para Ejecución

---

## CONTRATOS CLAVE (Implementar Primero)

### 1. TrainingScenarioResult
Resultado estructurado de CUALQUIER práctica. Campos obligatorios:
- `skill_id`, `domain`, `scenario_id`, `level`, `status` ("success" | "success_with_fallback" | "failure" | "blocked")
- `verified`: bool (¿pasó verificación?)
- `failure_stage`: None | "detection" | "action" | "verification"
- `fallback_used`: None | "explorer_fallback" | "copy_to_clipboard" (qué se usó)
- `attempted_strategies`, `chosen_strategy`: lista y seleccionado
- `metrics`: dict (latency, accuracy, etc)
- `evidence`: dict (filepath, screenshot, text, etc - LO QUE VERIFICA)
- `verified_outcome`: dict (resultado de verificación)

### 2. SkillGate
Define criterio de promoción. Campos:
- `skill_id`, `from_level`, `to_level`
- `required_scenarios`: lista de escenarios que debe cumplir
- `min_success_rate`, `max_fallback_rate`, `min_verified_sessions`
- `gate_passed`: bool, `gate_passed_date`: int

### 3. TrainableDraft
Para skills nuevos. Mapea a `family` existente, hereda templates.

### 4. RecoveryAttempt
Audita un reintento: failure_stage → chosen_strategy → recovery_result

### 5. ModelAssistDecision
Audita decisión neuronal: model_id → score → used? → fallback_reason?

---

## NIVELES Y GATES (Concreto)

### desktop-first Gates

| Nivel | Escenarios Requeridos | Min Success % | Max Fallback % | Min Sessions | Days |
|-------|------|------|------|------|------|
| 1→2 | 3 scenarios | 100% | 0% | 5 | 3 |
| 2→3 | 2 scenarios (drag, recovery) | 90% | 0% | 10 | 5 |
| 3→4 | 3 scenarios (drag real + verify) | 80% | 25% | 15 | 7 |
| 4→5 | Any Lvl4, 50 sessions | 70% | 25% | 50 | 14 |
| 5→ Ops | None, maintain 65%+ | 65% | <20% | — | — |

**Verificación Nivel 4**: `os.path.exists(dest) AND file_size == expected AND checksum_ok`

### investigar Gates

| Nivel | Escenarios Requeridos | Min Success % | Max Fallback % | Min Sessions | Days |
|-------|------|------|------|------|------|
| 1→2 | 2 scenarios | 100% | 0% | 5 | 3 |
| 2→3 | 2 scenarios (multi, discard) | 90% | 10% | 8 | 5 |
| 3→4 | 3 scenarios (OCR, recovery) | 80% | 25% | 12 | 7 |
| 4→5 | Any Lvl4, 50 sessions | 70% | 25% | 50 | 14 |

**Verificación Nivel 4**: `file_exists AND size>=5KB AND unique_facts>=5`

---

## SCHEDULER: FÓRMULA CONCRETA

```
score = (
    0.30 * priority_score +           # (9 - rank) / 8
    0.35 * weakness_score +           # (1 - success_rate) * (1 + fallback_rate)
    0.15 * stagnation_score +         # log(1 + days_stagnant/2) / log(8)
    0.10 * freshness_score +          # Decay over time
    0.10 * operational_score          # Emergencias
)
```

Selecciona: `max_score` por dominio cada sesión.

**8 Dominios**:
1. vision/detection (priority_rank=1)
2. selection/workflow (priority_rank=2)
3. research (priority_rank=1) ← DÉBIL hoy (55% success)
4. browser (priority_rank=3)
5. file_manager/explorer (priority_rank=3)
6. document_editor (priority_rank=4)
7. application_workflow (priority_rank=4)
8. game_foundation (priority_rank=5)

---

## FAMILY MAPPING (Para Drafts)

```python
SKILL_FAMILY_MAPPING = {
    # Vision & Desktop
    "desktop-first": "vision",
    "mouse_drag": "vision",
    "object_detection": "vision",
    
    # Research
    "investigar": "research",
    "search_google": "research",
    
    # Browser
    "fill_form": "browser",
    "extract_text": "browser",
    
    # File Manager
    "open_file_explorer": "file_manager",
    "copy_files": "file_manager",
    
    # Documents
    "save_document": "documents",
    "edit_text": "documents",
    
    # Application
    "launch_application": "application",
    "click_button": "application",
    
    # Game
    "press_key": "game",
    "move_cursor": "game"
}
```

Skill nuevo → lookup familia → hereda templates + verification rules.

---

## CRITERIOS DE SALIDA

### Gen 1.1a (desktop-first, 2 weeks)
- [ ] desktop-first Nivel 4: ≥20 sesiones, 70%+ success, ≤30% fallback
- [ ] Verificación filesystem 100% correcta en esas sesiones
- [ ] Dataset: ≥50 sesiones totales con TrainingScenarioResult completo
- [ ] Todos los TrainingScenarioResult tienen `verified_outcome` + `failure_stage` + `evidence`

### Gen 1.1b (investigar, 2 weeks)
- [ ] investigar Nivel 4: ≥15 sesiones, documentos guardados verificables
- [ ] Descarte de páginas pobres: ≥70% precision
- [ ] Multi-fuente: ≥5 sesiones con ≥3 URLs diferentes

### Gen 1.1c (Loop Infinito, 3 weeks)
- [ ] Loop rota entre 8 dominios cada sesión
- [ ] Scheduler reordena basado en scores cada sesión
- [ ] ≥10 sesiones por dominio en 2 semanas
- [ ] ≥2 skills alcanzaron Nivel 5 (promoción automática)
- [ ] Cero promociones falsas (validar 10 manualmente)

---

## RECUPERACIÓN: Playbooks

### Vision Domain
- **detection_lost** → ["retry_with_focus", "ocr_fallback", "manual"]
- **action_failed_3x** → ["copy_clipboard", "explorer_fallback", "manual_position"]
- **verification_failed** → ["verify_again", "check_alt_location", "inspect_fs"]

### Research Domain
- **page_timeout** → ["retry_url", "search_keywords", "cache"]
- **poor_quality** → ["skip_page", "search_specific", "ocr_screenshot"]
- **ocr_failed** → ["retry_ocr", "capture_again", "manual_entry"]

Elegir estrategia por historial: rank por success_rate (últimas 10 sesiones).

---

## VERIFICACIÓN: Código Base

### desktop-first Nivel 4
```python
verified = (
    os.path.exists(destination_path) 
    and os.path.getsize(destination_path) == expected_size
    and hashlib.md5(open(destination_path, 'rb').read()).hexdigest() == expected_checksum
)
```

### investigar Nivel 4
```python
verified = (
    os.path.exists(document_path) 
    and os.path.getsize(document_path) >= 5120  # 5KB
    and len([kw for kw in keywords if kw.lower() in content.lower()]) >= 3
    and unique_facts_count >= 5
)
```

---

## ARCHIVOS A CREAR

| Archivo | Responsabilidad | Prioridad |
|---------|---|---|
| `core/training_models.py` | Dataclasses (TrainingScenarioResult, etc) | P0 |
| `core/verification_desktop_first.py` | DesktopFirstVerifier + DESKTOP_FIRST_GATES | P0 |
| `core/verification_research.py` | ResearchVerifier + RESEARCH_GATES | P0 |
| `core/training_scheduler.py` | SkillScheduler con fórmula de pesos | P0 |
| `core/training_loop_infinite.py` | InfiniteTrainingLoop.run_one_cycle() | P1 |
| `core/recovery_engine.py` | RecoveryEngine + playbooks | P1 |
| `core/skill_family_mapping.py` | SKILL_FAMILY_MAPPING + TrainableDraft factory | P1 |
| `core/models/ui_target_ranker.py` | UITargetRankerModel (heurístico + ONNX slot) | P2 |
| `core/models/page_usefulness_classifier.py` | PageUsefulnessClassifier (heurístico + ONNX slot) | P2 |

---

## EJEMPLOS DE USO

### Crear y ejecutar un scenario
```python
from core.training_models import TrainingScenarioResult, SkillGate
from core.verification_desktop_first import DesktopFirstVerifier
from core.training_loop_infinite import InfiniteTrainingLoop

loop = InfiniteTrainingLoop(scheduler, verifiers)
loop.run_sessions(50)  # Ejecuta 50 ciclos
```

### Crear draft para skill nuevo
```python
from core.skill_family_mapping import create_trainable_draft

draft = create_trainable_draft(
    skill_id="fill_form",
    skill_name="Fill Web Forms",
    description="Enter data into web form fields"
)
# draft.family = "browser" (auto-mapped)
# draft.scenario_templates = browser templates
# draft.missing_capabilities = []
```

### Recuperación tras fallo
```python
from core.recovery_engine import RecoveryEngine

engine = RecoveryEngine(history)
recovery = engine.get_next_strategy({
    "training_scenario_id": "...",
    "failure_stage": "detection",
    "failure_reason": "Target lost after frame 5",
    "domain": "vision"
})
# recovery.chosen_next_strategy = "ocr_fallback" (basado en historial)
```

---

## MÉTRICAS A MONITOREAR

| Métrica | Frecuencia | Umbral OK |
|---------|---|---|
| `desktop-first` success_rate | Cada sesión | ≥70% |
| `investigar` success_rate | Cada sesión | ≥65% |
| Scheduler reordenación | Cada sesión | Cambio en ranking |
| Verificación latency | Cada sesión | <500ms |
| Recovery success_rate | Por dominio | ≥60% |
| Gate promotion rate | Semanal | ≥1 skill alcanza Lvl5/week |

---

## PRÓXIMOS PASOS (INMEDIATOS)

1. **Crear core/training_models.py** con dataclasses
2. **Crear core/verification_desktop_first.py** con verifier + gates
3. **Crear core/training_scheduler.py** con fórmula concreta
4. **Ejecutar 10 sesiones manual** desktop-first Nivel 1 para validar TrainingScenarioResult
5. **Escalar a 50 sesiones**, verificar todas las sesiones
6. **Repetir para investigar**
7. **Integrar loop infinito**, hacer que rote entre dominios

---

**Versión**: 1.0 Quick Ref  
**Fecha**: Mayo 17, 2026  
