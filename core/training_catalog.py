from __future__ import annotations

from typing import Any, Dict, List, Tuple


ORDERED_TRAINING_DOMAINS: Tuple[str, ...] = (
    "keyboard",
    "perception",
    "vision/detection",
    "selection/workflow",
    "research",
    "browser",
    "file_manager/explorer",
    "document_editor",
    "application_workflow",
    "game_foundation",
)


DOMAIN_SCENARIOS: Dict[str, List[Dict[str, Any]]] = {
    "keyboard": [
        {"scenario_id": "keyboard_text_entry", "runner": "practice_skill", "skill_label": "teclado", "level": 0, "family": "keyboard"},
        {"scenario_id": "keyboard_browser_address_focus", "runner": "practice_skill", "skill_label": "teclado", "level": 2, "family": "keyboard"},
        {"scenario_id": "keyboard_explorer_search", "runner": "practice_skill", "skill_label": "teclado", "level": 2, "family": "keyboard"},
        {"scenario_id": "keyboard_window_switch", "runner": "practice_skill", "skill_label": "teclado", "level": 4, "family": "keyboard"},
        {"scenario_id": "keyboard_multiapp_chain", "runner": "practice_skill", "skill_label": "teclado", "level": 5, "family": "keyboard"},
    ],
    "perception": [
        {"scenario_id": "visual_context_identity", "runner": "practice_skill", "skill_label": "visualizacion", "level": 0, "family": "perception"},
        {"scenario_id": "visual_target_reacquire", "runner": "practice_skill", "skill_label": "visualizacion", "level": 2, "family": "perception"},
        {"scenario_id": "visual_scene_transition", "runner": "practice_skill", "skill_label": "visualizacion", "level": 3, "family": "perception"},
        {"scenario_id": "visual_workflow_precondition", "runner": "practice_skill", "skill_label": "visualizacion", "level": 4, "family": "perception"},
        {"scenario_id": "visual_adversarial_recovery", "runner": "practice_skill", "skill_label": "visualizacion", "level": 5, "family": "perception"},
    ],
    "vision/detection": [
        {"scenario_id": "ui_detect_visible", "runner": "practice_mouse_movement", "skill_label": "mouse", "level": 0},
        {"scenario_id": "mouse_click_visible", "runner": "practice_mouse_click", "skill_label": "mouse", "level": 1},
        {"scenario_id": "mouse_click_reopened_window", "runner": "practice_mouse_double_click", "skill_label": "mouse", "level": 1},
        {"scenario_id": "mouse_right_click_visible", "runner": "practice_mouse_right_click", "skill_label": "mouse", "level": 1},
        {"scenario_id": "ui_detect_distracted", "runner": "practice_mouse_detection", "skill_label": "mouse", "level": 2},
        {"scenario_id": "ocr_partial_region", "runner": "practice_mouse_selection", "skill_label": "mouse", "level": 2},
    ],
    "selection/workflow": [
        {"scenario_id": "desktop_drag_constrained", "runner": "practice_desktop_mouse", "skill_label": "mouse", "level": 2},
        {"scenario_id": "desktop_drag_no_fallback", "runner": "practice_mouse_selection", "skill_label": "mouse", "level": 2},
        {"scenario_id": "desktop_drag_real_verify", "runner": "practice_mouse_workflow", "skill_label": "mouse", "level": 3},
        {"scenario_id": "desktop_recovery_verified", "runner": "practice_mouse_workflow", "skill_label": "mouse", "level": 4},
        {"scenario_id": "desktop_adversarial_verify", "runner": "practice_mouse_workflow", "skill_label": "mouse", "level": 5},
        {"scenario_id": "desktop_autonomous_discovery", "runner": "practice_mouse_workflow", "skill_label": "mouse", "level": 5},
    ],
    "research": [
        {"scenario_id": "research_single_source", "runner": "practice_skill", "skill_label": "investigar", "level": 0},
        {"scenario_id": "research_multi_query", "runner": "practice_skill", "skill_label": "investigar", "level": 2},
        {"scenario_id": "research_structured_extract", "runner": "practice_skill", "skill_label": "investigar", "level": 3},
        {"scenario_id": "research_discard_poor", "runner": "practice_skill", "skill_label": "investigar", "level": 3},
        {"scenario_id": "research_to_document", "runner": "practice_skill", "skill_label": "investigar", "level": 4, "create_document": True},
        {"scenario_id": "research_cross_verify", "runner": "practice_skill", "skill_label": "investigar", "level": 4, "create_document": True},
        {"scenario_id": "research_adversarial_recovery", "runner": "practice_skill", "skill_label": "investigar", "level": 5, "create_document": True},
        {"scenario_id": "research_autonomous_discovery", "runner": "practice_skill", "skill_label": "investigar", "level": 5, "create_document": True},
    ],
    "browser": [
        {"scenario_id": "browser_open_google", "runner": "practice_skill", "skill_label": "brave", "level": 0},
        {"scenario_id": "browser_search_result", "runner": "practice_skill", "skill_label": "brave", "level": 2},
        {"scenario_id": "browser_form_fill", "runner": "practice_skill", "skill_label": "youtube", "level": 3},
        {
            "scenario_id": "youtube_audio_visual_interpretation",
            "base_scenario_id": "browser_form_fill",
            "runner": "practice_skill",
            "skill_label": "youtube",
            "level": 3,
            "family": "browser",
            "training_goal": "tutorial basico con transcripcion o texto visible",
        },
    ],
    "file_manager/explorer": [
        {"scenario_id": "explorer_open_workspace", "runner": "practice_skill", "skill_label": "explorer", "level": 0},
        {"scenario_id": "explorer_select_item", "runner": "practice_skill", "skill_label": "explorer", "level": 1},
        {"scenario_id": "explorer_window_layout_stable", "runner": "practice_skill", "skill_label": "window management", "level": 1},
        {"scenario_id": "explorer_window_layout_repair", "runner": "practice_skill", "skill_label": "window management", "level": 2},
        {"scenario_id": "explorer_window_occlusion_recovery", "runner": "practice_skill", "skill_label": "window management", "level": 3},
        {"scenario_id": "explorer_move_verified", "runner": "practice_skill", "skill_label": "explorer", "level": 3},
    ],
    "document_editor": [
        {"scenario_id": "document_write_basic", "runner": "practice_skill", "skill_label": "notepad", "level": 0},
        {"scenario_id": "document_replace_text", "runner": "practice_skill", "skill_label": "notepad", "level": 1},
        {"scenario_id": "document_save_verified", "runner": "practice_skill", "skill_label": "notepad", "level": 3},
    ],
    "application_workflow": [
        {"scenario_id": "application_open_verify", "runner": "practice_skill", "skill_label": "youtube", "level": 0},
        {"scenario_id": "application_click_target", "runner": "practice_skill", "skill_label": "youtube", "level": 1},
        {"scenario_id": "application_goal_workflow", "runner": "practice_skill", "skill_label": "youtube", "level": 3},
    ],
    "game_foundation": [
        {"scenario_id": "game_input_foundation", "runner": "practice_skill", "skill_label": "jugar terraria", "level": 0},
        {"scenario_id": "game_control_lookup", "runner": "practice_skill", "skill_label": "jugar terraria", "level": 1},
        {"scenario_id": "game_goal_chain", "runner": "practice_skill", "skill_label": "jugar terraria", "level": 4},
    ],
}
