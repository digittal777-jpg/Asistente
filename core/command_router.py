from __future__ import annotations

import re
from typing import Callable, List, Tuple

from core.command_parser import CommandParser


class CommandRouter:
    def __init__(self, executor: Callable[[str, List[str]], str]) -> None:
        self.executor = executor
        self.patterns = [
            (r"^help$", lambda m: ("help", [])),
            (r"^exit$", lambda m: ("exit", [])),
            (r"^skills$", lambda m: ("skills", [])),
            (r"^vision-status$", lambda m: ("vision-status", [])),
            (r"^vision-on$", lambda m: ("vision-on", [])),
            (r"^vision-off$", lambda m: ("vision-off", [])),
            (r"^calibrate-ui$", lambda m: ("calibrate-ui", [])),
            (r"^memory$", lambda m: ("memory", [])),
            (r"^learning-status$", lambda m: ("learning-status", [])),
            (r"^(?:doctor|raphel-doctor|raphael-doctor)$", lambda m: ("doctor", [])),
            (
                r"^(?:p1-validation|validation-p1|validate-p1)(?:\s+(.+))?$",
                lambda m: ("p1-validation", m.group(1).split() if m.group(1) else []),
            ),
            (r"^reevaluate-levels$", lambda m: ("reevaluate-levels", [])),
            (r"^(?:reset|reset-runtime|runtime-reset|assistant-reset)$", lambda m: ("reset-runtime", [])),
            (
                r"^remote-console-start(?:\s+(\d+))?$",
                lambda m: ("remote-console-start", [m.group(1)] if m.group(1) else []),
            ),
            (
                r"^remote-console-online(?:\s+(\d+))?$",
                lambda m: ("remote-console-online", [m.group(1)] if m.group(1) else []),
            ),
            (r"^remote-console-stop$", lambda m: ("remote-console-stop", [])),
            (r"^remote-console-status$", lambda m: ("remote-console-status", [])),
            (
                r"^(?:input-training-start|training-loop-start)(?:\s+(\d+))?$",
                lambda m: ("input-training-start", [m.group(1)] if m.group(1) else []),
            ),
            (
                r"^(?:input-training-stop|training-loop-stop)$",
                lambda m: ("input-training-stop", []),
            ),
            (
                r"^(?:input-training-status|training-loop-status)$",
                lambda m: ("input-training-status", []),
            ),
            (r"^skill-learn\s+(.+)$", lambda m: ("skill-learn", [m.group(1)])),
            (r"^skill-practice\s+(.+)$", lambda m: ("skill-practice", [m.group(1)])),
            (r"^skill-evaluate(?:\s+(.+))?$", lambda m: ("skill-evaluate", [m.group(1)] if m.group(1) else [])),
            (
                r"^skill-use\s+(.+?)\|(.+?)(?:\|(document))?$",
                lambda m: ("skill-use", [m.group(1).strip(), m.group(2).strip(), (m.group(3) or "").strip()]),
            ),
            (r"^skill-bootstrap$", lambda m: ("skill-bootstrap", [])),
            (r"^skill-status(?:\s+(.+))?$", lambda m: ("skill-status", [m.group(1)] if m.group(1) else [])),
            (r"^autonomous-learn\s+(.+)$", lambda m: ("autonomous-learn", [m.group(1)])),
            (r"^autonomous-status$", lambda m: ("autonomous-status", [])),
            (r"^desktop-organize$", lambda m: ("desktop-organize", [])),
            (r"^desktop-organize-fast$", lambda m: ("desktop-organize-fast", [])),
            (r"^desktop-arrange-icons$", lambda m: ("desktop-arrange-icons", [])),
            (
                r"^desktop-practice-mouse(?:\s+(\d+))?$",
                lambda m: ("desktop-practice-mouse", [m.group(1)] if m.group(1) else []),
            ),
            (
                r"^desktop-practice-mouse-move(?:\s+(\d+))?$",
                lambda m: ("desktop-practice-mouse-move", [m.group(1)] if m.group(1) else []),
            ),
            (
                r"^desktop-practice-mouse-click(?:\s+(\d+))?$",
                lambda m: ("desktop-practice-mouse-click", [m.group(1)] if m.group(1) else []),
            ),
            (
                r"^desktop-practice-mouse-double-click(?:\s+(\d+))?$",
                lambda m: ("desktop-practice-mouse-double-click", [m.group(1)] if m.group(1) else []),
            ),
            (
                r"^desktop-practice-mouse-right-click(?:\s+(\d+))?$",
                lambda m: ("desktop-practice-mouse-right-click", [m.group(1)] if m.group(1) else []),
            ),
            (
                r"^desktop-practice-mouse-selection(?:\s+(\d+))?$",
                lambda m: ("desktop-practice-mouse-selection", [m.group(1)] if m.group(1) else []),
            ),
            (
                r"^desktop-practice-mouse-detection(?:\s+(\d+))?$",
                lambda m: ("desktop-practice-mouse-detection", [m.group(1)] if m.group(1) else []),
            ),
            (
                r"^desktop-practice-mouse-workflow(?:\s+(\d+))?$",
                lambda m: ("desktop-practice-mouse-workflow", [m.group(1)] if m.group(1) else []),
            ),
            (r"^desktop-undo-last$", lambda m: ("desktop-undo-last", [])),
            (r"^desktop-icons$", lambda m: ("desktop-icons", [])),
            (r"^desktop-learn\s+(.+)$", lambda m: ("desktop-learn", [m.group(1)])),
            (r"^desktop-click\s+(.+)$", lambda m: ("desktop-click", [m.group(1)])),
            (r"^desktop-open\s+(.+)$", lambda m: ("desktop-open", [m.group(1)])),
            (r"^run-skill\s+(.+)$", lambda m: ("run-skill", [m.group(1)])),
            (r"^learn-file\s+(.+)$", lambda m: ("learn-file", [m.group(1)])),
            (r"^open-project\s+(.+)$", lambda m: ("open-project", [m.group(1)])),
            (
                r"^open-browser\s+(.+?)(?:\s+(https?://\S+|\S+\.\S+))?$",
                lambda m: ("open-browser", [m.group(1), m.group(2)] if m.group(2) else [m.group(1)]),
            ),
            (r"^open-app\s+(.+)$", lambda m: ("open-app", [m.group(1)])),
            (r"^open-folder\s+(.+)$", lambda m: ("open-folder", [m.group(1)])),
            (r"^open-url\s+(.+)$", lambda m: ("open-url", [m.group(1)])),
            (r"^type\s+(.+)$", lambda m: ("type", [m.group(1)])),
            (r"^write-window\s+(.+?)\|(.+)$", lambda m: ("write-window", [m.group(1), m.group(2)])),
            (r"^hotkey\s+(.+)$", lambda m: ("hotkey", m.group(1).split("+"))),
            (r"^click\s+(\d+)\s+(\d+)$", lambda m: ("click", [m.group(1), m.group(2)])),
            (
                r"^drag\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)$",
                lambda m: ("drag", [m.group(1), m.group(2), m.group(3), m.group(4)]),
            ),
            (r"^move\s+(\d+)\s+(\d+)$", lambda m: ("move", [m.group(1), m.group(2)])),
            (r"^click-image\s+(.+)$", lambda m: ("click-image", [m.group(1)])),
            (r"^screenshot(?:\s+(.+))?$", lambda m: ("screenshot", [m.group(1)] if m.group(1) else [])),
            (r"^google\s+(.+)$", lambda m: ("google", [m.group(1)])),
            (r"^youtube\s+(.+)$", lambda m: ("youtube", [m.group(1)])),
            (r"^spotify\s+(.+)$", lambda m: ("spotify", [m.group(1)])),
            (r"^volume\s+(up|down)(?:\s+(\d+))?$", lambda m: ("volume", [m.group(1), m.group(2) or "5"])),
            (r"^volume-set\s+(\d{1,3})$", lambda m: ("volume-set", [m.group(1)])),
            (r"^media\s+(.+)$", lambda m: ("media", [m.group(1)])),
            (r"^ocr$", lambda m: ("ocr", [])),
            (r"^find-text\s+(.+)$", lambda m: ("find-text", [m.group(1)])),
            (r"^pixel-color\s+(\d+)\s+(\d+)$", lambda m: ("pixel-color", [m.group(1), m.group(2)])),
            (
                r"^find-color\s+(\d+),(\d+),(\d+)(?:\s+(\d+))?$",
                lambda m: ("find-color", [m.group(1), m.group(2), m.group(3), m.group(4) or "10"]),
            ),
            (r"^focus-window\s+(.+)$", lambda m: ("focus-window", [m.group(1)])),
            (r"^close-window(?:\s+(.+))?$", lambda m: ("close-window", [m.group(1)] if m.group(1) else [])),
            (r"^maximize-window$", lambda m: ("maximize-window", [])),
            (r"^minimize-all$", lambda m: ("minimize-all", [])),
            (r"^tab\s+(new|close|next|previous)$", lambda m: ("tab", [m.group(1)])),
            (r"^remind\s+(\d+)\s+(.+)$", lambda m: ("remind", [m.group(1), m.group(2)])),
            (r"^history$", lambda m: ("history", [])),
        ]

    def route(self, raw_command: str) -> str:
        action, args = self.match_command(raw_command)
        return self.executor(action, args)

    def match_command(self, raw_command: str) -> Tuple[str, List[str]]:
        command = raw_command.strip()
        if not command:
            return "natural", [""]

        if "|" in command and command.lower().startswith("learn "):
            return "learn", [segment.strip() for segment in command[6:].split("|", 2)]

        if "|" in command and command.lower().startswith("feedback "):
            return "feedback", [segment.strip() for segment in command[9:].split("|", 1)]

        for pattern, handler in self.patterns:
            match = re.match(pattern, command, flags=re.IGNORECASE)
            if match:
                return handler(match)

        return "natural", [command]

    def is_natural_command(self, raw_command: str) -> bool:
        action, _ = self.match_command(raw_command)
        return action == "natural"

    @staticmethod
    def example_commands() -> str:
        return "\n".join(f"- {item}" for item in CommandParser.supported_examples())
