from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Tuple

from core.automation import DesktopAutomation
from core.skills import normalize_text
from core.vision import MatchResult, ScreenVision, UIElement


class MouseController:
    """Controlador de mouse orientado a objetivos visuales."""

    def __init__(
        self,
        vision: ScreenVision,
        automation: DesktopAutomation,
        logger: Optional[Any] = None,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.vision = vision
        self.automation = automation
        self.logger = logger
        self.progress_callback = progress_callback

    def locate_and_click(
        self,
        image_template: str,
        confidence: float = 0.8,
        timeout: float = 10,
        button: str = "left",
        clicks: int = 1,
        app: Optional[str] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
        scroll_plan: Optional[Any] = None,
    ) -> str:
        self._emit(f"Buscando plantilla o target: {image_template}", "info")
        target = self._wait_for_target(
            target_name=image_template,
            confidence=confidence,
            timeout=timeout,
            app=app,
            region=region,
            scroll_plan=scroll_plan,
        )
        if not target:
            raise FileNotFoundError(f"No se pudo localizar '{image_template}' en pantalla.")

        self._emit("Moviendo mouse al objetivo localizado...", "info")
        x, y = self._target_center(target)
        self.automation.move_mouse(x, y, duration=0.28)
        time.sleep(0.08)
        self._emit("Dando click...", "info")
        self.automation.click(x, y, button=button, clicks=max(1, int(clicks)), duration=0.08)
        self._emit("Click confirmado.", "info")
        return f"Click realizado sobre {image_template} en ({x}, {y})."

    def locate_and_type(
        self,
        target_name: str,
        text: str,
        confidence: float = 0.8,
        timeout: float = 10,
        select_all: bool = True,
        press_enter: bool = False,
        use_clipboard: bool = True,
        interval: float = 0.02,
        app: Optional[str] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
        scroll_plan: Optional[Any] = None,
    ) -> str:
        self.locate_and_click(
            image_template=target_name,
            confidence=confidence,
            timeout=timeout,
            button="left",
            app=app,
            region=region,
            scroll_plan=scroll_plan,
        )
        time.sleep(0.08)
        if select_all:
            self._emit("Seleccionando texto previo...", "info")
            self.automation.hotkey("ctrl", "a")
        self._emit("Escribiendo texto...", "info")
        self.automation.write_text(text, interval=interval, use_clipboard=use_clipboard)
        if press_enter:
            self._emit("Enviando Enter...", "info")
            self.automation.press_keys(["enter"])
        return f"Texto enviado a {target_name}: {text}"

    def click_ui_target(
        self,
        target_name: str,
        timeout: float = 8,
        app: Optional[str] = None,
        fallback_hotkey: Optional[Sequence[str]] = None,
    ) -> str:
        try:
            return self.locate_and_click(
                image_template=target_name,
                confidence=0.8,
                timeout=timeout,
                app=app,
            )
        except Exception as exc:
            self._emit(f"No se encontro {target_name}: {exc}", "warning")
            if fallback_hotkey:
                keys = [str(item) for item in fallback_hotkey]
                self._emit(f"Aplicando fallback por atajo: {' + '.join(keys)}", "info")
                self.automation.hotkey(*keys)
                return f"Fallback ejecutado para {target_name}: {' + '.join(keys)}"
            raise

    def focus_or_launch_app(
        self,
        app_name: str,
        taskbar_target: Optional[str] = None,
        launch_callback: Optional[Callable[[], str]] = None,
    ) -> str:
        normalized_app = normalize_text(app_name)
        self._emit(f"Buscando ventana existente para {app_name}...", "info")
        windows = self.automation.list_windows()
        for title in windows:
            if normalized_app in normalize_text(title):
                self._emit(f"Reutilizando ventana existente: {title}", "info")
                return self.automation.focus_window(title)

        self._emit(f"No se encontro ventana directa para {app_name}. Probando Alt+Tab...", "info")
        for attempt in range(3):
            self.automation.alt_tab()
            time.sleep(0.25)
            active_title = self.automation.get_active_window_title() or ""
            if normalized_app in normalize_text(active_title):
                self._emit(f"Ventana localizada por Alt+Tab: {active_title}", "info")
                return f"Ventana recuperada por Alt+Tab: {active_title}"
            self._emit(f"Alt+Tab intento {attempt + 1} sin coincidencia.", "warning")

        if taskbar_target:
            try:
                self._emit(f"Intentando icono de taskbar: {taskbar_target}", "info")
                return self.click_ui_target(taskbar_target, timeout=4, app="taskbar")
            except Exception as exc:
                self._emit(f"No se pudo usar icono de taskbar: {exc}", "warning")

        if launch_callback:
            self._emit(f"Lanzando aplicacion nueva: {app_name}", "info")
            return launch_callback()

        raise FileNotFoundError(f"No se pudo enfocar ni lanzar la aplicacion '{app_name}'.")

    def scroll_until_found(
        self,
        target_name: str,
        max_scrolls: int = 6,
        scroll_amount: int = -500,
        confidence: float = 0.8,
    ) -> Optional[MatchResult]:
        for attempt in range(max_scrolls + 1):
            located = self.vision.locate_ui_target(target_name)
            if isinstance(located, MatchResult):
                return located
            if isinstance(located, UIElement):
                x, y = self._target_center(located)
                return MatchResult(
                    x=x,
                    y=y,
                    confidence=located.confidence,
                    width=located.width,
                    height=located.height,
                    source=located.source,
                    template_name=target_name,
                )
            if attempt >= max_scrolls:
                break
            self._emit("Aplicando scroll para seguir buscando...", "info")
            self.automation.scroll(scroll_amount)
            time.sleep(0.22)
        return None

    def click_at(self, x: int, y: int, button: str = "left", duration: float = 0.18) -> str:
        self._emit(f"Moviendo mouse a ({x}, {y})...", "info")
        self.automation.move_mouse(x, y, duration=duration)
        time.sleep(0.05)
        self._emit("Dando click en coordenadas...", "info")
        self.automation.click(x, y, button=button, duration=0.06)
        return f"Click realizado en ({x}, {y})."

    def _wait_for_target(
        self,
        target_name: str,
        confidence: float,
        timeout: float,
        app: Optional[str],
        region: Optional[Tuple[int, int, int, int]],
        scroll_plan: Optional[Any],
    ) -> Optional[MatchResult | UIElement]:
        if Path(target_name).exists():
            start = time.time()
            attempts = 0
            while time.time() - start <= timeout:
                attempts += 1
                match = self.vision.locate_image(
                    template_path=target_name,
                    confidence=confidence,
                    region=region,
                )
                if match:
                    return match
                if attempts % 2 == 0 and scroll_plan:
                    self._emit("Aplicando scroll por reintento de plantilla...", "info")
                    self._apply_scroll(scroll_plan)
                self._emit("No encontrada, reintentando...", "warning")
                time.sleep(0.35)
            return None

        start = time.time()
        attempts = 0
        while time.time() - start <= timeout:
            attempts += 1
            located = self.vision.locate_template(
                template_name=target_name,
                app=app,
                region=region,
                confidence=confidence,
                grayscale=True,
            )
            if not located:
                located = self.vision.locate_ui_target(target_name)
            if located:
                return located
            if attempts % 2 == 0 and scroll_plan:
                self._emit("Aplicando scroll...", "info")
                self._apply_scroll(scroll_plan)
            self._emit("No encontrada, reintentando...", "warning")
            time.sleep(0.35)
        return None

    def _apply_scroll(self, scroll_plan: Any) -> None:
        if callable(scroll_plan):
            scroll_plan()
            return
        if isinstance(scroll_plan, dict):
            amount = int(scroll_plan.get("amount", -500))
            self.automation.scroll(amount)
            return
        self.automation.scroll(-500)

    @staticmethod
    def _target_center(target: MatchResult | UIElement) -> Tuple[int, int]:
        return int(target.x), int(target.y)

    def _emit(self, message: str, level: str = "info") -> None:
        if self.logger:
            log_method = getattr(self.logger, level if hasattr(self.logger, level) else "info")
            log_method(message)
        if self.progress_callback:
            self.progress_callback(message, level)
