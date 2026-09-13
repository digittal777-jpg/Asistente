# SKILL MAP MAESTRO — AGENTE AUTÓNOMO
## Mapa Completo de Habilidades para Implementación

**Versión**: 1.0  
**Fecha**: Mayo 17, 2026  
**Compatibilidad**: Gen 1.1a → Gen 1.5 → Gen 2.5+  
**Total**: 6 Dominios | 36 Skills críticas | 3 Niveles de prioridad

---

## ÍNDICE

1. [Estructura de Prioridades](#estructura-de-prioridades)
2. [Dominio 1 — Visión & Detección](#dominio-1--visión--detección)
3. [Dominio 2 — Control & Acción](#dominio-2--control--acción)
4. [Dominio 3 — Investigación](#dominio-3--investigación)
5. [Dominio 4 — Aprendizaje Autónomo](#dominio-4--aprendizaje-autónomo)
6. [Dominio 5 — Resolución de Problemas](#dominio-5--resolución-de-problemas)
7. [Dominio 6 — Gaming & Aplicaciones](#dominio-6--gaming--aplicaciones)
8. [Cadena Crítica de Dependencias](#cadena-crítica-de-dependencias)
9. [Matriz de Dependencias Completa](#matriz-de-dependencias-completa)
10. [Roadmap de Implementación por Fase](#roadmap-de-implementación-por-fase)
11. [Criterios de Promoción por Skill](#criterios-de-promoción-por-skill)
12. [Checklist de Implementación](#checklist-de-implementación)

---

## ESTRUCTURA DE PRIORIDADES

| Nivel | Código | Descripción | Cuando implementar |
|-------|--------|-------------|-------------------|
| Fundacional | **P0** | Sin esto el sistema no puede operar | Gen 1.1a — primero |
| Core | **P1** | Necesario para autonomía completa | Gen 1.1b / 1.1c |
| Avanzado | **P2** | Expande capacidades a nuevos dominios | Gen 2 / Gen 2.5+ |

> **Regla**: Nunca implementar P1 sin P0 completo. Nunca P2 sin P1 estable.

---

## DOMINIO 1 — VISIÓN & DETECCIÓN

**Propósito**: Ver y entender la pantalla en tiempo real.  
**Priority rank en scheduler**: 1 (máxima prioridad)  
**Family mapping**: `vision`

### SKILL-V1 — Detección de elementos UI
- **Prioridad**: P0 — Fundacional
- **Descripción**: Identificar botones, campos, iconos y controles en cualquier pantalla con precisión suficiente para actuar sobre ellos.
- **Requiere**: Ningún prerrequisito
- **Habilita**: `mouse_control`, `form_fill`, `drag_drop`, todo el sistema
- **Verificación**: `detected_element != None AND confidence >= 0.85`
- **Tags**: `vision`, `desktop`
- **Nivel objetivo Gen 1.1a**: Nivel 4 (≥80% success, ≤25% fallback, ≥15 sesiones)
- **Notas de implementación**: Es la skill más crítica del sistema. Prioridad absoluta. Failure en esta etapa bloquea todo lo demás.

---

### SKILL-V2 — OCR y lectura de texto
- **Prioridad**: P0 — Fundacional
- **Descripción**: Extraer texto legible de imágenes, PDFs escaneados, capturas de pantalla y elementos UI que no exponen texto por API.
- **Requiere**: `SKILL-V1` (detección de elementos UI)
- **Habilita**: `research`, `document_reading`, `verification_semantic`, `game_state_reading`
- **Verificación**: `extracted_text != "" AND len(extracted_text) >= expected_min_chars AND similarity(ground_truth) >= 0.90`
- **Tags**: `vision`, `research`, `gaming`
- **Nivel objetivo**: Nivel 4 (accuracy ≥90% en texto estándar, ≥70% en texto pequeño/rotado)
- **Notas de implementación**: Fallback natural cuando detección de elementos UI falla. Debe funcionar en screenshots parciales.

---

### SKILL-V3 — Verificación por checksum
- **Prioridad**: P0 — Fundacional
- **Descripción**: Confirmar integridad y correctitud de archivos después de operaciones de escritura, copia o descarga usando hash MD5/SHA256.
- **Requiere**: `SKILL-F1` (filesystem operations básicas)
- **Habilita**: `training_loop_verification`, `trusted_results`, `gate_evaluation`
- **Verificación**:
  ```python
  verified = (
      os.path.exists(destination_path)
      and os.path.getsize(destination_path) == expected_size
      and hashlib.md5(open(destination_path,'rb').read()).hexdigest() == expected_checksum
  )
  ```
- **Tags**: `verification`, `filesystem`
- **Nivel objetivo**: 100% correcto — sin tolerancia. Fallo aquí = fallo de sesión.
- **Notas de implementación**: Parte de `DesktopFirstVerifier`. Ver `core/verification_desktop_first.py`.

---

### SKILL-V4 — Detección de cambios de estado
- **Prioridad**: P1 — Core
- **Descripción**: Reconocer automáticamente cuando la pantalla cambia tras una acción: loading spinners, mensajes de error, confirmaciones, cambios de vista.
- **Requiere**: `SKILL-V1` (detección UI)
- **Habilita**: `recovery_engine`, `adaptive_retry`, `action_confirmation`
- **Verificación**: `state_before != state_after OR timeout_detected == True`
- **Tags**: `vision`, `recovery`
- **Nivel objetivo**: ≥85% detección correcta de cambios en ≤500ms
- **Notas de implementación**: Fundamental para el loop de recuperación. Sin esto, el agente no sabe si su acción tuvo efecto.

---

### SKILL-V5 — Template matching
- **Prioridad**: P1 — Core
- **Descripción**: Comparar regiones de pantalla contra plantillas pre-guardadas para localizar elementos que cambian de posición (sprites, iconos de juego, botones de posición variable).
- **Requiere**: `SKILL-V1` (detección UI)
- **Habilita**: `gaming_skills`, `dynamic_UI_handling`, `sprite_detection`
- **Verificación**: `match_confidence >= 0.80 AND bounding_box_valid == True`
- **Tags**: `vision`, `gaming`
- **Nivel objetivo**: ≥80% match rate con templates de referencia
- **Notas de implementación**: Clave para Gen 2.5 gaming. Permite localizar HP bars, minimapas, inventarios que no tienen posición fija.

---

## DOMINIO 2 — CONTROL & ACCIÓN

**Propósito**: Manipular el entorno digital de forma precisa y confiable.  
**Priority rank en scheduler**: 2  
**Family mapping**: `vision` (mouse) + `application` (keyboard)

### SKILL-C1 — Mouse control preciso
- **Prioridad**: P0 — Fundacional
- **Descripción**: Click simple, doble click y click derecho con precisión a nivel de pixel sobre cualquier elemento detectado. Incluye manejo de coordenadas relativas y absolutas.
- **Requiere**: `SKILL-V1` (detección UI para saber dónde hacer click)
- **Habilita**: `form_fill`, `drag_drop`, `browser_navigation`, `game_control`
- **Verificación**: `click_registered == True AND target_element_activated == True`
- **Tags**: `control`, `desktop`
- **Nivel objetivo Gen 1.1a**: Parte del skill `desktop-first`, Nivel 4
- **Notas de implementación**: Base de `desktop-first`. Debe fallar gracefully y activar recovery si click no registra en 3 intentos.

---

### SKILL-C2 — Keyboard input
- **Prioridad**: P0 — Fundacional
- **Descripción**: Tipeo de texto arbitrario, shortcuts de sistema (Ctrl+C/V/Z/A/S), teclas de función, combinaciones especiales y secuencias de navegación (Tab, Enter, Escape, flechas).
- **Requiere**: Ningún prerrequisito
- **Habilita**: `form_fill`, `document_edit`, `search_queries`, `game_movement_keys`
- **Verificación**: `text_appeared_in_field == True AND content_matches_input == True`
- **Tags**: `control`, `desktop`
- **Nivel objetivo**: 100% fidelidad de input, ≤50ms latencia por keystroke
- **Notas de implementación**: Distinguir entre `type_text()` (para texto), `press_key()` (para teclas únicas) y `hotkey()` (para combinaciones). Separar en tres métodos.

---

### SKILL-C3 — Drag & Drop
- **Prioridad**: P1 — Core
- **Descripción**: Arrastrar archivos, carpetas, ventanas y elementos de UI desde una posición origen a una destino con verificación de éxito.
- **Requiere**: `SKILL-C1` (mouse control), `SKILL-V4` (detección de cambio de estado)
- **Habilita**: `file_operations_advanced`, `window_management`, `game_item_management`
- **Verificación**: `element_at_destination == True AND source_empty_or_moved == True`
- **Tags**: `control`, `filesystem`
- **Nivel objetivo**: ≥90% success rate, fallback a `explorer_fallback` si falla 2x
- **Notas de implementación**: Parte crítica del gate 2→3 de `desktop-first`. Implementar con mousedown → move → mouseup con delay entre cada paso.

---

### SKILL-C4 — Scroll & navegación vertical
- **Prioridad**: P1 — Core
- **Descripción**: Desplazarse en páginas web largas, listas, documentos y menús para alcanzar contenido por debajo del viewport. Incluye scroll suave y scroll hasta elemento específico.
- **Requiere**: `SKILL-C1` (mouse control)
- **Habilita**: `research_deep_reading`, `full_page_extraction`, `long_document_edit`
- **Verificación**: `target_element_visible == True AND element_y < viewport_height`
- **Tags**: `control`, `research`
- **Nivel objetivo**: ≥95% éxito alcanzando elementos objetivo en páginas de hasta 10x viewport
- **Notas de implementación**: Combinar con `SKILL-V4` para detectar cuándo el scroll llegó al destino o al final de la página.

---

### SKILL-C5 — Clipboard management
- **Prioridad**: P1 — Core
- **Descripción**: Leer contenido actual del clipboard y escribir texto arbitrario en él. Usado como estrategia de fallback cuando acción directa de typing falla.
- **Requiere**: `SKILL-C2` (keyboard input para paste)
- **Habilita**: `recovery_engine`, `copy_to_clipboard_fallback`, `cross_app_data_transfer`
- **Verificación**: `clipboard_content == expected_text`
- **Tags**: `control`, `recovery`
- **Nivel objetivo**: 100% fidelidad — si falla este fallback, el agente está bloqueado
- **Notas de implementación**: `fallback_used = "copy_to_clipboard"` en `TrainingScenarioResult`. Siempre disponible como último recurso antes de `manual`.

---

## DOMINIO 3 — INVESTIGACIÓN

**Propósito**: Adquirir conocimiento externo confiable de múltiples fuentes.  
**Priority rank en scheduler**: 1 (co-prioridad con visión)  
**Family mapping**: `research`  
**Estado actual**: Débil (55% success) — prioridad alta de mejora

### SKILL-R1 — Búsqueda web multi-query
- **Prioridad**: P0 — Fundacional para Gen 1.5
- **Descripción**: Lanzar múltiples búsquedas en paralelo o secuencia sobre un mismo tema, sintetizar resultados de diferentes motores/fuentes y eliminar duplicados.
- **Requiere**: `SKILL-C1` (mouse), `SKILL-C2` (keyboard), navegación de browser
- **Habilita**: `curriculum_generation`, `knowledge_base_building`, `research_to_doc`
- **Verificación**:
  ```python
  verified = (
      len(results) >= min_sources
      and unique_sources >= 3
      and any(result["quality_score"] >= 0.7 for result in results)
  )
  ```
- **Tags**: `research`, `learning`
- **Nivel objetivo Gen 1.1b**: Nivel 4 (≥3 URLs por sesión, ≥5 hechos únicos verificados)
- **Notas de implementación**: Base del `TaskAnalyzer` en Gen 1.5. Sin esto, el sistema no puede auto-investigar nuevos objetivos.

---

### SKILL-R2 — Descarte de fuentes pobres
- **Prioridad**: P1 — Core
- **Descripción**: Evaluar calidad de una página antes de leerla completamente: detectar páginas de ads, contenido superficial, spam SEO, paywalls y páginas sin información útil.
- **Requiere**: `SKILL-R1` (búsqueda web), `SKILL-V2` (OCR para leer snippets)
- **Habilita**: `research_quality_control`, `efficient_research`, `clean_knowledge_base`
- **Verificación**: `precision_discard >= 0.70` (70% de páginas descartadas eran realmente pobres)
- **Tags**: `research`, `quality`
- **Nivel objetivo Gen 1.1b**: ≥70% precision en descarte
- **Notas de implementación**: El `PageUsefulnessClassifier` de `core/models/page_usefulness_classifier.py`. Heurístico primero, ONNX después.

---

### SKILL-R3 — Extracción estructurada
- **Prioridad**: P1 — Core
- **Descripción**: Parsear tablas, listas numeradas, definiciones, steps y datos de páginas web en formatos estructurados (dict, list, JSON) reutilizables por el sistema.
- **Requiere**: `SKILL-R1` (búsqueda web), `SKILL-V2` (OCR), `SKILL-C4` (scroll)
- **Habilita**: `knowledge_base_building`, `structured_learning_materials`, `curriculum_data`
- **Verificación**: `parsed_structure != {} AND len(facts) >= 3 AND format_valid == True`
- **Tags**: `research`, `data`
- **Nivel objetivo**: ≥85% extracción correcta de estructura en páginas bien formateadas
- **Notas de implementación**: Priorizar extracción de: pasos ordenados, tablas comparativas, definiciones clave. Ignorar sidebars y navigation.

---

### SKILL-R4 — Verificación cruzada
- **Prioridad**: P1 — Core
- **Descripción**: Confirmar un hecho o dato en mínimo 3 fuentes independientes antes de almacenarlo en el knowledge base como verdadero.
- **Requiere**: `SKILL-R1` (multi-query), `SKILL-R3` (extracción)
- **Habilita**: `trusted_knowledge_base`, `reliable_curriculum`, `fact_confidence_scoring`
- **Verificación**: `sources_confirming >= 3 AND sources_contradicting == 0`
- **Tags**: `research`, `quality`
- **Nivel objetivo**: Aplicar a todos los hechos marcados como `confidence: high` en knowledge base
- **Notas de implementación**: Un hecho con solo 1-2 fuentes se marca `confidence: medium`. Solo `confidence: high` alimenta el curriculum planner.

---

### SKILL-R5 — Research to document
- **Prioridad**: P1 — Core
- **Descripción**: Tomar el resultado de una sesión de investigación y guardarlo como documento estructurado, verificable y reutilizable en sesiones futuras.
- **Requiere**: `SKILL-R3` (extracción), `SKILL-V3` (checksum), filesystem operations
- **Habilita**: `persistent_learning`, `curriculum_planner_input`, `knowledge_reuse`
- **Verificación**:
  ```python
  verified = (
      os.path.exists(document_path)
      and os.path.getsize(document_path) >= 5120  # 5KB mínimo
      and len([kw for kw in keywords if kw.lower() in content.lower()]) >= 3
      and unique_facts_count >= 5
  )
  ```
- **Tags**: `research`, `filesystem`
- **Nivel objetivo Gen 1.1b**: 100% de sesiones de investigación producen documento verificable
- **Notas de implementación**: Parte del `ResearchVerifier`. Ver `core/verification_research.py`.

---

## DOMINIO 4 — APRENDIZAJE AUTÓNOMO

**Propósito**: Planificar curricula, ejecutar entrenamiento y promover skills automáticamente.  
**Priority rank en scheduler**: Variable (depende de debilidades actuales)  
**Family mapping**: `research` + infraestructura core

### SKILL-L1 — Task analysis
- **Prioridad**: P0 — Core de Gen 1.5
- **Descripción**: Dado un objetivo en lenguaje natural ("aprende a jugar Minecraft"), descomponerlo automáticamente en skills necesarios, prerrequisitos y estimación de tiempo.
- **Requiere**: `SKILL-R1` (para investigar objetivos desconocidos)
- **Habilita**: `curriculum_planning`, `autonomous_learning`, `skill_gap_analysis`
- **Código base**: `core/task_analysis.py` — clase `TaskAnalyzer`
- **Verificación**: `len(required_skills) >= 1 AND estimated_days > 0 AND prerequisites_valid == True`
- **Tags**: `learning`, `planning`
- **Nivel objetivo**: Detección correcta en ≥5 tipos de objetivos diferentes, estimación dentro de ±50%
- **Notas de implementación**: Empezar con 10+ templates hardcoded (minecraft, python, terraria, web_automation, etc). Generic analysis como fallback vía investigación.

---

### SKILL-L2 — Curriculum planning
- **Prioridad**: P0 — Core de Gen 1.5
- **Descripción**: Ordenar el conjunto de skills requeridos según sus dependencias (topological sort), agruparlos en fases lógicas y generar escenarios de práctica por skill.
- **Requiere**: `SKILL-L1` (task analysis), `SKILL-DEPS` (knowledge de dependencias entre skills)
- **Habilita**: `self_training_execution`, `phased_learning`, `logical_skill_ordering`
- **Código base**: `core/curriculum_planner.py` — clase `CurriculumPlanner`
- **Verificación**: `no_cycles_in_graph == True AND phases_ordered_correctly == True AND min_scenarios_per_skill >= 2`
- **Tags**: `learning`, `planning`
- **Nivel objetivo**: Topological sort sin ciclos, ≥2 scenarios por skill, fases agrupadas lógicamente
- **Notas de implementación**: Usar algoritmo de Kahn para topological sort. Si hay ciclos, marcar como error y alertar.

---

### SKILL-L3 — Self-training loop
- **Prioridad**: P0 — Motor central del sistema
- **Descripción**: Ejecutar ciclos de práctica automatizados: seleccionar skill, ejecutar scenario, verificar resultado, registrar `TrainingScenarioResult`, actualizar métricas.
- **Requiere**: `SKILL-L2` (curriculum), `SKILL-L5` (scheduler), todos los verifiers
- **Habilita**: `skill_level_progression`, `autonomous_mastery`, `infinite_training`
- **Código base**: `core/training_loop_infinite.py` — clase `InfiniteTrainingLoop`
- **Verificación**: `TrainingScenarioResult.verified == True AND result.evidence != {} AND result.failure_stage registered`
- **Tags**: `learning`, `training`
- **Nivel objetivo**: Ejecutar ≥50 sesiones sin intervención manual, 0% sesiones sin `TrainingScenarioResult` completo
- **Notas de implementación**: TODOS los campos de `TrainingScenarioResult` son obligatorios. Sesión sin `verified_outcome` o `failure_stage` = sesión inválida.

---

### SKILL-L4 — Skill promotion gates
- **Prioridad**: P1 — Core
- **Descripción**: Evaluar automáticamente si un skill cumple los criterios de calidad para ser promovido al siguiente nivel (success rate, fallback rate, sesiones mínimas, días mínimos).
- **Requiere**: `SKILL-L3` (training loop con historial)
- **Habilita**: `level_5_skills`, `ops_ready_skills`, `quality_assurance`
- **Código base**: `core/verification_desktop_first.py` + `core/verification_research.py` — `SkillGate`
- **Verificación**:

  | Gate | Min Success | Max Fallback | Min Sessions | Min Days |
  |------|------------|--------------|--------------|----------|
  | 1→2  | 100%       | 0%           | 5            | 3        |
  | 2→3  | 90%        | 0-10%        | 8-10         | 5        |
  | 3→4  | 80%        | 25%          | 12-15        | 7        |
  | 4→5  | 70%        | 25%          | 50           | 14       |
  | 5→Ops| 65%        | <20%         | —            | —        |

- **Tags**: `learning`, `quality`
- **Nivel objetivo**: 0 promociones falsas — validar 10 manualmente al implementar
- **Notas de implementación**: `gate_passed = True` solo cuando TODOS los criterios se cumplen simultáneamente. No promediar.

---

### SKILL-L5 — Weighted scheduler
- **Prioridad**: P1 — Core
- **Descripción**: Calcular qué skill entrenar en cada sesión usando una fórmula ponderada que balancea prioridad, debilidades, estancamiento, frescura y emergencias operacionales.
- **Requiere**: `SKILL-L3` (historial de sesiones)
- **Habilita**: `multi_domain_balance`, `weakness_focused_training`, `stagnation_prevention`
- **Código base**: `core/training_scheduler.py` — clase `SkillScheduler`
- **Fórmula**:
  ```python
  score = (
      0.30 * priority_score        # (9 - rank) / 8
    + 0.35 * weakness_score        # (1 - success_rate) * (1 + fallback_rate)
    + 0.15 * stagnation_score      # log(1 + days_stagnant/2) / log(8)
    + 0.10 * freshness_score       # Decay temporal
    + 0.10 * operational_score     # Emergencias / skills bloqueantes
  )
  ```
- **Tags**: `learning`, `scheduling`
- **Nivel objetivo**: Cambio en ranking de skills cada sesión, ≥10 sesiones por dominio en 2 semanas
- **Notas de implementación**: Usar `max_score` por dominio cada sesión. Los 8 dominios deben recibir atención en proporción a sus debilidades.

---

### SKILL-L6 — Knowledge base management
- **Prioridad**: P1 — Core
- **Descripción**: Almacenar, indexar, deduplicar y reutilizar conocimiento investigado entre sesiones, evitando re-investigar información ya conocida.
- **Requiere**: `SKILL-R5` (research to document), filesystem operations
- **Habilita**: `faster_learning`, `knowledge_reuse`, `cross_objective_learning`
- **Verificación**: `knowledge_retrieved_correctly == True AND no_duplicate_entries == True AND lookup_time < 100ms`
- **Tags**: `learning`, `memory`
- **Nivel objetivo**: ≥80% de investigaciones previas reutilizadas sin repetir búsqueda web
- **Notas de implementación**: Implementar índice simple (JSON o SQLite) mapeando `topic → document_path → confidence_level`. No sobre-ingeniería al inicio.

---

## DOMINIO 5 — RESOLUCIÓN DE PROBLEMAS

**Propósito**: Detectar fallos, recuperarse y adaptarse sin intervención humana.  
**Priority rank en scheduler**: 2 (critico para uptime)  
**Family mapping**: `vision` + todos los dominios

### SKILL-P1 — Recovery engine
- **Prioridad**: P0 — Fundacional
- **Descripción**: Detectar en qué etapa falló una acción (detection / action / verification) y seleccionar automáticamente la estrategia de recuperación con mayor probabilidad de éxito según historial.
- **Requiere**: `SKILL-V4` (detección de estado), `SKILL-P2` (fallback strategies)
- **Habilita**: `resilient_training`, `zero_manual_intervention`, `self_healing_system`
- **Código base**: `core/recovery_engine.py` — clase `RecoveryEngine`
- **Playbooks**:
  ```
  Vision domain:
    detection_lost      → retry_with_focus → ocr_fallback → manual
    action_failed_3x    → copy_clipboard → explorer_fallback → manual_position
    verification_failed → verify_again → check_alt_location → inspect_fs

  Research domain:
    page_timeout        → retry_url → search_keywords → cache
    poor_quality        → skip_page → search_specific → ocr_screenshot
    ocr_failed          → retry_ocr → capture_again → manual_entry
  ```
- **Tags**: `recovery`, `resilience`
- **Nivel objetivo**: ≥60% recovery success rate por dominio
- **Notas de implementación**: `RecoveryAttempt` debe registrar: `failure_stage → chosen_strategy → recovery_result`. Auditable.

---

### SKILL-P2 — Fallback strategies
- **Prioridad**: P0 — Fundacional
- **Descripción**: Repertorio de estrategias alternativas disponibles cuando la acción primaria falla. Cada acción crítica debe tener ≥3 alternativas ordenadas por probabilidad de éxito.
- **Requiere**: `SKILL-C5` (clipboard), `SKILL-V2` (OCR), `SKILL-C1` (mouse)
- **Habilita**: `recovery_engine`, `graceful_degradation`, `blocked_state_prevention`
- **Estrategias disponibles**:
  | Estrategia | Cuándo usar | Costo |
  |-----------|-------------|-------|
  | `retry_with_focus` | Elemento no encontrado, 1er fallo | Bajo |
  | `ocr_fallback` | UI no expone texto por API | Medio |
  | `copy_to_clipboard` | Typing directo falla 2x | Bajo |
  | `explorer_fallback` | Drag & drop falla | Medio |
  | `search_keywords` | URL no responde | Bajo |
  | `manual_position` | Coordenadas absolutas como último recurso | Alto |
- **Tags**: `recovery`, `control`
- **Nivel objetivo**: 100% de skills P0/P1 con ≥3 fallbacks implementados
- **Notas de implementación**: Registrar `fallback_used` en `TrainingScenarioResult`. Máximo `"success_with_fallback"` no es `"success"` — contar separado.

---

### SKILL-P3 — Error classification
- **Prioridad**: P1 — Core
- **Descripción**: Distinguir automáticamente entre errores transitorios (reintentar), sistémicos (cambiar estrategia) y bloqueantes (escalar). Evitar loops infinitos de reintentos inútiles.
- **Requiere**: `SKILL-V4` (detección de estado), `SKILL-P1` (recovery engine con historial)
- **Habilita**: `smart_recovery`, `no_infinite_retry_loops`, `escalation_detection`
- **Clasificación**:
  ```
  TRANSITORIO  → mismo error <3 veces seguidas → reintentar con delay
  SISTÉMICO    → mismo error ≥3 veces → cambiar estrategia
  BLOQUEANTE   → no hay más fallbacks disponibles → marcar status="blocked", continuar siguiente skill
  ```
- **Tags**: `recovery`, `intelligence`
- **Nivel objetivo**: 0 loops infinitos, <5% sesiones terminan en `status="blocked"` innecesariamente
- **Notas de implementación**: Implementar contador por `(skill_id, failure_stage, error_type)` en contexto de sesión. Reset al cambiar de skill.

---

### SKILL-P4 — Adaptive retry logic
- **Prioridad**: P1 — Core
- **Descripción**: Usar el historial de éxito de cada estrategia de recuperación para aprender cuál funciona mejor en cada contexto, ordenando opciones por `success_rate` de las últimas 10 sesiones.
- **Requiere**: `SKILL-P1` (recovery engine), `SKILL-L3` (training loop con historial persistente)
- **Habilita**: `self_improving_recovery`, `context_aware_fallbacks`, `recovery_learning`
- **Verificación**: `chosen_strategy == argmax(success_rate_last_10_sessions)` para ≥80% de decisiones
- **Tags**: `recovery`, `learning`
- **Nivel objetivo**: Recovery success rate mejora semana a semana (medible)
- **Notas de implementación**: `ModelAssistDecision` audita esta decisión: `model_id → score → used? → fallback_reason`. Ver dataclass en `core/training_models.py`.

---

### SKILL-P5 — Verification pipeline
- **Prioridad**: P0 — Fundacional
- **Descripción**: Confirmar el resultado de cada acción antes de reportar éxito, usando la combinación apropiada de verificación filesystem, visual (screenshot diff) y semántica (contenido correcto).
- **Requiere**: `SKILL-V3` (checksum), `SKILL-V2` (OCR para verificación semántica)
- **Habilita**: `trusted_results`, `no_false_positives`, `gate_evaluation_integrity`
- **Tipos de verificación**:
  ```python
  # Filesystem (desktop-first Nivel 4)
  verified_fs = os.path.exists(path) and size_ok and checksum_ok

  # Semántica (investigar Nivel 4)
  verified_semantic = file_exists and size >= 5120 and keywords_present >= 3 and unique_facts >= 5

  # Visual (cualquier acción UI)
  verified_visual = screenshot_after != screenshot_before and expected_element_visible
  ```
- **Tags**: `verification`, `quality`
- **Nivel objetivo**: 100% de sesiones con `verified_outcome` completo en `TrainingScenarioResult`
- **Notas de implementación**: Si `verified == False`, marcar `failure_stage = "verification"` y activar recovery. Nunca reportar éxito sin verificar.

---

## DOMINIO 6 — GAMING & APLICACIONES

**Propósito**: Interactuar con software complejo, juegos y flujos de trabajo avanzados.  
**Priority rank en scheduler**: 4-5  
**Family mapping**: `game` + `application` + `browser`  
**Nota**: Este dominio requiere todos los dominios 1-5 estables antes de implementar.

### SKILL-G1 — Game state recognition
- **Prioridad**: P1 — Core (para Gen 2.5)
- **Descripción**: Leer en tiempo real el estado de un juego desde la pantalla: puntos de vida, inventario, minimapa, cooldowns, posición de enemigos, recursos disponibles.
- **Requiere**: `SKILL-V2` (OCR), `SKILL-V5` (template matching), `SKILL-V4` (cambios de estado)
- **Habilita**: `game_decisions`, `combat_logic`, `survival_strategy`
- **Verificación**: `state_parsed_correctly >= 90% AND update_latency < 100ms`
- **Tags**: `gaming`, `vision`
- **Nivel objetivo Gen 2.5**: Nivel 3 en Minecraft + Terraria (los dos objetivos del roadmap)
- **Notas de implementación**: Crear `GameStateParser` con templates específicos por juego. No reutilizar directamente entre juegos.

---

### SKILL-G2 — Real-time input control
- **Prioridad**: P1 — Core (para gaming)
- **Descripción**: Ejecutar secuencias combinadas de teclas y movimientos de mouse con timing preciso (≤50ms de latencia), necesario para combat, parkour y acciones de juego.
- **Requiere**: `SKILL-C1` (mouse), `SKILL-C2` (keyboard)
- **Habilita**: `combat_execution`, `movement_precision`, `skill_combos`
- **Verificación**: `action_latency <= 50ms AND sequence_completed == True AND game_response_registered == True`
- **Tags**: `gaming`, `control`
- **Nivel objetivo**: ≤50ms latencia en 90% de inputs, 0% dropped inputs
- **Notas de implementación**: Usar threading separado para input loop en gaming. No bloquear el verification pipeline.

---

### SKILL-G3 — Goal decomposition in-game
- **Prioridad**: P2 — Avanzado
- **Descripción**: Dividir un objetivo de alto nivel en juego ("craftear una espada de diamante") en sub-tareas ejecutables con dependencias claras y verificación de completitud.
- **Requiere**: `SKILL-G1` (game state), `SKILL-L1` (task analysis), `SKILL-L2` (curriculum planning)
- **Habilita**: `strategic_gameplay`, `multi_step_quest_completion`, `autonomous_game_progression`
- **Verificación**: `subtasks_ordered_correctly == True AND all_subtasks_completable == True`
- **Tags**: `gaming`, `planning`
- **Nivel objetivo Gen 2.5**: Completar 5 cadenas de crafting end-to-end autónomamente
- **Notas de implementación**: Reutilizar `TaskAnalyzer` y `CurriculumPlanner` de Gen 1.5. El juego es solo otro "objetivo" para el sistema autónomo.

---

### SKILL-G4 — Application workflow automation
- **Prioridad**: P2 — Avanzado
- **Descripción**: Automatizar flujos de trabajo repetitivos en aplicaciones de productividad (Excel, Word, Photoshop, IDEs): macros implícitas, navegación de menús, export/import de archivos.
- **Requiere**: `SKILL-V1` (detección UI), `SKILL-C1` + `SKILL-C2` (control), `SKILL-P1` (recovery)
- **Habilita**: `productivity_automation`, `batch_processing`, `tool_integration`
- **Verificación**: `workflow_completed == True AND output_file_valid == True AND no_manual_intervention == True`
- **Tags**: `utility`, `automation`
- **Nivel objetivo Gen 3**: ≥5 aplicaciones con workflow automatizado verificable
- **Notas de implementación**: Gen 3+ use case. Priorizar aplicaciones que aparecen frecuentemente en objetivos del usuario.

---

### SKILL-G5 — Form filling & web interaction
- **Prioridad**: P1 — Core
- **Descripción**: Completar formularios web con validación, navegar en SPAs (React, Vue, Angular), hacer click en elementos dinámicos cargados por JavaScript.
- **Requiere**: `SKILL-C1` (mouse), `SKILL-C2` (keyboard), `SKILL-V4` (cambios de estado para await carga)
- **Habilita**: `web_automation`, `data_entry_automation`, `online_research_forms`
- **Verificación**: `form_submitted == True AND confirmation_received == True AND data_in_server == True`
- **Tags**: `browser`, `utility`
- **Nivel objetivo**: ≥95% success rate en formularios estándar, ≥75% en SPAs con carga dinámica
- **Notas de implementación**: Esperar carga con `SKILL-V4` antes de intentar interactuar. Timeout configurable, default 5s.

---

### SKILL-G6 — Multi-window management
- **Prioridad**: P2 — Avanzado
- **Descripción**: Gestionar múltiples ventanas y aplicaciones simultáneamente, cambiar entre ellas sin perder contexto, transferir datos entre apps.
- **Requiere**: Todos los skills de control + `SKILL-V4` (detección de ventana activa)
- **Habilita**: `complex_multi_app_workflows`, `parallel_task_execution`, `cross_app_data_transfer`
- **Verificación**: `active_window_correct == True AND context_preserved == True AND data_transferred_correctly == True`
- **Tags**: `utility`, `desktop`
- **Nivel objetivo Gen 3**: Flujos de ≥3 apps simultáneas sin pérdida de contexto
- **Notas de implementación**: Implementar `WindowManager` con stack de contexto por ventana. Guardar estado antes de cambiar.

---

## CADENA CRÍTICA DE DEPENDENCIAS

```
[SKILL-V1] Detección UI
    ↓
[SKILL-C1] Mouse control ──────────────→ [SKILL-C3] Drag & Drop
    ↓                                          ↓
[SKILL-C2] Keyboard ──→ Browser nav    [SKILL-V3] Checksum
    ↓                       ↓                  ↓
[SKILL-R1] Búsqueda web    [SKILL-G5] Forms   [SKILL-P5] Verification
    ↓                                          ↓
[SKILL-R5] Research→Doc ──────────────→ [SKILL-L3] Training loop
    ↓                                          ↓
[SKILL-L1] Task analysis               [SKILL-L4] Skill gates
    ↓                                          ↓
[SKILL-L2] Curriculum planning ────────→ NIVEL 5 / OPS READY
    ↓
[SKILL-L3] Self-training loop (GEN 1.5 COMPLETO)
    ↓
[SKILL-G1..G6] Gaming & Apps (GEN 2.5+)
```

**Regla de oro**: Nada en la cadena puede saltarse. Si `SKILL-V1` es inestable, todo lo que depende de él lo será también.

---

## MATRIZ DE DEPENDENCIAS COMPLETA

| Skill | Requiere | Habilita | Prioridad | Gen |
|-------|----------|----------|-----------|-----|
| V1 — Detección UI | — | C1, C3, V2, V4, V5 | P0 | 1.1a |
| V2 — OCR | V1 | R1, R3, P5, G1 | P0 | 1.1a |
| V3 — Checksum | Filesystem | P5, L4 | P0 | 1.1a |
| V4 — Cambios de estado | V1 | P1, P3, G5 | P1 | 1.1b |
| V5 — Template matching | V1 | G1, dynamic_UI | P1 | 2.5 |
| C1 — Mouse | V1 | C3, C4, G5, R1 | P0 | 1.1a |
| C2 — Keyboard | — | C5, G5, R1 | P0 | 1.1a |
| C3 — Drag & Drop | C1, V4 | file_ops_adv | P1 | 1.1a |
| C4 — Scroll | C1 | R1_deep, doc_edit | P1 | 1.1b |
| C5 — Clipboard | C2 | P1, P2 | P1 | 1.1a |
| R1 — Búsqueda web | C1, C2 | R3, R5, L1 | P0 | 1.1b |
| R2 — Descarte fuentes | R1, V2 | research_quality | P1 | 1.1b |
| R3 — Extracción | R1, V2, C4 | R5, L2 | P1 | 1.1b |
| R4 — Verificación cruzada | R1, R3 | trusted_KB | P1 | 1.1b |
| R5 — Research→Doc | R3, V3 | L6, curriculum | P1 | 1.1b |
| L1 — Task analysis | R1 | L2, G3 | P0 | 1.5 |
| L2 — Curriculum planning | L1 | L3, phased_learning | P0 | 1.5 |
| L3 — Self-training loop | L2, L5, verifiers | L4, autonomy | P0 | 1.1c |
| L4 — Skill gates | L3 | level_5, ops_ready | P1 | 1.1c |
| L5 — Scheduler | L3 | multi_domain_balance | P1 | 1.1c |
| L6 — Knowledge base | R5, filesystem | faster_learning | P1 | 1.5 |
| P1 — Recovery engine | V4, P2 | resilience | P0 | 1.1a |
| P2 — Fallback strategies | C5, V2, C1 | P1, graceful_deg | P0 | 1.1a |
| P3 — Error classification | V4, P1 | smart_recovery | P1 | 1.1b |
| P4 — Adaptive retry | P1, L3 | self_improving | P1 | 1.1c |
| P5 — Verification pipeline | V3, V2 | no_false_positives | P0 | 1.1a |
| G1 — Game state | V2, V5, V4 | game_decisions | P1 | 2.5 |
| G2 — Real-time input | C1, C2 | combat, movement | P1 | 2.5 |
| G3 — Goal decomp in-game | G1, L1, L2 | strategic_play | P2 | 2.5 |
| G4 — App workflow | V1, C1, C2, P1 | productivity | P2 | 3+ |
| G5 — Form filling | C1, C2, V4 | web_automation | P1 | 1.1b |
| G6 — Multi-window | Todos control + V4 | complex_workflows | P2 | 3+ |

---

## ROADMAP DE IMPLEMENTACIÓN POR FASE

### Gen 1.1a — 2 semanas (Skills base)
**Objetivo**: Sistema que puede actuar sobre el desktop con verificación confiable.

- [ ] **V1** — Detección de elementos UI → Nivel 4
- [ ] **V2** — OCR básico → Nivel 3
- [ ] **V3** — Checksum verification → 100%
- [ ] **C1** — Mouse control → Nivel 4
- [ ] **C2** — Keyboard input → Nivel 4
- [ ] **C3** — Drag & Drop → Nivel 3
- [ ] **C5** — Clipboard fallback → Funcional
- [ ] **P2** — Fallback strategies → 3 estrategias por dominio
- [ ] **P5** — Verification pipeline → 100% cobertura

**Criterio de salida**:
- `desktop-first` Nivel 4: ≥20 sesiones, 70%+ success, ≤30% fallback
- Verificación filesystem 100% correcta
- Dataset: ≥50 `TrainingScenarioResult` completos

---

### Gen 1.1b — 2 semanas (Investigación)
**Objetivo**: Sistema que puede investigar y producir documentos verificables.

- [ ] **C4** — Scroll → Funcional
- [ ] **V4** — Detección de cambios → Nivel 3
- [ ] **R1** — Búsqueda web multi-query → Nivel 4
- [ ] **R2** — Descarte de fuentes → ≥70% precision
- [ ] **R3** — Extracción estructurada → Nivel 3
- [ ] **R4** — Verificación cruzada → Implementada
- [ ] **R5** — Research to document → 100% verificable
- [ ] **G5** — Form filling básico → Funcional
- [ ] **P1** — Recovery engine → Playbooks activos
- [ ] **P3** — Error classification → Implementada

**Criterio de salida**:
- `investigar` Nivel 4: ≥15 sesiones, documentos ≥5KB verificables
- Descarte páginas pobres: ≥70% precision
- Multi-fuente: ≥5 sesiones con ≥3 URLs diferentes

---

### Gen 1.1c — 3 semanas (Loop infinito)
**Objetivo**: Sistema que rota autónomamente entre dominios y mejora solo.

- [ ] **L3** — Self-training loop → Funcional (8 dominios)
- [ ] **L4** — Skill gates → 0 promociones falsas
- [ ] **L5** — Weighted scheduler → Formula implementada
- [ ] **P4** — Adaptive retry → Aprendiendo de historial

**Criterio de salida**:
- Loop rota entre 8 dominios cada sesión
- ≥10 sesiones por dominio en 2 semanas
- ≥2 skills alcanzaron Nivel 5 (automático)
- Cero promociones falsas

---

### Gen 1.5 — 2 semanas (Autonomía completa)
**Objetivo**: El sistema puede aprender cualquier cosa sin intervención.

- [ ] **L1** — Task analysis → 10+ templates
- [ ] **L2** — Curriculum planning → Topological sort
- [ ] **L6** — Knowledge base → Persistente y reutilizable
- [ ] **Integración**: `AutonomousLearningSystem.learn(objetivo)` funciona end-to-end

**Criterio de salida**:
- 3 objetivos diferentes completados autónomamente
- Success rate ≥65% en cada uno
- Cero intervención manual

---

### Gen 2.5 — 6-12 semanas (Gaming)
**Objetivo**: Agente capaz de jugar Minecraft y Terraria autónomamente.

- [ ] **V5** — Template matching → Sprites de juego
- [ ] **G1** — Game state recognition → Minecraft + Terraria
- [ ] **G2** — Real-time input → ≤50ms latencia
- [ ] **G3** — Goal decomposition in-game → Chains de 5+ pasos

---

## CRITERIOS DE PROMOCIÓN POR SKILL

Todo skill sigue este proceso de evaluación antes de marcar como "estable":

```python
# Criterio universal de estabilidad (P0 skills)
stable = (
    success_rate >= gate.min_success_rate
    and fallback_rate <= gate.max_fallback_rate
    and verified_sessions >= gate.min_verified_sessions
    and days_practicing >= gate.min_days
    and no_regressions_last_5_sessions == True
)
```

**Definición de regresión**: Si un skill que estaba en Nivel N registra 3 sesiones consecutivas por debajo del umbral de Nivel N-1, se considera regresión y requiere re-entrenamiento.

---

## CHECKLIST DE IMPLEMENTACIÓN

### Archivos a crear (en orden de prioridad)

| Archivo | Skills que implementa | Prioridad |
|---------|----------------------|-----------|
| `core/training_models.py` | TrainingScenarioResult, SkillGate, RecoveryAttempt, ModelAssistDecision | **P0** |
| `core/verification_desktop_first.py` | V3, P5 (filesystem) | **P0** |
| `core/verification_research.py` | R5, P5 (semántica) | **P0** |
| `core/recovery_engine.py` | P1, P2, P3 | **P0** |
| `core/training_scheduler.py` | L5 | **P0** |
| `core/training_loop_infinite.py` | L3, L4 | **P1** |
| `core/skill_family_mapping.py` | TrainableDraft factory | **P1** |
| `core/task_analysis.py` | L1 | **P1** (Gen 1.5) |
| `core/curriculum_planner.py` | L2 | **P1** (Gen 1.5) |
| `core/autonomous_learning_system.py` | Integración L1+L2+L3 | **P1** (Gen 1.5) |
| `core/knowledge_base.py` | L6 | **P1** (Gen 1.5) |
| `core/models/ui_target_ranker.py` | V1 neuronal | **P2** |
| `core/models/page_usefulness_classifier.py` | R2 neuronal | **P2** |

### Métricas a monitorear en cada sesión

| Métrica | Umbral OK | Alarma si |
|---------|-----------|-----------|
| `desktop-first` success_rate | ≥70% | <60% dos sesiones seguidas |
| `investigar` success_rate | ≥65% | <55% dos sesiones seguidas |
| Recovery success_rate | ≥60% por dominio | <50% |
| Verification latency | <500ms | >1000ms |
| Gate promotion rate | ≥1 skill/semana | 0 en 2 semanas |
| Sessions with blocked status | <5% | >10% |
| False promotions | 0 | Cualquiera |

---

## SKILLS VIVAS DEL LOOP INFINITO

Esta sección describe solo las skills que ya deben poder resolverse, ejecutarse y verificarse dentro de `core/training_loop_infinite.py`, sin depender de una promesa futura.

| Dominio del loop | Skill entrenable | Escenarios base | Estado esperado |
|---------|----------------------|-----------|-----------------|
| `vision/detection` | `mouse` | `ui_detect_visible`, `mouse_click_visible`, `ui_detect_distracted` | Activo |
| `selection/workflow` | `mouse` | `desktop_drag_constrained`, `desktop_drag_real_verify`, `desktop_recovery_verified` | Activo |
| `research` | `investigar` | `research_single_source`, `research_structured_extract`, `research_to_document` | Activo |
| `browser` | `brave` | `browser_open_google`, `browser_search_result` | Activo |
| `browser` | `youtube` | `browser_form_fill` | Activo |
| `file_manager/explorer` | `explorer` | `explorer_open_workspace`, `explorer_select_item`, `explorer_move_verified` | Activo |
| `file_manager/explorer` | `window management` | `explorer_window_layout_stable`, `explorer_window_layout_repair`, `explorer_window_occlusion_recovery` | Activo |
| `document_editor` | `notepad` | `document_write_basic`, `document_replace_text`, `document_save_verified` | Activo |
| `application_workflow` | `youtube` | `application_open_verify`, `application_click_target`, `application_goal_workflow` | Activo |
| `game_foundation` | `jugar terraria` | `game_input_foundation`, `game_control_lookup`, `game_goal_chain` | Activo |

### Reglas de integración al loop

- Cada escenario debe declarar `skill_label` real y el loop debe ejecutar esa skill exacta.
- `document_editor` usa `notepad` como ruta base entrenable. `word` no debe bloquear todo el dominio si está en `blocked`.
- `window management` pertenece al dominio `file_manager/explorer` y necesita escenarios propios de layout estable, reparación y recuperación por oclusión.
- Toda skill listada aquí debe resolverse con el engine, producir `TrainingScenarioResult` y quedar asociada a un `scenario_id` verificable.

---

## NOTAS FINALES

**Sobre el orden de implementación**: Los skills P0 son bloqueantes. No avanzar a P1 sin P0 estable. El sistema entero colapsa si V1, C1, P5 o P2 no funcionan correctamente.

**Sobre los fallbacks**: Un `status = "success_with_fallback"` NO es lo mismo que `status = "success"`. Los gates calculan `fallback_rate` separado. Un sistema que siempre usa fallbacks no ha dominado la skill principal.

**Sobre las verificaciones**: El campo `verified_outcome` en `TrainingScenarioResult` es sagrado. Una sesión sin él es una sesión que no existe para el sistema de métricas.

**Sobre Gen 1.5**: Una vez que `AutonomousLearningSystem.learn(objetivo)` funciona, todos los skills de Gaming y Aplicaciones se vuelven adquiribles simplemente diciéndole al sistema qué aprender. Ese es el multiplicador real.

---

**Versión**: 1.0  
**Generado por**: Raphael — Reina de la Sabiduría  
**Estado**: Listo para implementación  
**Siguiente fase**: Gen 1.1a — comenzar con `core/training_models.py`
