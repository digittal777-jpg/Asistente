from __future__ import annotations

import random
import threading
from typing import Any, Callable, Dict, List, Optional

from core.automation import DesktopAutomation
from core.autonomous_learning_system import AutonomousLearningSystem
from core.command_parser import CommandParser, set_default_parser
from core.command_router import CommandRouter
from core.config import ConfigManager
from core.desktop_learning_organizer import DesktopLearningOrganizer
from core.desktop_trainer import DesktopTrainer
from core.gui import RaphelGUI
from core.intelligent_learning import IntelligentLearningEngine
from core.learning_skill_engine import LearningSkillEngine
from core.logging_utils import ActionHistory, setup_logger
from core.memory import MemoryStore
from core.models.page_usefulness_classifier import PageUsefulnessClassifier
from core.models.ui_target_ranker import UITargetRankerModel
from core.mouse_controller import MouseController
from core.perception import PerceptionEngine
from core.recovery_engine import RecoveryEngine
from core.reminders import ReminderManager
from core.skill_manager import SkillManager
from core.task_executor import TaskExecutor
from core.task_planner import TaskPlanner
from core.training_loop_infinite import InfiniteTrainingLoop
from core.training_scheduler import SkillScheduler
from core.vision import ScreenVision


def initialize_assistant_runtime(assistant: Any) -> None:
    assistant.logger = setup_logger(assistant.base_dir)
    assistant.history = ActionHistory(assistant.base_dir)
    assistant.config = ConfigManager(assistant.base_dir)
    assistant.memory = MemoryStore(assistant.base_dir)
    assistant.learning = IntelligentLearningEngine(
        base_dir=assistant.base_dir,
        memory=assistant.memory,
        config=assistant.config,
        logger=assistant.logger,
    )
    assistant.automation = DesktopAutomation()
    assistant.vision = ScreenVision(assistant.config.get("vision", {}), base_dir=assistant.base_dir)
    assistant.perception = PerceptionEngine(assistant.vision)
    assistant.mouse_controller = MouseController(
        vision=assistant.vision,
        automation=assistant.automation,
        logger=assistant.logger,
        progress_callback=assistant.emit_status,
    )
    assistant._input_training_stop_event = threading.Event()
    assistant._input_training_thread = None
    assistant._input_training_lock = threading.Lock()
    assistant._input_training_cycle_count = 0
    assistant._input_training_last_result = "sin ciclos todavia"
    assistant._input_training_stop_path = assistant.paths.resolve_runtime_path("input_training_stop")
    assistant._input_training_rng = random.Random()
    assistant._input_training_escape_started_at = None
    assistant.desktop_trainer = DesktopTrainer(
        base_dir=assistant.base_dir,
        config=assistant.config,
        vision=assistant.vision,
        mouse_controller=assistant.mouse_controller,
        automation=assistant.automation,
        logger=assistant.logger,
        progress_callback=assistant.emit_status,
    )
    assistant.desktop_learning_organizer = DesktopLearningOrganizer(
        base_dir=assistant.base_dir,
        config=assistant.config,
        trainer=assistant.desktop_trainer,
        automation=assistant.automation,
        vision=assistant.vision,
        memory=assistant.memory,
        logger=assistant.logger,
        progress_callback=assistant.emit_status,
        stop_checker=assistant.input_training_stop_requested,
    )
    assistant.skill_manager = SkillManager(assistant.base_dir, assistant)
    assistant.command_parser = CommandParser(assistant.base_dir, assistant.config, assistant.skill_manager)
    set_default_parser(assistant.command_parser)
    assistant.task_planner = TaskPlanner(assistant.config, assistant.memory)
    assistant.task_executor = TaskExecutor(
        assistant=assistant,
        vision=assistant.vision,
        mouse_controller=assistant.mouse_controller,
        automation=assistant.automation,
        memory=assistant.memory,
        logger=assistant.logger,
        progress_callback=assistant.emit_status,
    )
    assistant.learning_skill_engine = LearningSkillEngine(
        base_dir=assistant.base_dir,
        config=assistant.config,
        memory=assistant.memory,
        learning=assistant.learning,
        automation=assistant.automation,
        task_executor=assistant.task_executor,
        mouse_controller=assistant.mouse_controller,
        assistant=assistant,
        logger=assistant.logger,
        progress_callback=assistant.emit_status,
    )
    assistant.recovery_engine = RecoveryEngine(
        base_dir=assistant.base_dir,
        learning=assistant.learning,
        logger=assistant.logger,
    )
    assistant.training_scheduler = SkillScheduler()
    assistant.ui_target_ranker = UITargetRankerModel()
    assistant.page_usefulness_classifier = PageUsefulnessClassifier()
    assistant.infinite_training_loop = InfiniteTrainingLoop(
        base_dir=assistant.base_dir,
        assistant=assistant,
        learning_skill_engine=assistant.learning_skill_engine,
        scheduler=assistant.training_scheduler,
        recovery_engine=assistant.recovery_engine,
        logger=assistant.logger,
        progress_callback=assistant.emit_status,
        stop_checker=assistant.input_training_stop_requested,
        ui_target_ranker=assistant.ui_target_ranker,
        page_usefulness_classifier=assistant.page_usefulness_classifier,
    )
    assistant.autonomous_learning_system = AutonomousLearningSystem(
        infinite_loop=assistant.infinite_training_loop,
        assistant=assistant,
        task_executor=assistant.task_executor,
        logger=assistant.logger,
    )
    assistant.router = CommandRouter(assistant._dispatch)
    assistant.reminders = ReminderManager(assistant.base_dir, assistant._notify)
    assistant.running = True
    assistant._status_listeners = []
    assistant._context_listeners = []
    assistant._confirmation_provider = None
