from __future__ import annotations

import os
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, quote_plus

from core.skills import normalize_text


class AutomationDependencyError(RuntimeError):
    """Se lanza cuando falta una dependencia opcional de automatizacion."""


def _import_pyautogui():
    try:
        import pyautogui
    except ImportError as exc:
        raise AutomationDependencyError(
            "Falta la dependencia 'pyautogui'. Instala requirements.txt."
        ) from exc
    return pyautogui


def _import_pyperclip():
    try:
        import pyperclip
    except ImportError as exc:
        raise AutomationDependencyError(
            "Falta la dependencia 'pyperclip'. Instala requirements.txt."
        ) from exc
    return pyperclip


def _import_pygetwindow():
    try:
        import pygetwindow as gw
    except ImportError as exc:
        raise AutomationDependencyError(
            "Falta la dependencia 'pygetwindow'. Instala requirements.txt."
        ) from exc
    return gw


class DesktopAutomation:
    def __init__(self) -> None:
        try:
            pyautogui = _import_pyautogui()
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.15
        except AutomationDependencyError:
            pass

    def open_application(
        self,
        target: str,
        application_catalog: Optional[Dict[str, object]] = None,
        extra_args: Optional[List[str]] = None,
    ) -> str:
        resolved_name, executable = self.resolve_application(target, application_catalog)
        command = [executable]
        if extra_args:
            command.extend(extra_args)
        subprocess.Popen(command)
        return f"Aplicacion iniciada: {resolved_name} ({executable})"

    def open_browser(
        self,
        browser_name: str,
        browser_paths: Optional[Dict[str, List[str]]] = None,
        url: Optional[str] = None,
        private: bool = False,
    ) -> str:
        executable = self.resolve_browser(browser_name, browser_paths)
        command = [executable, *self._browser_private_args(browser_name, url, private)]
        if url:
            if not private or browser_name != "firefox":
                command.append(url)
        subprocess.Popen(command)
        suffix = " en modo privado" if private else ""
        return f"Navegador abierto: {browser_name}{suffix}" + (f" -> {url}" if url else "")

    def open_url(
        self,
        url: str,
        browser_name: Optional[str] = None,
        browser_paths: Optional[Dict[str, List[str]]] = None,
        private: bool = False,
    ) -> str:
        if browser_name:
            return self.open_browser(browser_name, browser_paths=browser_paths, url=url, private=private)
        webbrowser.open(url)
        return f"URL abierta: {url}"

    def open_spotify_search(self, query: str, spotify_web_url: str) -> str:
        uri = f"spotify:search:{quote(query)}"
        try:
            os.startfile(uri)
            return f"Spotify abierto con busqueda: {query}"
        except OSError:
            webbrowser.open(spotify_web_url.format(query=quote(query)))
            return f"Spotify web abierto con busqueda: {query}"

    def open_folder(self, folder_path: str) -> str:
        path = Path(folder_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"No existe la carpeta: {path}")
        os.startfile(str(path))
        return f"Carpeta abierta: {path}"

    def open_file_select(self, file_path: str) -> str:
        path = Path(file_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"No existe el archivo: {path}")
        subprocess.Popen(["explorer.exe", f"/select,{path}"])
        return f"Archivo seleccionado en Explorer: {path}"

    def write_text(self, text: str, interval: float = 0.02, use_clipboard: bool = False) -> str:
        pyautogui = _import_pyautogui()
        if use_clipboard:
            pyperclip = _import_pyperclip()
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        else:
            pyautogui.write(text, interval=interval)
        return "Texto escrito en la ventana activa."

    def write_text_to_window(
        self,
        window_title: str,
        text: str,
        use_clipboard: bool = True,
        press_enter: bool = False,
        search_shortcut: Optional[str] = None,
    ) -> str:
        self.focus_window(window_title)
        time.sleep(0.25)
        if search_shortcut:
            if "+" in search_shortcut:
                self.hotkey(*[part.strip() for part in search_shortcut.split("+") if part.strip()])
            else:
                self.press_keys([search_shortcut])
        self.write_text(text, use_clipboard=use_clipboard)
        if press_enter:
            self.press_keys(["enter"])
        return f"Texto enviado a la ventana '{window_title}'."

    def press_keys(self, keys: Sequence[str]) -> str:
        pyautogui = _import_pyautogui()
        for key in keys:
            pyautogui.press(key)
        return f"Teclas presionadas: {', '.join(keys)}"

    def press_and_wait(self, key: str, delay: float = 0.15) -> str:
        pyautogui = _import_pyautogui()
        pyautogui.press(key)
        time.sleep(delay)
        return f"Tecla presionada: {key}"

    def hotkey(self, *keys: str) -> str:
        pyautogui = _import_pyautogui()
        pyautogui.hotkey(*keys)
        return f"Atajo ejecutado: {' + '.join(keys)}"

    def alt_tab(self, repeats: int = 1, delay: float = 0.25) -> str:
        pyautogui = _import_pyautogui()
        repeats = max(1, int(repeats))
        for _ in range(repeats):
            pyautogui.hotkey("alt", "tab")
            time.sleep(delay)
        return f"Alt+Tab ejecutado {repeats} vez/veces."

    def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.1,
        duration: float = 0.15,
    ) -> str:
        pyautogui = _import_pyautogui()
        pyautogui.moveTo(x, y, duration=duration)
        pyautogui.click(x=x, y=y, button=button, clicks=clicks, interval=interval)
        return f"Click realizado en ({x}, {y}) con boton {button}."

    def move_mouse(self, x: int, y: int, duration: float = 0.25) -> str:
        pyautogui = _import_pyautogui()
        pyautogui.moveTo(x, y, duration=duration)
        return f"Mouse movido a ({x}, {y})."

    def drag_mouse(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.4,
        button: str = "left",
    ) -> str:
        pyautogui = _import_pyautogui()
        pyautogui.moveTo(start_x, start_y, duration=0.1)
        pyautogui.dragTo(end_x, end_y, duration=duration, button=button)
        return f"Drag completado de ({start_x}, {start_y}) a ({end_x}, {end_y})."

    def drag_mouse_precise(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.9,
        button: str = "left",
        pre_hold: float = 0.2,
        post_hold: float = 0.1,
        steps: int = 12,
        wiggle_pixels: int = 0,
    ) -> str:
        pyautogui = _import_pyautogui()
        steps = max(4, int(steps))
        pyautogui.moveTo(start_x, start_y, duration=0.12)
        pyautogui.mouseDown(button=button)
        try:
            time.sleep(max(0.0, pre_hold))
            if wiggle_pixels > 0:
                pyautogui.moveRel(wiggle_pixels, 0, duration=0.06)
                pyautogui.moveRel(-wiggle_pixels, 0, duration=0.06)
            per_step = max(0.01, duration / steps)
            for index in range(1, steps + 1):
                ratio = index / steps
                x = int(start_x + (end_x - start_x) * ratio)
                y = int(start_y + (end_y - start_y) * ratio)
                pyautogui.moveTo(x, y, duration=per_step)
            time.sleep(max(0.0, post_hold))
        finally:
            pyautogui.mouseUp(button=button)
        return f"Drag preciso completado de ({start_x}, {start_y}) a ({end_x}, {end_y})."

    def scroll(self, clicks: int) -> str:
        pyautogui = _import_pyautogui()
        pyautogui.scroll(clicks)
        return f"Scroll ejecutado: {clicks}"

    def search_google(
        self,
        query: str,
        url_template: str,
        browser_name: Optional[str] = None,
        browser_paths: Optional[Dict[str, List[str]]] = None,
        private: bool = False,
    ) -> str:
        safe_query = quote_plus(query.strip())
        url = url_template.format(query=safe_query)
        return self.open_url(
            url,
            browser_name=browser_name,
            browser_paths=browser_paths,
            private=private,
        )

    def search_youtube(
        self,
        query: str,
        url_template: str,
        browser_name: Optional[str] = None,
        browser_paths: Optional[Dict[str, List[str]]] = None,
        private: bool = False,
    ) -> str:
        safe_query = quote_plus(query.strip())
        url = url_template.format(query=safe_query)
        return self.open_url(
            url,
            browser_name=browser_name,
            browser_paths=browser_paths,
            private=private,
        )

    def media_control(self, action: str) -> str:
        key_map = {
            "play_pause": "playpause",
            "next": "nexttrack",
            "previous": "prevtrack",
            "stop": "stop",
            "mute": "volumemute",
            "volume_up": "volumeup",
            "volume_down": "volumedown",
        }
        if action not in key_map:
            raise ValueError(f"Accion multimedia no soportada: {action}")
        pyautogui = _import_pyautogui()
        pyautogui.press(key_map[action])
        return f"Accion multimedia ejecutada: {action}"

    def set_volume(self, direction: str, steps: int = 5) -> str:
        if steps < 1:
            raise ValueError("Los pasos de volumen deben ser mayores que 0.")
        action = "volume_up" if direction == "up" else "volume_down"
        for _ in range(steps):
            self.media_control(action)
            time.sleep(0.03)
        return f"Volumen ajustado: {direction} ({steps} pasos)."

    def set_volume_percent(self, percent: int) -> str:
        percent = max(0, min(100, int(percent)))
        try:
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMasterVolumeLevelScalar(percent / 100.0, None)
            return f"Volumen ajustado exactamente al {percent}%."
        except ImportError:
            self._set_volume_percent_fallback(percent)
            return (
                f"Volumen ajustado aproximadamente al {percent}% usando atajos del teclado. "
                "Instala pycaw para un control exacto."
            )

    def _set_volume_percent_fallback(self, percent: int) -> None:
        pyautogui = _import_pyautogui()
        for _ in range(50):
            pyautogui.press("volumedown")
            time.sleep(0.01)
        steps = round(percent / 2)
        for _ in range(steps):
            pyautogui.press("volumeup")
            time.sleep(0.01)

    def list_windows(self, title_filter: Optional[str] = None) -> List[str]:
        gw = _import_pygetwindow()
        titles = [title for title in gw.getAllTitles() if title.strip()]
        if title_filter:
            target = normalize_text(title_filter)
            titles = [title for title in titles if target in normalize_text(title)]
        return titles

    def focus_window(self, title: str) -> str:
        window = self._find_window(title)
        if window.isMinimized:
            window.restore()
        window.activate()
        return f"Ventana activada: {window.title}"

    def get_active_window_title(self) -> Optional[str]:
        gw = _import_pygetwindow()
        active = gw.getActiveWindow()
        if not active:
            return None
        return active.title or None

    def get_mouse_position(self) -> Tuple[int, int]:
        pyautogui = _import_pyautogui()
        position = pyautogui.position()
        return int(position.x), int(position.y)

    def capture_selected_text(
        self,
        select_all: bool = True,
        settle_delay: float = 0.15,
        select_all_shortcut: Sequence[str] = ("ctrl", "a"),
    ) -> str:
        pyautogui = _import_pyautogui()
        pyperclip = _import_pyperclip()

        previous = pyperclip.paste()
        pyperclip.copy("")
        if select_all:
            pyautogui.hotkey(*select_all_shortcut)
            time.sleep(settle_delay)
        pyautogui.hotkey("ctrl", "c")
        time.sleep(settle_delay)
        captured = pyperclip.paste()
        if previous and captured == "":
            pyperclip.copy(previous)
        return captured or ""

    def close_current_window(self) -> str:
        return self.hotkey("alt", "f4")

    def close_window(self, title: str) -> str:
        self.focus_window(title)
        time.sleep(0.2)
        return self.close_current_window()

    def minimize_all_windows(self) -> str:
        return self.hotkey("winleft", "m")

    def maximize_current_window(self) -> str:
        return self.hotkey("winleft", "up")

    def switch_window(self, title: str) -> str:
        return self.focus_window(title)

    def browser_tab(self, mode: str) -> str:
        actions = {
            "new": ("ctrl", "t"),
            "close": ("ctrl", "w"),
            "next": ("ctrl", "tab"),
            "previous": ("ctrl", "shift", "tab"),
        }
        if mode not in actions:
            raise ValueError(f"Modo de pestaña no soportado: {mode}")
        return self.hotkey(*actions[mode])

    def run_shell(self, command: str, dangerous: bool = False) -> str:
        if dangerous:
            raise PermissionError(
                "run_shell peligroso requiere confirmacion explicita desde el asistente."
            )
        subprocess.Popen(command, shell=True)
        return f"Comando lanzado: {command}"

    def wait(self, seconds: float) -> str:
        time.sleep(seconds)
        return f"Espera completada: {seconds} segundos."

    def resolve_application(
        self,
        target: str,
        application_catalog: Optional[Dict[str, object]] = None,
    ) -> Tuple[str, str]:
        normalized_target = normalize_text(target)
        application_catalog = application_catalog or {}

        for app_name, value in application_catalog.items():
            command, aliases, paths = self._extract_entry_data(app_name, value)
            candidates = [normalize_text(app_name), *[normalize_text(alias) for alias in aliases]]
            if normalized_target in candidates:
                resolved = self._locate_executable([command, *paths, *aliases])
                return app_name, resolved

        for app_name, value in application_catalog.items():
            command, aliases, paths = self._extract_entry_data(app_name, value)
            haystack = " ".join([normalize_text(app_name), *[normalize_text(alias) for alias in aliases]])
            if normalized_target and normalized_target in haystack:
                resolved = self._locate_executable([command, *paths, *aliases])
                return app_name, resolved

        resolved = self._locate_executable([target])
        return target, resolved

    def resolve_browser(
        self,
        browser_name: str,
        browser_paths: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        normalized_target = normalize_text(browser_name)
        browser_paths = browser_paths or {}
        for key, candidates in browser_paths.items():
            if normalized_target == normalize_text(key):
                return self._locate_executable(candidates)
        return self._locate_executable([browser_name])

    def _find_window(self, title: str):
        gw = _import_pygetwindow()
        normalized_title = normalize_text(title)
        candidates = [
            window
            for window in gw.getAllWindows()
            if window.title and normalized_title in normalize_text(window.title)
        ]
        if not candidates:
            raise FileNotFoundError(f"No se encontro ninguna ventana con titulo similar a '{title}'.")
        return candidates[0]

    @staticmethod
    def _extract_entry_data(app_name: str, value: object) -> Tuple[str, List[str], List[str]]:
        if isinstance(value, dict):
            command = str(value.get("command", app_name))
            aliases = [str(alias) for alias in value.get("aliases", [])]
            paths = [str(path) for path in value.get("paths", [])]
            return command, aliases, paths
        return str(value), [], []

    @staticmethod
    def _locate_executable(candidates: Sequence[str]) -> str:
        for candidate in candidates:
            expanded = os.path.expandvars(candidate)
            if Path(expanded).exists():
                return str(Path(expanded))
            which_result = shutil.which(expanded)
            if which_result:
                return which_result
        raise FileNotFoundError(
            f"No se encontro ningun ejecutable valido para: {', '.join(candidates)}"
        )

    @staticmethod
    def _browser_private_args(browser_name: str, url: Optional[str], private: bool) -> List[str]:
        if not private:
            return []
        if browser_name == "chrome" or browser_name == "brave":
            return ["--incognito"]
        if browser_name == "edge":
            return ["-inprivate"]
        if browser_name == "firefox":
            args = ["-private-window"]
            if url:
                args.append(url)
            return args
        return []
