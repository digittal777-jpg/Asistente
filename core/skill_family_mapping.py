from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from core.skills import normalize_text
from core.training_models import TrainableDraft


SKILL_FAMILY_MAPPING: Dict[str, str] = {
    "desktop-first": "vision",
    "mouse_drag": "vision",
    "object_detection": "vision",
    "vision": "vision",
    "detection": "vision",
    "ocr": "vision",
    "investigar": "research",
    "research": "research",
    "search_google": "research",
    "research_document": "research",
    "fill_form": "browser",
    "browser": "browser",
    "extract_text": "browser",
    "youtube": "browser",
    "brave": "browser",
    "open_file_explorer": "file_manager",
    "copy_files": "file_manager",
    "file_manager": "file_manager",
    "explorer": "file_manager",
    "save_document": "documents",
    "edit_text": "documents",
    "documents": "documents",
    "word": "documents",
    "notepad": "documents",
    "launch_application": "application",
    "click_button": "application",
    "application": "application",
    "press_key": "game",
    "move_cursor": "game",
    "minecraft": "game",
    "terraria": "game",
    "juego": "game",
    "game": "game",
}


FAMILY_SCENARIO_TEMPLATES: Dict[str, List[dict]] = {
    "vision": [
        {"scenario_id": "ui_detect_visible", "description": "detectar elemento UI visible", "level": 0},
        {"scenario_id": "ui_detect_distracted", "description": "detectar con distractores", "level": 1},
        {"scenario_id": "ocr_partial_region", "description": "extraer texto de region parcial", "level": 2},
    ],
    "research": [
        {"scenario_id": "research_single_source", "description": "buscar y abrir una fuente util", "level": 0},
        {"scenario_id": "research_multi_query", "description": "buscar multiples variantes y deduplicar", "level": 2},
        {"scenario_id": "research_to_document", "description": "guardar documento verificable", "level": 3},
    ],
    "browser": [
        {"scenario_id": "browser_open_google", "description": "abrir Google en browser", "level": 0},
        {"scenario_id": "browser_search_result", "description": "hacer busqueda y confirmar transicion", "level": 1},
        {"scenario_id": "browser_form_fill", "description": "llenar formulario simple", "level": 3},
    ],
    "file_manager": [
        {"scenario_id": "explorer_open_workspace", "description": "abrir Explorer y enfocarlo", "level": 0},
        {"scenario_id": "explorer_select_item", "description": "seleccionar item correcto", "level": 1},
        {"scenario_id": "explorer_move_verified", "description": "mover archivo con verificacion", "level": 3},
    ],
    "documents": [
        {"scenario_id": "document_write_basic", "description": "escritura basica en editor", "level": 0},
        {"scenario_id": "document_replace_text", "description": "reemplazo y verificacion de texto", "level": 1},
        {"scenario_id": "document_save_verified", "description": "guardado con verificacion de archivo", "level": 3},
    ],
    "application": [
        {"scenario_id": "application_open_verify", "description": "abrir aplicacion y verificar foco", "level": 0},
        {"scenario_id": "application_click_target", "description": "accionar control visible", "level": 1},
        {"scenario_id": "application_goal_workflow", "description": "flujo util completo", "level": 3},
    ],
    "game": [
        {"scenario_id": "game_input_foundation", "description": "input basico de teclado/mouse", "level": 0},
        {"scenario_id": "game_control_lookup", "description": "investigar controles del juego", "level": 1},
        {"scenario_id": "game_goal_chain", "description": "secuencia de acciones orientada a objetivo", "level": 4},
    ],
}


FAMILY_VERIFICATION_RULES: Dict[str, Dict[str, Any]] = {
    "vision": {"minimum_confidence": 0.85, "requires_evidence": True},
    "research": {"minimum_sources": 3, "minimum_unique_facts": 5, "requires_document_at_level_3": True},
    "browser": {"requires_active_site_confirmation": True},
    "file_manager": {"requires_filesystem_verification": True},
    "documents": {"requires_saved_file": True},
    "application": {"requires_active_window_confirmation": True},
    "game": {"requires_foundation_only_until_backend": True},
}


FAMILY_ESTIMATED_DAYS: Dict[str, int] = {
    "vision": 10,
    "research": 14,
    "browser": 7,
    "file_manager": 7,
    "documents": 7,
    "application": 7,
    "game": 21,
}


def infer_skill_family(skill_id: str, skill_name: str = "", description: str = "") -> str:
    text = " ".join(item for item in (skill_id, skill_name, description) if item).strip()
    normalized = normalize_text(text)
    for keyword, family in SKILL_FAMILY_MAPPING.items():
        alias = normalize_text(keyword)
        if alias and alias in normalized:
            return family
    return "application"


def create_trainable_draft(
    skill_id: str,
    skill_name: str,
    description: str,
    family: Optional[str] = None,
) -> TrainableDraft:
    resolved_family = family or infer_skill_family(skill_id, skill_name, description)
    templates = [dict(item) for item in FAMILY_SCENARIO_TEMPLATES.get(resolved_family, [])]
    verification_rules = dict(FAMILY_VERIFICATION_RULES.get(resolved_family, {}))
    missing_capabilities: List[str] = []
    readiness_blockers: List[str] = []

    if resolved_family == "game":
        missing_capabilities.extend(["game_state_verification", "game_ui_patterns"])
        readiness_blockers.append("needs_game_backend_or_specific_visual_templates")
    elif resolved_family == "application":
        missing_capabilities.append("application_specific_ui_map")
    elif resolved_family == "research":
        missing_capabilities.append("source_specific_parsers")

    return TrainableDraft(
        skill_id=skill_id,
        skill_name=skill_name,
        description=description,
        family=resolved_family,
        scenario_templates=templates,
        verification_rules=verification_rules,
        missing_capabilities=missing_capabilities,
        readiness_blockers=readiness_blockers,
        estimated_training_days=FAMILY_ESTIMATED_DAYS.get(resolved_family, 7),
        created_date=int(time.time()),
    )
