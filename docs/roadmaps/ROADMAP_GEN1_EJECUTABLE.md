# Roadmap De Subida De Nivel: Loop Infinito Robusto, Niveles Reales y Arquitectura Híbrida
## VERSIÓN EJECUTABLE - Mayo 2026

---

## RESUMEN EJECUTIVO

El sistema se reorganiza en torno a **entrenamiento continuo verificado**, reemplazando repetición ciega con:
- **Currículum vivo** con escenarios controlados, mixtos y reales
- **Gates verificados** con criterios de salida explícitos
- **Recuperación auditable** registrando causa y estrategia
- **Arquitectura híbrida**: evidencia + verificación + heurísticas → modelos neuronales (apoyo, no reemplazo)

### Orden de Ejecución

1. **Gen 1.1a (Piloto)**: `desktop-first` con gates cerrados, dataset real, verificación operativa
2. **Gen 1.1b (Expansión)**: `investigar` con análisis robusto; integrar con Gen 1.1a
3. **Gen 1.1c (Loop Infinito)**: Scheduler ponderado, todos los dominios
4. **Gen 1.5**: Drafts entrenables, recuperación autónoma
5. **Gen 2**: Modelos neuronales híbridos versionados

---

## PARTE I: CONTRATOS Y ESTRUCTURAS (Implementar Primero)

### 1.1 TrainingScenarioResult - Contrato Base

```python
@dataclass
class TrainingScenarioResult:
    """Resultado estructurado de cualquier práctica o ejecución."""
    
    # Identidad
    skill_id: str                    # "desktop-first", "investigar", etc
    domain: str                      # "vision", "research", "browser", "file_manager", "documents", "application", "game"
    scenario_id: str                 # "desktop_drag_001", "research_multi_source_001"
    session_id: str                  # Vinculación a sesión
    timestamp: int                   # Unix timestamp
    
    # Ejecución
    level: int                       # 1-5
    status: str                      # "success", "success_with_fallback", "failure", "blocked"
    verified: bool                   # ¿Pasó verificación final?
    failure_stage: Optional[str]     # "detection", "action", "verification", None si exitoso
    
    # Recuperación
    fallback_used: Optional[str]     # "explorer_fallback", "copy_to_clipboard", None
    attempted_strategies: List[str]  # ["drag_desktop", "copy_paste", "explorer"]
    chosen_strategy: str             # La que se usó finalmente
    retryable: bool                  # ¿Se puede reintentar?
    
    # Evidencia
    metrics: dict                    # Métricas por dominio (latency, accuracy, etc)
    evidence: dict                   # Artefactos verificables (filepath, screenshot, text_captured, etc)
    verified_outcome: dict           # Lo que se verificó al final
    
    # Auditoría
    error_log: Optional[str]         # Stack trace o detalle de error
    notes: Optional[str]             # Contexto adicional


@dataclass
class SkillGate:
    """Define criterio de promoción para un skill en un nivel."""
    
    skill_id: str
    from_level: int
    to_level: int
    
    # Escenarios requeridos
    required_scenarios: List[str]    # IDs de escenarios que debe pasar
    
    # Criterios numéricos
    min_success_rate: float          # Ej: 0.80 = 80%
    max_fallback_rate: float         # Ej: 0.20 = máx 20%
    min_verified_sessions: int       # Ej: 5 sesiones verificadas
    
    # Tolerancia temporal
    max_days_to_gate: int            # Ej: 14 días para completar gate
    
    # Estado actual
    verified_scenarios_passed: List[str]
    verified_sessions_count: int
    current_success_rate: float
    current_fallback_rate: float
    gate_passed: bool
    gate_passed_date: Optional[int]


@dataclass
class TrainableDraft:
    """Skill nuevo que espera ser entrenado."""
    
    skill_id: str
    skill_name: str
    description: str
    
    # Mapeo a familia existente
    family: str                      # "vision", "research", "browser", "file_manager", "documents", "application", "game"
    
    # Plantillas de escenarios heredadas de la familia
    scenario_templates: List[dict]   # Copiadas de familia, adaptadas
    verification_rules: dict         # Copiadas de familia
    
    # Qué falta
    missing_capabilities: List[str]  # ["specific_ui_pattern", "custom_ocr_region"]
    readiness_blockers: List[str]    # ["awaiting_backend_api", "needs_manual_ui_map"]
    
    # Timeline
    estimated_training_days: int
    created_date: int


@dataclass
class RecoveryAttempt:
    """Auditoría de un reintento después de fallo."""
    
    training_scenario_id: str
    failure_session_id: str
    failure_stage: str               # "detection", "action", "verification"
    failure_reason: str              # Descripción clara del por qué falló
    
    # Decisión de recuperación
    attempted_strategies: List[str]  # ["drag_again", "copy_paste", "explorer"]
    chosen_next_strategy: str
    strategy_reasoning: str          # Por qué se eligió esta estrategia
    
    # Resultado del reintento
    recovery_session_id: str
    recovery_succeeded: bool
    recovery_verified: bool
    
    # Métricas de confianza
    confidence_in_recovery: float    # 0.0-1.0
    is_playbook_decision: bool       # ¿Viene de un playbook registrado?


@dataclass
class ModelAssistDecision:
    """Auditoría de ayuda neuronal en runtime."""
    
    model_id: str                    # "ui_target_ranker_v1", "page_usefulness_v2"
    decision_type: str               # "ranking", "classification", "strategy_suggestion"
    input_type: str                  # "screenshot", "text", "candidates"
    
    # Decisión
    score: float                     # Confianza del modelo (0.0-1.0)
    recommendation: str              # "click_id_123", "page_is_useful", "try_ocr_next"
    used: bool                       # ¿Se usó la recomendación?
    
    # Si no se usó, por qué
    fallback_reason: Optional[str]   # "heuristic_was_higher", "model_confidence_low", "user_override"
    heuristic_score: Optional[float] # Para comparación
    
    # Trazabilidad
    timestamp: int
    session_id: str
```

---

## PARTE II: GEN 1.1A - DESKTOP-FIRST CON GATES CERRADOS

### 2.1 Matriz de Escenarios: desktop-first

**Dominios cubiertos**: `vision/detection`, `selection/workflow`

| Nivel | Escenarios Obligatorios | Métrica de Éxito | Techo Fallback | Notas |
|-------|------|------|------|------|
| **1** | 1. Click en target visible (sin oclusión) | 100% éxito en 5 intentos | 0 fallbacks | Solo candidatos sobre-detectados |
| **2** | 1. Click con distracción visual<br>2. Click en ventana minimizada/reabierta | 90% éxito en 10 intentos | 0 fallbacks | Aún sin complicaciones dinámicas |
| **3** | 1. Drag desktop correctamente posicionado<br>2. Fallo + recovery (click + copy) | 80% éxito en 15 intentos<br>1 recovery mínimo | 2 fallbacks totales | Recuperación es obligatoria demostrarse |
| **4** | 1. Drag en posición real verificada<br>2. Verificación filesystem: archivo llegó a destino<br>3. Metadatos correctos (nombre, tamaño) | 70% éxito en 20 intentos | 3 fallbacks máx | **Verificación hardcodificada**: `os.path.exists(dest) AND file_size == expected` |
| **5** | 1. 10 sesiones sostenidas, 65%+ éxito<br>2. Fallback < 20%<br>3. Sin regresión a Nivel 4 (< 2 fallos seguidos) | Tasa sostenida 65%+ | < 20% | Rol operativo |

**Criterio de salida Gen 1.1a**: 
- ✅ Gen 1.1a cierra cuando: 
  - `desktop-first` tiene Nivel 4 cumplido
  - dataset de ≥50 sesiones capturadas
  - todas las sesiones tienen `TrainingScenarioResult` estructurado
  - verificación filesystem funciona 100% en dataset histórico

### 2.2 Verificación: desktop-first (Con Código)

```python
# Módulo: core/verification_desktop_first.py

class DesktopFirstVerifier:
    """Verifica resultado de drag/click en desktop."""
    
    def verify_level_1_2(self, result: TrainingScenarioResult) -> dict:
        """Nivel 1-2: Solo verificar que hubo acción registrada."""
        return {
            "action_logged": result.evidence.get("action_detected") is not None,
            "timestamp_valid": result.evidence.get("timestamp") is not None
        }
    
    def verify_level_3(self, result: TrainingScenarioResult) -> dict:
        """Nivel 3: Drag o fallback a copy registrado."""
        was_drag = "desktop_drag" in result.attempted_strategies
        had_recovery = "copy_to_clipboard" in result.attempted_strategies
        
        return {
            "had_primary_action": was_drag,
            "had_recovery": had_recovery,
            "recovery_registered": result.fallback_used is not None if not was_drag else True
        }
    
    def verify_level_4(self, result: TrainingScenarioResult) -> dict:
        """Nivel 4: Archivo llegó a destino correcto (VERIFICACIÓN FUERTE)."""
        destination_path = result.evidence.get("destination_path")
        expected_size = result.evidence.get("source_file_size")
        
        # Verificación 1: Existe el archivo
        file_exists = os.path.exists(destination_path) if destination_path else False
        
        # Verificación 2: Tamaño coincide
        actual_size = None
        if file_exists:
            actual_size = os.path.getsize(destination_path)
        size_matches = actual_size == expected_size if expected_size else None
        
        # Verificación 3: No está corrompido (checksum si es posible)
        checksum_valid = True
        if file_exists and result.evidence.get("source_checksum"):
            import hashlib
            actual_hash = hashlib.md5(open(destination_path, 'rb').read()).hexdigest()
            checksum_valid = actual_hash == result.evidence.get("source_checksum")
        
        return {
            "file_exists": file_exists,
            "size_matches": size_matches,
            "checksum_valid": checksum_valid,
            "verified_outcome": {
                "destination_path": destination_path,
                "file_exists": file_exists,
                "expected_size": expected_size,
                "actual_size": actual_size
            }
        }
    
    def verify_level_5(self, result: TrainingScenarioResult, session_history: List[TrainingScenarioResult]) -> dict:
        """Nivel 5: Desempeño sostenido."""
        recent_50 = session_history[-50:] if len(session_history) >= 50 else session_history
        
        success_count = sum(1 for s in recent_50 if s.status == "success" or s.status == "success_with_fallback")
        success_rate = success_count / len(recent_50) if recent_50 else 0
        
        verified_count = sum(1 for s in recent_50 if s.verified)
        verified_rate = verified_count / len(recent_50) if recent_50 else 0
        
        fallback_count = sum(1 for s in recent_50 if s.fallback_used is not None)
        fallback_rate = fallback_count / len(recent_50) if recent_50 else 0
        
        return {
            "success_rate": success_rate,
            "verified_rate": verified_rate,
            "fallback_rate": fallback_rate,
            "meets_level_5_criteria": success_rate >= 0.65 and fallback_rate <= 0.20 and verified_rate >= 0.70
        }

# Gates explícitos para desktop-first
DESKTOP_FIRST_GATES = {
    1: SkillGate(
        skill_id="desktop-first",
        from_level=0,
        to_level=1,
        required_scenarios=["desktop_click_001", "desktop_click_002", "desktop_click_003"],
        min_success_rate=1.0,
        max_fallback_rate=0.0,
        min_verified_sessions=5,
        max_days_to_gate=3
    ),
    2: SkillGate(
        skill_id="desktop-first",
        from_level=1,
        to_level=2,
        required_scenarios=["desktop_click_distraction_001", "desktop_click_windowed_001"],
        min_success_rate=0.90,
        max_fallback_rate=0.0,
        min_verified_sessions=10,
        max_days_to_gate=5
    ),
    3: SkillGate(
        skill_id="desktop-first",
        from_level=2,
        to_level=3,
        required_scenarios=["desktop_drag_001", "desktop_drag_recovery_001"],
        min_success_rate=0.80,
        max_fallback_rate=0.25,
        min_verified_sessions=15,
        max_days_to_gate=7
    ),
    4: SkillGate(
        skill_id="desktop-first",
        from_level=3,
        to_level=4,
        required_scenarios=["desktop_drag_real_001", "desktop_drag_real_002", "desktop_drag_verification_001"],
        min_success_rate=0.70,
        max_fallback_rate=0.30,
        min_verified_sessions=20,
        max_days_to_gate=10
    ),
    5: SkillGate(
        skill_id="desktop-first",
        from_level=4,
        to_level=5,
        required_scenarios=[],  # Cualquier escenario Nivel 4, 50 sesiones
        min_success_rate=0.65,
        max_fallback_rate=0.20,
        min_verified_sessions=50,
        max_days_to_gate=14
    )
}
```

### 2.3 TrainingScenarioResult Completos: desktop-first

**Ejemplo 1: Éxito limpio Nivel 4**
```json
{
  "skill_id": "desktop-first",
  "domain": "vision",
  "scenario_id": "desktop_drag_real_001",
  "session_id": "session_20260517_143137",
  "timestamp": 1747632697,
  
  "level": 4,
  "status": "success",
  "verified": true,
  "failure_stage": null,
  
  "fallback_used": null,
  "attempted_strategies": ["desktop_drag"],
  "chosen_strategy": "desktop_drag",
  "retryable": false,
  
  "metrics": {
    "detection_latency_ms": 120,
    "action_latency_ms": 85,
    "verification_latency_ms": 200,
    "drag_accuracy_percent": 100,
    "total_latency_ms": 405
  },
  "evidence": {
    "source_file_path": "C:\\Users\\Desktop\\test.txt",
    "source_file_size": 1024,
    "source_checksum": "abc123def456",
    "destination_path": "C:\\Users\\Downloads\\test.txt",
    "screenshot_before": "data:image/png;base64,...",
    "screenshot_after": "data:image/png;base64,...",
    "action_detected": "DRAG_DESKTOP_ICON",
    "timestamp": 1747632697
  },
  "verified_outcome": {
    "file_exists": true,
    "size_matches": true,
    "checksum_valid": true,
    "destination_path": "C:\\Users\\Downloads\\test.txt",
    "file_exists_at_dest": true,
    "expected_size": 1024,
    "actual_size": 1024
  },
  
  "error_log": null,
  "notes": "Clean desktop drag, no fallback needed"
}
```

**Ejemplo 2: Éxito con fallback Nivel 3**
```json
{
  "skill_id": "desktop-first",
  "domain": "vision",
  "scenario_id": "desktop_drag_recovery_001",
  "session_id": "session_20260517_143200",
  "timestamp": 1747632800,
  
  "level": 3,
  "status": "success_with_fallback",
  "verified": true,
  "failure_stage": "action",
  
  "fallback_used": "copy_to_clipboard",
  "attempted_strategies": ["desktop_drag", "copy_to_clipboard"],
  "chosen_strategy": "copy_to_clipboard",
  "retryable": true,
  
  "metrics": {
    "detection_latency_ms": 110,
    "action_latency_ms": 450,
    "action_failed_after_attempts": 3,
    "fallback_triggered_at_attempt": 3,
    "recovery_latency_ms": 200,
    "total_latency_ms": 760
  },
  "evidence": {
    "source_file_path": "C:\\Users\\Desktop\\test2.txt",
    "source_file_size": 2048,
    "source_checksum": "xyz789uvw012",
    "destination_path": "C:\\Users\\Downloads\\test2.txt",
    "failure_reason": "Drag failed: mouse pointer lost tracking after 3 attempts",
    "recovery_action": "Copy file to clipboard, open explorer, paste in destination",
    "screenshot_before": "data:image/png;base64,...",
    "screenshot_after_failure": "data:image/png;base64,...",
    "screenshot_after_recovery": "data:image/png;base64,..."
  },
  "verified_outcome": {
    "file_exists": true,
    "size_matches": true,
    "recovery_method": "copy_clipboard_fallback"
  },
  
  "error_log": "Drag action failed: [DetectionError: Object occlusion detected after frame 5]",
  "notes": "Recovery triggered by occlusion; recovery successful"
}
```

---

## PARTE III: GEN 1.1B - INVESTIGAR (RESEARCH) CON ANÁLISIS ROBUSTO

### 3.1 Matriz de Escenarios: investigar

**Dominios cubiertos**: `research`

| Nivel | Escenarios Obligatorios | Métrica de Éxito | Techo Fallback | Verificación Específica |
|-------|------|------|------|------|
| **1** | 1. Búsqueda simple → captura URL | ≥1 página útil en 1 búsqueda | 0 fallbacks | URL en búsqueda, texto ≥200 chars |
| **2** | 1. Búsqueda multi-resultado<br>2. Descarte de página pobre | 2+ páginas útiles de 3 intentos | 1 fallback | Descartó ≥1 página pobre; resumen >150 chars |
| **3** | 1. Multi-fuente con OCR<br>2. Fallo + recovery (busca alternativa) | 3+ páginas, OCR en 1+ | 2 fallbacks | Verificación: ≥3 fuentes diferentes, OCR capturado |
| **4** | 1. Búsqueda real + guardar documento<br>2. Verificación: documento en disco | Documento contiene ≥5 hechos únicos capturados | 2 fallbacks | Archivo existe, tamaño >5KB, contiene palabras clave |
| **5** | 1. 10 sesiones, 65%+ éxito<br>2. Documentos guardan limpiamente<br>3. Sin regresión | Tasa sostenida 65%+ | <20% | Media de 6+ hechos únicos por sesión |

### 3.2 Verificación: investigar (Con Código)

```python
# Módulo: core/verification_research.py

class ResearchVerifier:
    """Verifica resultado de búsqueda e investigación."""
    
    def verify_level_1(self, result: TrainingScenarioResult) -> dict:
        """Nivel 1: Búsqueda → captura URL + texto mínimo."""
        url = result.evidence.get("captured_url")
        text = result.evidence.get("captured_text", "")
        
        url_valid = url and url.startswith(("http://", "https://"))
        text_length = len(text)
        text_sufficient = text_length >= 200
        
        return {
            "url_valid": url_valid,
            "text_length": text_length,
            "text_sufficient": text_sufficient,
            "verified": url_valid and text_sufficient
        }
    
    def verify_level_2(self, result: TrainingScenarioResult) -> dict:
        """Nivel 2: Multi-resultado + descarte de pobres."""
        urls = result.evidence.get("captured_urls", [])
        pages_evaluated = len(urls)
        
        # Verificar que haya descartado al menos 1 página pobre
        poor_pages_rejected = result.evidence.get("poor_pages_rejected_count", 0)
        
        # Verificar resumen
        summary = result.evidence.get("captured_summary", "")
        summary_length = len(summary)
        summary_sufficient = summary_length >= 150
        
        # Verificar que URLs sean diferentes
        unique_urls = len(set(urls))
        
        return {
            "pages_evaluated": pages_evaluated,
            "poor_pages_rejected": poor_pages_rejected,
            "had_discernment": poor_pages_rejected > 0,
            "summary_length": summary_length,
            "summary_sufficient": summary_sufficient,
            "unique_urls": unique_urls,
            "verified": pages_evaluated >= 2 and poor_pages_rejected >= 1 and summary_sufficient
        }
    
    def verify_level_3(self, result: TrainingScenarioResult) -> dict:
        """Nivel 3: Multi-fuente + OCR."""
        urls = result.evidence.get("captured_urls", [])
        unique_sources = len(set(urls))
        
        ocr_performed = result.evidence.get("ocr_performed", False)
        ocr_success = result.evidence.get("ocr_text_captured") is not None
        
        recovery_attempted = "search_alternative_keywords" in result.attempted_strategies
        
        return {
            "unique_sources": unique_sources,
            "has_multi_source": unique_sources >= 3,
            "ocr_performed": ocr_performed,
            "ocr_success": ocr_success,
            "recovery_attempted": recovery_attempted,
            "verified": unique_sources >= 3 and ocr_success
        }
    
    def verify_level_4(self, result: TrainingScenarioResult) -> dict:
        """Nivel 4: Documento guardado en disco con contenido verificable."""
        document_path = result.evidence.get("document_path")
        
        # Verificación 1: Archivo existe
        file_exists = os.path.exists(document_path) if document_path else False
        
        # Verificación 2: Tamaño razonable
        file_size = None
        if file_exists:
            file_size = os.path.getsize(document_path)
        size_sufficient = file_size and file_size >= 5120  # 5KB mínimo
        
        # Verificación 3: Contiene palabras clave del resumen
        content = ""
        keywords_found = 0
        if file_exists:
            try:
                with open(document_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except:
                content = ""
            
            expected_keywords = result.evidence.get("expected_keywords", [])
            keywords_found = sum(1 for kw in expected_keywords if kw.lower() in content.lower())
        
        # Verificación 4: Cuántos hechos únicos capturados
        unique_facts = result.evidence.get("unique_facts_captured", 0)
        
        return {
            "file_exists": file_exists,
            "file_size": file_size,
            "size_sufficient": size_sufficient,
            "keywords_found": keywords_found,
            "keywords_total": len(result.evidence.get("expected_keywords", [])),
            "unique_facts": unique_facts,
            "facts_sufficient": unique_facts >= 5,
            "verified": file_exists and size_sufficient and unique_facts >= 5
        }
    
    def verify_level_5(self, session_history: List[TrainingScenarioResult]) -> dict:
        """Nivel 5: Desempeño sostenido."""
        recent_50 = session_history[-50:] if len(session_history) >= 50 else session_history
        
        success_count = sum(1 for s in recent_50 if s.verified and s.status in ["success", "success_with_fallback"])
        success_rate = success_count / len(recent_50) if recent_50 else 0
        
        fallback_count = sum(1 for s in recent_50 if s.fallback_used is not None)
        fallback_rate = fallback_count / len(recent_50) if recent_50 else 0
        
        # Promedio de hechos únicos por sesión
        total_facts = sum(s.evidence.get("unique_facts_captured", 0) for s in recent_50)
        avg_facts = total_facts / len(recent_50) if recent_50 else 0
        
        return {
            "success_rate": success_rate,
            "fallback_rate": fallback_rate,
            "avg_facts_per_session": avg_facts,
            "meets_level_5_criteria": success_rate >= 0.65 and fallback_rate <= 0.20 and avg_facts >= 6
        }

# Gates explícitos para investigar
RESEARCH_GATES = {
    1: SkillGate(
        skill_id="investigar",
        from_level=0,
        to_level=1,
        required_scenarios=["research_simple_001", "research_simple_002"],
        min_success_rate=1.0,
        max_fallback_rate=0.0,
        min_verified_sessions=5,
        max_days_to_gate=3
    ),
    2: SkillGate(
        skill_id="investigar",
        from_level=1,
        to_level=2,
        required_scenarios=["research_multi_result_001", "research_discard_poor_001"],
        min_success_rate=0.90,
        max_fallback_rate=0.10,
        min_verified_sessions=8,
        max_days_to_gate=5
    ),
    3: SkillGate(
        skill_id="investigar",
        from_level=2,
        to_level=3,
        required_scenarios=["research_ocr_001", "research_recovery_001"],
        min_success_rate=0.80,
        max_fallback_rate=0.25,
        min_verified_sessions=12,
        max_days_to_gate=7
    ),
    4: SkillGate(
        skill_id="investigar",
        from_level=3,
        to_level=4,
        required_scenarios=["research_real_001", "research_document_save_001", "research_verification_001"],
        min_success_rate=0.70,
        max_fallback_rate=0.30,
        min_verified_sessions=15,
        max_days_to_gate=10
    ),
    5: SkillGate(
        skill_id="investigar",
        from_level=4,
        to_level=5,
        required_scenarios=[],
        min_success_rate=0.65,
        max_fallback_rate=0.20,
        min_verified_sessions=50,
        max_days_to_gate=14
    )
}
```

---

## PARTE IV: GEN 1.1C - SCHEDULER PONDERADO Y LOOP INFINITO

### 4.1 Scheduler: Fórmula Concreta y Pesos

```python
# Módulo: core/training_scheduler.py

@dataclass
class SchedulerWeights:
    """Pesos para el scheduler ponderado."""
    priority: float = 0.30          # Dominio prioritario
    weakness: float = 0.35          # Tasa de fallo baja = debilidad alta
    stagnation: float = 0.15        # Días sin progreso
    freshness: float = 0.10         # Prefiere skills nuevas
    operational_need: float = 0.10  # Necesidad operativa emergente


class SkillScheduler:
    """Selecciona próximo skill a entrenar en loop infinito."""
    
    def __init__(self, weights: SchedulerWeights = None):
        self.weights = weights or SchedulerWeights()
        self.domains = [
            "vision/detection",
            "selection/workflow", 
            "research",
            "browser",
            "file_manager/explorer",
            "document_editor",
            "application_workflow",
            "game_foundation"
        ]
    
    def compute_score(self, domain: str, state: dict) -> float:
        """
        Computa puntuación para un dominio.
        
        Args:
            domain: Nombre del dominio
            state: {
                "priority_rank": 1-8,           # 1=highest
                "success_rate": 0.0-1.0,
                "fallback_rate": 0.0-1.0,
                "days_since_last_win": int,
                "sessions_without_progress": int,
                "operational_need_score": 0.0-1.0
            }
        
        Returns:
            score: 0.0-1.0
        """
        
        # Normalizar dimensiones a 0.0-1.0
        priority_score = (9 - state["priority_rank"]) / 8  # Invertir: rank 1 → 1.0
        
        # Debilidad: (1 - success_rate) * fallback_penalty
        weakness_score = (1 - state["success_rate"]) * (1 + state["fallback_rate"])
        weakness_score = min(weakness_score, 1.0)  # Capped at 1.0
        
        # Estancamiento: logarítmico (crecer rápido los primeros días, luego suavizar)
        import math
        days_stagnant = state["days_since_last_win"]
        stagnation_score = math.log(1 + days_stagnant / 2) / math.log(8)  # Normalize to ~0-1 in 14 days
        stagnation_score = min(stagnation_score, 1.0)
        
        # Frescura: nuevas skills obtienen boost temporalmente
        freshness_score = state.get("freshness_boost", 0.0)  # Decays over time
        
        # Necesidad operativa
        operational_score = state.get("operational_need_score", 0.0)
        
        # Computar score final
        score = (
            self.weights.priority * priority_score +
            self.weights.weakness * weakness_score +
            self.weights.stagnation * stagnation_score +
            self.weights.freshness * freshness_score +
            self.weights.operational_need * operational_score
        )
        
        return score
    
    def select_next_domain(self, domain_states: dict) -> str:
        """
        Selecciona el próximo dominio a entrenar.
        
        Args:
            domain_states: {
                "vision/detection": {state dict},
                "research": {state dict},
                ...
            }
        
        Returns:
            selected_domain: str
        """
        scores = {}
        for domain, state in domain_states.items():
            scores[domain] = self.compute_score(domain, state)
        
        selected = max(scores, key=scores.get)
        
        # Log para debugging
        print(f"[Scheduler] Selected {selected}")
        for domain, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            print(f"  {domain}: {score:.3f}")
        
        return selected


# Ejemplo de uso: Domain States (actualizar continuamente)
INITIAL_DOMAIN_STATES = {
    "vision/detection": {
        "priority_rank": 1,              # Highest
        "success_rate": 0.92,
        "fallback_rate": 0.08,
        "days_since_last_win": 2,
        "sessions_without_progress": 0,
        "freshness_boost": 0.0
    },
    "selection/workflow": {
        "priority_rank": 2,
        "success_rate": 0.95,
        "fallback_rate": 0.05,
        "days_since_last_win": 1,
        "sessions_without_progress": 0,
        "freshness_boost": 0.0
    },
    "research": {
        "priority_rank": 1,              # Also high
        "success_rate": 0.55,            # WEAK: 55% = high weakness score
        "fallback_rate": 0.35,
        "days_since_last_win": 5,
        "sessions_without_progress": 3,
        "freshness_boost": 0.0
    },
    "browser": {
        "priority_rank": 3,
        "success_rate": 0.70,
        "fallback_rate": 0.25,
        "days_since_last_win": 7,
        "sessions_without_progress": 2,
        "freshness_boost": 0.1            # New domain
    },
    "file_manager/explorer": {
        "priority_rank": 3,
        "success_rate": 0.80,
        "fallback_rate": 0.15,
        "days_since_last_win": 3,
        "sessions_without_progress": 0,
        "freshness_boost": 0.0
    },
    "document_editor": {
        "priority_rank": 4,
        "success_rate": 0.65,
        "fallback_rate": 0.30,
        "days_since_last_win": 10,
        "sessions_without_progress": 5,
        "freshness_boost": 0.0
    },
    "application_workflow": {
        "priority_rank": 4,
        "success_rate": 0.50,            # WEAK
        "fallback_rate": 0.40,
        "days_since_last_win": 12,
        "sessions_without_progress": 8,
        "freshness_boost": 0.0
    },
    "game_foundation": {
        "priority_rank": 5,
        "success_rate": 0.75,
        "fallback_rate": 0.20,
        "days_since_last_win": 6,
        "sessions_without_progress": 1,
        "freshness_boost": 0.05
    }
}

# Uso:
scheduler = SkillScheduler()
next_domain = scheduler.select_next_domain(INITIAL_DOMAIN_STATES)
# Esperado: 'research' (tasa baja 55%, muchos días sin progreso, alto fallback)
```

### 4.2 Loop Infinito: Flujo de Integración

```python
# Módulo: core/training_loop_infinite.py

class InfiniteTrainingLoop:
    """Loop infinito que ejecuta, verifica y promociona."""
    
    def __init__(self, scheduler: SkillScheduler, verifiers: dict):
        self.scheduler = scheduler
        self.verifiers = verifiers  # {"desktop-first": verifier, "research": verifier, ...}
        self.session_history = []
        self.domain_states = INITIAL_DOMAIN_STATES.copy()
    
    def run_one_cycle(self) -> TrainingScenarioResult:
        """Ejecuta un ciclo: selecciona → entrena → verifica → promociona."""
        
        # 1. SELECCIONAR próximo dominio
        selected_domain = self.scheduler.select_next_domain(self.domain_states)
        print(f"\n[Loop] Selected domain: {selected_domain}")
        
        # 2. OBTENER skill asociado y nivel actual
        skill_id, current_level = self._get_skill_for_domain(selected_domain)
        gate = self._get_current_gate(skill_id, current_level)
        
        print(f"[Loop] Skill: {skill_id}, Current Level: {current_level}")
        
        # 3. SELECCIONAR escenario
        scenario = self._select_scenario(skill_id, current_level)
        print(f"[Loop] Selected scenario: {scenario['scenario_id']}")
        
        # 4. EJECUTAR entrenamiento (simulado o real)
        result = self._execute_training(scenario)
        
        # 5. VERIFICAR resultado
        verifier = self.verifiers.get(skill_id)
        if verifier:
            if current_level == 1:
                verification = verifier.verify_level_1(result)
            elif current_level == 2:
                verification = verifier.verify_level_2(result)
            elif current_level == 3:
                verification = verifier.verify_level_3(result)
            elif current_level == 4:
                verification = verifier.verify_level_4(result)
            elif current_level == 5:
                verification = verifier.verify_level_5(self.session_history)
            else:
                verification = {"verified": False}
            
            result.verified = verification.get("verified", False)
            result.verified_outcome = verification
        
        # 6. REGISTRAR resultado
        self.session_history.append(result)
        print(f"[Loop] Result: {result.status}, Verified: {result.verified}")
        
        # 7. ACTUALIZAR domain states
        self._update_domain_states(selected_domain, result)
        
        # 8. VERIFICAR promoción
        promoted = self._check_gate_promotion(skill_id, current_level, gate)
        if promoted:
            print(f"[Loop] ✅ PROMOTED: {skill_id} Level {current_level} → {current_level + 1}")
        
        return result
    
    def run_sessions(self, count: int):
        """Ejecuta N ciclos del loop infinito."""
        for i in range(count):
            print(f"\n{'='*60}")
            print(f"CYCLE {i+1}/{count}")
            print(f"{'='*60}")
            self.run_one_cycle()
    
    def _get_skill_for_domain(self, domain: str) -> tuple:
        """Retorna (skill_id, current_level)."""
        mapping = {
            "vision/detection": ("desktop-first", 3),
            "selection/workflow": ("desktop-first", 4),
            "research": ("investigar", 1),
            "browser": ("browser", 2),
            "file_manager/explorer": ("file_manager", 3),
            "document_editor": ("document_editor", 1),
            "application_workflow": ("application_workflow", 1),
            "game_foundation": ("game_foundation", 1)
        }
        return mapping.get(domain, ("unknown", 1))
    
    def _get_current_gate(self, skill_id: str, level: int) -> SkillGate:
        """Obtiene gate actual para skill y nivel."""
        # Simplificado: retorna gate template
        all_gates = {
            "desktop-first": DESKTOP_FIRST_GATES,
            "investigar": RESEARCH_GATES
        }
        gates = all_gates.get(skill_id, {})
        return gates.get(level, SkillGate(skill_id=skill_id, from_level=level, to_level=level+1, required_scenarios=[], min_success_rate=0.7, max_fallback_rate=0.3, min_verified_sessions=10, max_days_to_gate=7))
    
    def _select_scenario(self, skill_id: str, level: int) -> dict:
        """Selecciona escenario para entrenar."""
        # Simplificado: retorna escenario template
        return {
            "scenario_id": f"{skill_id}_level{level}_001",
            "level": level,
            "skill_id": skill_id
        }
    
    def _execute_training(self, scenario: dict) -> TrainingScenarioResult:
        """Ejecuta el entrenamiento (aquí va el código real)."""
        # Placeholder: en implementación real, ejecutaría el skill y capturaría TrainingScenarioResult
        result = TrainingScenarioResult(
            skill_id=scenario["skill_id"],
            domain="vision",  # Simplificado
            scenario_id=scenario["scenario_id"],
            session_id=f"session_{int(time.time())}",
            timestamp=int(time.time()),
            level=scenario["level"],
            status="success",  # Simulado
            verified=False,  # Será actualizado en verify
            failure_stage=None,
            fallback_used=None,
            attempted_strategies=["primary_strategy"],
            chosen_strategy="primary_strategy",
            retryable=False,
            metrics={"latency_ms": 150},
            evidence={"test": "evidence"},
            verified_outcome={},
            error_log=None,
            notes="Simulated execution"
        )
        return result
    
    def _update_domain_states(self, domain: str, result: TrainingScenarioResult):
        """Actualiza domain states basado en resultado."""
        state = self.domain_states[domain]
        
        # Actualizar success_rate (rolling average últimas 10)
        recent_results = [r for r in self.session_history if r.domain == domain][-10:]
        successes = sum(1 for r in recent_results if r.status in ["success", "success_with_fallback"])
        state["success_rate"] = successes / len(recent_results) if recent_results else 0.5
        
        # Actualizar fallback_rate
        fallbacks = sum(1 for r in recent_results if r.fallback_used is not None)
        state["fallback_rate"] = fallbacks / len(recent_results) if recent_results else 0.0
        
        # Actualizar days_since_last_win
        if result.status in ["success", "success_with_fallback"] and result.verified:
            state["days_since_last_win"] = 0
        else:
            state["days_since_last_win"] += 0  # En loop real, incrementar por sesión
    
    def _check_gate_promotion(self, skill_id: str, current_level: int, gate: SkillGate) -> bool:
        """Verifica si se cumple gate para promoción."""
        # Obtener resultados relevantes
        relevant_results = [
            r for r in self.session_history
            if r.skill_id == skill_id and r.level == current_level and r.verified
        ]
        
        if len(relevant_results) < gate.min_verified_sessions:
            return False
        
        recent = relevant_results[-gate.min_verified_sessions:]
        success_rate = sum(1 for r in recent if r.status == "success") / len(recent)
        fallback_rate = sum(1 for r in recent if r.fallback_used is not None) / len(recent)
        
        if success_rate >= gate.min_success_rate and fallback_rate <= gate.max_fallback_rate:
            gate.gate_passed = True
            gate.gate_passed_date = int(time.time())
            return True
        
        return False
```

---

## PARTE V: GEN 1.5 - DRAFTS ENTRENABLES Y RECUPERACIÓN

### 5.1 Family Mapping: Tabla Explícita

```python
# Módulo: core/skill_family_mapping.py

SKILL_FAMILY_MAPPING = {
    # Vision & Desktop
    "desktop-first": "vision",
    "mouse_click": "vision",
    "mouse_movement": "vision",
    "mouse_drag": "vision",
    "mouse_double_click": "vision",
    "mouse_right_click": "vision",
    "object_detection": "vision",
    
    # Selection & Workflow
    "text_selection": "selection",
    "multiple_selection": "selection",
    "drag_selection": "selection",
    "workflow_sequential": "selection",
    "workflow_branching": "selection",
    
    # Research
    "investigar": "research",
    "search_google": "research",
    "search_specific_site": "research",
    "multi_source_research": "research",
    "fact_verification": "research",
    
    # Browser
    "open_webpage": "browser",
    "fill_form": "browser",
    "submit_form": "browser",
    "scroll_page": "browser",
    "extract_text": "browser",
    "navigate_links": "browser",
    
    # File Manager / Explorer
    "open_file_explorer": "file_manager",
    "navigate_folders": "file_manager",
    "copy_files": "file_manager",
    "move_files": "file_manager",
    "delete_files": "file_manager",
    "find_files": "file_manager",
    
    # Document Editor
    "open_document": "documents",
    "edit_text": "documents",
    "format_text": "documents",
    "save_document": "documents",
    "insert_image": "documents",
    "insert_table": "documents",
    
    # Application Workflow
    "launch_application": "application",
    "navigate_app_ui": "application",
    "click_button": "application",
    "enter_data": "application",
    "confirm_action": "application",
    
    # Game Foundation
    "press_key": "game",
    "hold_key": "game",
    "move_cursor": "game",
    "timing_based_action": "game",
    "multi_key_combo": "game"
}

def get_family_for_skill(skill_id: str) -> str:
    """Retorna familia para un skill."""
    return SKILL_FAMILY_MAPPING.get(skill_id, "unknown")

def create_trainable_draft(skill_id: str, skill_name: str, description: str) -> TrainableDraft:
    """Crea draft entrenable para skill nuevo."""
    family = get_family_for_skill(skill_id)
    
    if family == "unknown":
        family = "application"  # Default fallback
    
    # Copiar templates de la familia
    family_templates = _get_family_scenario_templates(family)
    family_verification = _get_family_verification_rules(family)
    
    draft = TrainableDraft(
        skill_id=skill_id,
        skill_name=skill_name,
        description=description,
        family=family,
        scenario_templates=family_templates,
        verification_rules=family_verification,
        missing_capabilities=[],
        readiness_blockers=[],
        estimated_training_days=14,
        created_date=int(time.time())
    )
    
    return draft

def _get_family_scenario_templates(family: str) -> List[dict]:
    """Retorna templates de escenarios para una familia."""
    templates = {
        "vision": [
            {"level": 1, "name": "Basic detection", "description": "Detect object in clear view"},
            {"level": 2, "name": "Detection with distractions", "description": "Detect with visual noise"},
            {"level": 3, "name": "Recovery + partial occlusion", "description": "Recover from failure, handle half-visible target"},
            {"level": 4, "name": "Real execution with verification", "description": "Execute in real app, verify result"}
        ],
        "research": [
            {"level": 1, "name": "Simple search", "description": "One search query → capture URL + text"},
            {"level": 2, "name": "Multi-source with filtering", "description": "Multiple results, discard poor pages"},
            {"level": 3, "name": "OCR + recovery", "description": "Extract from images, retry on failure"},
            {"level": 4, "name": "Real task with artifact", "description": "Complete research task, save document"}
        ],
        "browser": [
            {"level": 1, "name": "Open URL", "description": "Navigate to page, verify loaded"},
            {"level": 2, "name": "Basic interaction", "description": "Scroll, click links"},
            {"level": 3, "name": "Form filling", "description": "Enter data, handle validation"},
            {"level": 4, "name": "Complex workflow", "description": "Multi-step interaction sequence"}
        ],
        "file_manager": [
            {"level": 1, "name": "Navigate folders", "description": "Open explorer, navigate"},
            {"level": 2, "name": "File operations", "description": "Copy, move, rename"},
            {"level": 3, "name": "Search + filtering", "description": "Find files by criteria"},
            {"level": 4, "name": "Batch operations", "description": "Multiple file actions"}
        ],
        "documents": [
            {"level": 1, "name": "Open document", "description": "Launch editor, open file"},
            {"level": 2, "name": "Basic editing", "description": "Type, select, delete"},
            {"level": 3, "name": "Formatting", "description": "Apply styles, structure"},
            {"level": 4, "name": "Save + verify", "description": "Save document, verify content"}
        ],
        "selection": [
            {"level": 1, "name": "Simple selection", "description": "Select single element"},
            {"level": 2, "name": "Multi-selection", "description": "Ctrl+click multiple"},
            {"level": 3, "name": "Drag selection", "description": "Click+drag to select"},
            {"level": 4, "name": "Complex selection workflow", "description": "Multi-step selection"}
        ],
        "application": [
            {"level": 1, "name": "Launch app", "description": "Start application"},
            {"level": 2, "name": "UI navigation", "description": "Click buttons, menus"},
            {"level": 3, "name": "Data entry", "description": "Fill forms, confirm"},
            {"level": 4, "name": "Complex workflow", "description": "Multi-screen interaction"}
        ],
        "game": [
            {"level": 1, "name": "Key press", "description": "Single key actions"},
            {"level": 2, "name": "Movement", "description": "Arrow keys, WASD"},
            {"level": 3, "name": "Timing", "description": "Precise timing actions"},
            {"level": 4, "name": "Complex controls", "description": "Multi-key combos"}
        ]
    }
    return templates.get(family, [])

def _get_family_verification_rules(family: str) -> dict:
    """Retorna reglas de verificación para una familia."""
    rules = {
        "vision": {
            "level_1": "Action detected and logged",
            "level_2": "Action succeeded with distraction",
            "level_3": "Recovery strategy used, succeeded",
            "level_4": "Final state verified (file/position)"
        },
        "research": {
            "level_1": "URL captured, text length >= 200",
            "level_2": "Multiple sources, poor pages filtered",
            "level_3": "Multi-source verified, OCR obtained",
            "level_4": "Document saved, contains verified facts"
        }
        # ... (similar para otras familias)
    }
    return rules.get(family, {})
```

### 5.2 Recovery Engine: Auditable

```python
# Módulo: core/recovery_engine.py

class RecoveryEngine:
    """Motor de recuperación autónomo basado en playbooks."""
    
    PLAYBOOKS = {
        "vision": {
            "detection_lost": {
                "strategies": ["retry_with_focus_window", "screenshot_refresh", "ocr_fallback"],
                "description": "Target lost or not detected"
            },
            "action_failed_after_3_attempts": {
                "strategies": ["copy_to_clipboard", "explorer_fallback", "manual_positioning"],
                "description": "Primary action failed multiple times"
            },
            "verification_failed": {
                "strategies": ["verify_again", "check_alternative_location", "inspect_filesystem"],
                "description": "Verification check failed"
            }
        },
        "research": {
            "page_load_timeout": {
                "strategies": ["retry_same_url", "search_alternative_keywords", "use_cached_result"],
                "description": "Page took too long to load"
            },
            "poor_page_quality": {
                "strategies": ["skip_page", "search_more_specific", "use_ocr_on_screenshot"],
                "description": "Page content too poor or blocked"
            },
            "ocr_failed": {
                "strategies": ["retry_ocr", "capture_screenshot_again", "manual_text_entry"],
                "description": "OCR extraction failed"
            }
        }
    }
    
    def __init__(self, history: List[TrainingScenarioResult]):
        self.history = history
    
    def get_next_strategy(self, failure: dict) -> RecoveryAttempt:
        """
        Obtiene próxima estrategia basada en fallo.
        
        Args:
            failure: {
                "training_scenario_id": str,
                "failure_session_id": str,
                "failure_stage": str,      # "detection", "action", "verification"
                "failure_reason": str,     # Descripción del fallo
                "domain": str              # "vision", "research", etc
            }
        
        Returns:
            RecoveryAttempt con estrategia recomendada
        """
        domain = failure.get("domain")
        failure_reason = failure.get("failure_reason")
        
        playbooks = self.PLAYBOOKS.get(domain, {})
        
        # Buscar playbook que coincida
        matched_playbook = None
        for playbook_key, playbook in playbooks.items():
            if playbook_key in failure_reason.lower() or failure_reason.lower() in playbook_key:
                matched_playbook = playbook
                break
        
        if not matched_playbook:
            # Default: las estrategias más comunes por dominio
            matched_playbook = list(playbooks.values())[0] if playbooks else {"strategies": ["retry"]}
        
        # Rankear estrategias por historial
        strategies = matched_playbook.get("strategies", ["retry"])
        ranked_strategies = self._rank_strategies_by_history(domain, strategies)
        
        chosen_strategy = ranked_strategies[0]
        
        recovery = RecoveryAttempt(
            training_scenario_id=failure.get("training_scenario_id"),
            failure_session_id=failure.get("failure_session_id"),
            failure_stage=failure.get("failure_stage"),
            failure_reason=failure_reason,
            attempted_strategies=ranked_strategies,
            chosen_next_strategy=chosen_strategy,
            strategy_reasoning=f"Ranked {len(ranked_strategies)} strategies, {chosen_strategy} was most successful historically",
            recovery_session_id=f"recovery_{int(time.time())}",
            recovery_succeeded=False,  # Será actualizado después
            recovery_verified=False,
            confidence_in_recovery=0.7,  # Valor inicial
            is_playbook_decision=matched_playbook is not None
        )
        
        return recovery
    
    def _rank_strategies_by_history(self, domain: str, strategies: List[str]) -> List[str]:
        """Rankea estrategias por historial de éxito."""
        strategy_stats = {}
        
        for strategy in strategies:
            matching_results = [
                r for r in self.history
                if r.domain == domain and strategy in r.attempted_strategies
            ]
            
            successes = sum(1 for r in matching_results if r.status in ["success", "success_with_fallback"] and r.verified)
            total = len(matching_results)
            success_rate = (successes / total) if total > 0 else 0.5  # Default 0.5 si no hay historial
            
            strategy_stats[strategy] = {
                "success_rate": success_rate,
                "attempts": total
            }
        
        # Rankear por success_rate, con tie-break por attempts (más intentos = más confianza)
        ranked = sorted(strategies, key=lambda s: (strategy_stats[s]["success_rate"], strategy_stats[s]["attempts"]), reverse=True)
        
        return ranked
```

---

## PARTE VI: GEN 2 - ARQUITECTURA HÍBRIDA CON MODELOS

### 6.1 Interface ModelAssistDecision (Ya Definida Arriba)

### 6.2 Primeros Modelos Obligatorios

#### 6.2.1 UI Target Ranker

```python
# Módulo: core/models/ui_target_ranker.py

class UITargetRankerModel:
    """
    Reordena candidatos de UI (botones, items, targets) por probabilidad de ser el objetivo.
    Entrenado offline con dataset de capturas + candidatos detectados + selección real.
    """
    
    model_id: str = "ui_target_ranker_v1"
    input_type: str = "screenshot_with_candidates"
    input_shape: tuple = (480, 640, 3)  # Tamaño normalizado de screenshot
    
    def __init__(self, onnx_path: Optional[str] = None):
        """
        Args:
            onnx_path: Ruta a modelo ONNX pre-entrenado. Si None, usa heurísticas.
        """
        self.onnx_path = onnx_path
        self.session = None
        
        if onnx_path and os.path.exists(onnx_path):
            try:
                import onnxruntime
                self.session = onnxruntime.InferenceSession(onnx_path)
            except:
                self.session = None
    
    def rank_candidates(self, screenshot: np.ndarray, candidates: List[dict], use_model: bool = True) -> List[tuple]:
        """
        Rankea candidatos (botones, items).
        
        Args:
            screenshot: np.ndarray de imagen (H x W x 3)
            candidates: [
                {"id": "btn_123", "bbox": [x, y, w, h], "text": "Click here", "color": (255, 0, 0)},
                {"id": "btn_456", "bbox": [x2, y2, w2, h2], "text": "Cancel", ...},
                ...
            ]
            use_model: Si True, usa modelo ONNX si está disponible; si False, usa heurísticas
        
        Returns:
            [(candidate_id, score), ...]  # Ordenado por score descendente
        """
        
        if use_model and self.session:
            return self._rank_with_model(screenshot, candidates)
        else:
            return self._rank_with_heuristics(screenshot, candidates)
    
    def _rank_with_model(self, screenshot: np.ndarray, candidates: List[dict]) -> List[tuple]:
        """Ranking con modelo ONNX."""
        try:
            # Preparar inputs
            screenshot_resized = cv2.resize(screenshot, self.input_shape[:2][::-1])
            screenshot_normalized = screenshot_resized.astype(np.float32) / 255.0
            screenshot_batched = np.expand_dims(screenshot_normalized, 0)  # Batch dimension
            
            # Preparar features de candidatos
            candidate_features = []
            for cand in candidates:
                bbox = cand.get("bbox", [0, 0, 0, 0])
                text = cand.get("text", "")
                # Feature vector: [normalized_bbox_center_x, normalized_bbox_center_y, bbox_area, text_length]
                center_x = (bbox[0] + bbox[2]/2) / screenshot.shape[1]
                center_y = (bbox[1] + bbox[3]/2) / screenshot.shape[0]
                area = (bbox[2] * bbox[3]) / (screenshot.shape[0] * screenshot.shape[1])
                text_len = len(text) / 100.0  # Normalize
                candidate_features.append([center_x, center_y, area, text_len])
            
            candidate_features = np.array(candidate_features, dtype=np.float32)
            
            # Inferencia
            input_name = self.session.get_inputs()[0].name
            output_name = self.session.get_outputs()[0].name
            scores = self.session.run([output_name], {input_name: screenshot_batched})[0]
            
            # Retornar ranking
            candidate_scores = list(zip([c.get("id", f"cand_{i}") for i, c in enumerate(candidates)], scores.flatten()))
            return sorted(candidate_scores, key=lambda x: x[1], reverse=True)
        
        except Exception as e:
            print(f"[UITargetRanker] Model inference failed: {e}, falling back to heuristics")
            return self._rank_with_heuristics(screenshot, candidates)
    
    def _rank_with_heuristics(self, screenshot: np.ndarray, candidates: List[dict]) -> List[tuple]:
        """Ranking con heurísticas (fallback)."""
        scores = {}
        
        for cand in candidates:
            cand_id = cand.get("id", f"cand_{len(scores)}")
            bbox = cand.get("bbox", [0, 0, 0, 0])
            text = cand.get("text", "")
            
            # Heurística 1: Candidatos en el centro de la pantalla (más probable objetivo)
            center_x = bbox[0] + bbox[2] / 2
            center_y = bbox[1] + bbox[3] / 2
            distance_from_center = abs(center_x - screenshot.shape[1]/2) + abs(center_y - screenshot.shape[0]/2)
            center_score = 1.0 / (1.0 + distance_from_center / 100)  # Decay by distance
            
            # Heurística 2: Texto indicativo (contiene palabras clave)
            action_keywords = ["click", "submit", "ok", "confirm", "save", "next", "start"]
            text_score = 1.0 if any(kw in text.lower() for kw in action_keywords) else 0.5
            
            # Heurística 3: Tamaño razonable (no demasiado pequeño, no demasiado grande)
            area = bbox[2] * bbox[3]
            ideal_area = (screenshot.shape[0] * screenshot.shape[1]) / 20  # 5% de pantalla
            size_score = 1.0 / (1.0 + abs(area - ideal_area) / ideal_area)
            
            # Combinar
            total_score = 0.4 * center_score + 0.3 * text_score + 0.3 * size_score
            scores[cand_id] = total_score
        
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

#### 6.2.2 Research Page Usefulness Classifier

```python
# Módulo: core/models/page_usefulness_classifier.py

class PageUsefulnessClassifier:
    """
    Clasifica páginas web como útil vs pobre/basura.
    Entrenado offline con dataset de URLs + contenido capturado + label manual.
    """
    
    model_id: str = "page_usefulness_v1"
    input_type: str = "extracted_text"
    
    def __init__(self, onnx_path: Optional[str] = None):
        """
        Args:
            onnx_path: Ruta a modelo ONNX pre-entrenado.
        """
        self.onnx_path = onnx_path
        self.session = None
        
        if onnx_path and os.path.exists(onnx_path):
            try:
                import onnxruntime
                self.session = onnxruntime.InferenceSession(onnx_path)
            except:
                self.session = None
    
    def classify_page(self, page_text: str, page_url: str, use_model: bool = True) -> dict:
        """
        Clasifica utilidad de página.
        
        Args:
            page_text: Texto extraído de la página
            page_url: URL de la página
            use_model: Si True, usa modelo ONNX; si False, usa heurísticas
        
        Returns:
            {
                "useful": bool,
                "score": 0.0-1.0,
                "reasoning": str,
                "model_used": bool
            }
        """
        
        if use_model and self.session:
            return self._classify_with_model(page_text, page_url)
        else:
            return self._classify_with_heuristics(page_text, page_url)
    
    def _classify_with_model(self, page_text: str, page_url: str) -> dict:
        """Clasificación con modelo ONNX."""
        try:
            # Preparar features de texto
            text_features = self._extract_text_features(page_text)
            url_features = self._extract_url_features(page_url)
            all_features = np.concatenate([text_features, url_features]).astype(np.float32)
            all_features_batched = np.expand_dims(all_features, 0)
            
            # Inferencia
            input_name = self.session.get_inputs()[0].name
            output_name = self.session.get_outputs()[0].name
            score = self.session.run([output_name], {input_name: all_features_batched})[0][0, 0]
            
            return {
                "useful": score > 0.5,
                "score": float(score),
                "reasoning": f"Model score: {score:.2f}",
                "model_used": True
            }
        
        except Exception as e:
            print(f"[PageUsefulnessClassifier] Model inference failed: {e}, falling back to heuristics")
            return self._classify_with_heuristics(page_text, page_url)
    
    def _classify_with_heuristics(self, page_text: str, page_url: str) -> dict:
        """Clasificación con heurísticas (fallback)."""
        
        # Heurística 1: Largo del texto
        text_length = len(page_text)
        if text_length < 100:
            return {"useful": False, "score": 0.1, "reasoning": "Text too short (<100 chars)", "model_used": False}
        if text_length > 100000:
            return {"useful": False, "score": 0.2, "reasoning": "Text too long (>100K chars, likely bloat)", "model_used": False}
        
        # Heurística 2: Palabras comunes en páginas pobres
        poor_indicators = ["error", "404", "blocked", "restricted", "login required", "paywall", "javascript required"]
        poor_score = sum(1 for ind in poor_indicators if ind in page_text.lower())
        
        if poor_score >= 3:
            return {"useful": False, "score": 0.3, "reasoning": "Multiple poor-page indicators found", "model_used": False}
        
        # Heurística 3: URL puede indicar dominio poco confiable
        bad_domains = ["spam", "tracker", "ads", "pop"]
        is_bad_domain = any(bad in page_url.lower() for bad in bad_domains)
        
        if is_bad_domain:
            return {"useful": False, "score": 0.2, "reasoning": "Suspicious domain in URL", "model_used": False}
        
        # Heurística 4: Presencia de palabras clave constructivas
        good_keywords = ["research", "study", "data", "analysis", "information", "guide", "tutorial", "documentation"]
        good_score = sum(1 for kw in good_keywords if kw in page_text.lower())
        
        # Computar score final
        final_score = min(1.0, 0.5 + (text_length / 50000) * 0.2 + (good_score / 5) * 0.3)
        
        return {
            "useful": final_score > 0.5,
            "score": final_score,
            "reasoning": f"Heuristic score: {final_score:.2f} (length contrib, keywords contrib)",
            "model_used": False
        }
    
    def _extract_text_features(self, text: str) -> np.ndarray:
        """Extrae features de texto."""
        features = [
            len(text),
            len(text.split()),
            text.count('\n'),
            text.count('\t'),
        ]
        return np.array(features, dtype=np.float32)
    
    def _extract_url_features(self, url: str) -> np.ndarray:
        """Extrae features de URL."""
        features = [
            len(url),
            url.count('/'),
            url.count('?'),
        ]
        return np.array(features, dtype=np.float32)
```

---

## PARTE VII: CRITERIOS DE SALIDA Y HITOS

### 7.1 Gen 1.1a: Cierra Cuando...

✅ **CRITERIOS DE SALIDA (TODOS DEBEN CUMPLIRSE)**:

1. **desktop-first Nivel 4 completado**:
   - ≥20 sesiones verificadas en Nivel 4
   - Success rate ≥70%
   - Fallback rate ≤30%
   - Verificación filesystem 100% correcta en todas las sesiones

2. **Dataset capturado**:
   - ≥50 sesiones totales con `TrainingScenarioResult` estructurado
   - Todas tienen `evidence`, `verified_outcome`, `failure_stage` (si aplica)
   - Checksum validado para cada archivo en Nivel 4

3. **Integración con loop**:
   - TrainingScenarioResult se lee correctamente del loop
   - Gates se evalúan automáticamente después de cada sesión
   - Promoción automática ocurre cuando gate se cumple

4. **Cierre documentado**:
   - Todos los TrainingScenarioResult tienen `notes` explicativas
   - Error log está completo para fallos
   - Revisar 5 sesiones fallidas, extraer patrones comunes

---

### 7.2 Gen 1.1b: Cierra Cuando...

✅ **CRITERIOS DE SALIDA**:

1. **investigar Nivel 4 completado**:
   - ≥15 sesiones verificadas
   - Documentos guardados correctamente en disco
   - Verificación de contenido (≥5 hechos únicos) 100% confiable

2. **Descarte de páginas pobres confiable**:
   - Modelo o heurística descarta ≥70% de páginas pobres
   - No descarta páginas útiles (precisión >90%)

3. **Multi-fuente verificable**:
   - Al menos 5 sesiones con ≥3 URLs diferentes capturadas
   - Resúmenes contienen hechos de múltiples fuentes

---

### 7.3 Gen 1.1c: Cierra Cuando...

✅ **CRITERIOS DE SALIDA**:

1. **Loop infinito rota entre 8 dominios**:
   - Scheduler selecciona próximo dominio correctamente
   - Cada dominio tiene ≥10 sesiones capturadas en 2 semanas

2. **Promociones automáticas funcionan**:
   - ≥2 skills alcanzaron Nivel 5
   - Cero promociones falsas (verificar manualmente 10 promociones)

3. **Domain states se actualizan correctamente**:
   - Success rate, fallback rate, days_since_last_win actualizado después de cada sesión
   - Scheduler reordena dominios cada sesión basado en state actual

---

## PARTE VIII: PLAN DE PRUEBAS DETALLADO

### 8.1 Pruebas: desktop-first

| Test | Escenario | Esperado | Verificación |
|------|-----------|----------|---|
| **T1.1** | Click en target visible, Nivel 1 | Status="success", verified=true | `verify_level_1()` retorna true |
| **T1.2** | Click con distracción visual, Nivel 2 | Status="success", fallback_rate<1% | 10 intentos, 90%+ éxito |
| **T1.3** | Drag falla → fallback copy Nivel 3 | Status="success_with_fallback", fallback_used="copy_to_clipboard" | Recovery registered |
| **T1.4** | Drag real, Nivel 4 | Archivo en destino, checksum válido | `verify_level_4()` retorna true, filesystem check OK |
| **T1.5** | Sustancia Nivel 5 (50 sesiones) | Success rate 65%+, fallback rate <20% | `verify_level_5()` retorna true |
| **T1.6** | Gate promotion automática | Pasar de Nivel 3 a 4 | Gate se marca como passed, fecha registrada |

### 8.2 Pruebas: investigar

| Test | Escenario | Esperado | Verificación |
|------|-----------|----------|---|
| **T2.1** | Búsqueda simple, captura URL + texto | text_length >= 200, URL válida | `verify_level_1()` true |
| **T2.2** | Descarta página pobre | poor_pages_rejected_count >= 1, summary >= 150 chars | `verify_level_2()` true |
| **T2.3** | Multi-fuente + OCR | unique_sources >= 3, ocr_success=true | `verify_level_3()` true |
| **T2.4** | Documento guardado con hechos | file_exists=true, size>=5KB, facts>=5 | `verify_level_4()` true, file checksum |
| **T2.5** | Classifier: página útil vs pobre | Accuracy >85% en dataset test | Eval classifier en 100 páginas |

### 8.3 Pruebas: scheduler

| Test | Escenario | Esperado | Verificación |
|------|-----------|----------|---|
| **T3.1** | Selecciona dominio débil | Domain con lowest success_rate priorizado | scheduler.select_next_domain() retorna weakness-heavy domain |
| **T3.2** | Reordena cada sesión | Scores cambian después de resultado | Compararscores antes/después de sesión |
| **T3.3** | Respeta prioritario | High-priority domain no es ignorado | Rank top-3 includes priority-1 domains |

### 8.4 Pruebas: recuperación

| Test | Escenario | Esperado | Verificación |
|------|-----------|----------|---|
| **T4.1** | Fallo de detection → retry | chosen_next_strategy != attempted_strategy anterior | Recovery con estrategia diferente |
| **T4.2** | Playbook match | recovery.is_playbook_decision=true | estrategia viene de playbook |
| **T4.3** | Recovery success registrado | recovery_succeeded=true, recovery_verified=true | TrainingScenarioResult captura recovery |

---

## PARTE IX: TIMELINE Y RESPONSABILIDADES

### 9.1 Gen 1.1a (2 semanas)

| Semana | Tarea | Dueño | Entregables |
|--------|------|------|---|
| **S1** | Implementar TrainingScenarioResult + gates template | Backend | `core/training_models.py`, `DESKTOP_FIRST_GATES` |
| **S1** | Escribir DesktopFirstVerifier completo | Backend | `core/verification_desktop_first.py` |
| **S2** | Ejecutar ≥50 sesiones Nivel 4 | QA | Dataset con 50 sesiones + screenshots |
| **S2** | Validar verificación filesystem 100% | Backend | Report: 50/50 sesiones verificadas correctamente |

### 9.2 Gen 1.1b (2 semanas)

| Semana | Tarea | Dueño | Entregables |
|--------|------|------|---|
| **S3** | Escribir ResearchVerifier + RESEARCH_GATES | Backend | `core/verification_research.py` |
| **S3** | Integrar classifier (heurístico) | Backend | `core/models/page_usefulness_classifier.py` |
| **S4** | Ejecutar ≥15 sesiones Nivel 4 (documentos) | QA | Dataset con documentos verificados |
| **S4** | Validar multi-fuente + descarte | QA | Report: accuracy del classifier |

### 9.3 Gen 1.1c (3 semanas)

| Semana | Tarea | Dueño | Entregables |
|--------|------|------|---|
| **S5** | Escribir SkillScheduler + pesos numéricos | Backend | `core/training_scheduler.py` |
| **S5** | Escribir InfiniteTrainingLoop | Backend | `core/training_loop_infinite.py` |
| **S6** | Integrar todos 8 dominios | Backend | Domain states mapping, scenario templates |
| **S7** | Ejecutar loop: ≥10 sesiones por dominio, 2 semanas | QA | Datos de todas las dominios |
| **S7** | Validar 2+ promociones automáticas | QA | Gates cerrados, skills ascendidos |

---

## PARTE X: SUPUESTOS Y DEFAULTS FINALES

✅ **Default: Híbrido Primero**
- Evidencia > Verificación > Heurísticas > Modelos (apoyo)
- Gen 2 (modelos principales) es DESPUÉS de Gen 1 (datos + gates)

✅ **Default: Loop Infinito Todo Incluido**
- No solo mouse/teclado → 8 dominios desde el inicio
- Scheduler ponderado, no orden fijo

✅ **Default: Promoción = Gates, No Repeticiones**
- Matriz de escenarios + umbral de éxito + techo de fallback
- No "hicimos 100 intentos, está bueno"

✅ **Default: Personalidad Después**
- UI viva entra post-Gen 1.1c
- Cuando recuperación + verificación sean sólidas

✅ **Default: desktop-first + investigar Son Los Frentes**
- Mayor impacto en confianza del sistema
- Priorizados para Gen 1.1a + 1.1b

---

**Versión**: 1.0 Ejecutable  
**Fecha**: Mayo 17, 2026  
**Estado**: Listo para implementación  
