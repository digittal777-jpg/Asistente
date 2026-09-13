from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.data_paths import DataPaths
from core.logging_utils import ensure_directory
from core.skills import normalize_text


class VisionDependencyError(RuntimeError):
    """Se lanza cuando falta una dependencia opcional de vision."""


def _import_numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise VisionDependencyError(
            "Falta la dependencia 'numpy'. Instala requirements.txt."
        ) from exc
    return np


def _import_cv2():
    try:
        import cv2
    except ImportError as exc:
        raise VisionDependencyError(
            "Falta la dependencia 'opencv-python'. Instala requirements.txt."
        ) from exc
    return cv2


def _import_mss():
    try:
        import mss
    except ImportError as exc:
        raise VisionDependencyError(
            "Falta la dependencia 'mss'. Instala requirements.txt."
        ) from exc
    return mss


def _import_pil_image():
    try:
        from PIL import Image
    except ImportError as exc:
        raise VisionDependencyError(
            "Falta la dependencia 'pillow'. Instala requirements.txt."
        ) from exc
    return Image


def _import_tesseract():
    try:
        import pytesseract
    except ImportError as exc:
        raise VisionDependencyError(
            "Falta la dependencia 'pytesseract'. Instala requirements.txt."
        ) from exc
    return pytesseract


def tesseract_runtime_available() -> Tuple[bool, str]:
    try:
        pytesseract = _import_tesseract()
    except VisionDependencyError as exc:
        return False, str(exc)
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        return False, "pytesseract esta instalado, pero falta el ejecutable de Tesseract OCR en el PATH."
    except Exception:
        # Si el modulo esta presente y la consulta de version falla por una causa ajena
        # al ejecutable, no bloqueamos el dominio completo desde el scheduler.
        return True, ""
    return True, ""


def _import_pygetwindow():
    try:
        import pygetwindow as gw
    except ImportError as exc:
        raise VisionDependencyError(
            "Falta la dependencia 'pygetwindow'. Instala requirements.txt."
        ) from exc
    return gw


@dataclass
class MatchResult:
    x: int
    y: int
    confidence: float
    width: int
    height: int
    source: str = "template"
    template_name: str = ""
    region: Optional[Tuple[int, int, int, int]] = None


@dataclass
class UIElement:
    name: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 0.75
    source: str = "heuristic"


@dataclass
class WindowContext:
    title: str
    app_name: Optional[str]
    site_hint: Optional[str]
    left: int
    top: int
    width: int
    height: int
    is_active: bool = False


@dataclass
class VisionSnapshot:
    captured_at: str
    monitor_interval: float
    active_window: Optional[str]
    active_app: Optional[str]
    active_site: Optional[str]
    browsers_open: List[str] = field(default_factory=list)
    youtube_visible: bool = False
    gmail_visible: bool = False
    spotify_visible: bool = False
    windows: List[WindowContext] = field(default_factory=list)
    elements: List[UIElement] = field(default_factory=list)
    ocr_excerpt: str = ""
    notes: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


DEFAULT_TARGET_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "youtube_search_bar": {"app": "youtube", "capture_size": [460, 62]},
    "youtube_search_button": {"app": "youtube", "capture_size": [72, 56]},
    "google_search_bar": {"app": "google", "capture_size": [540, 70]},
    "google_result_card": {"app": "google", "capture_size": [760, 120]},
    "browser_address_bar": {"app": "browser", "capture_size": [620, 58]},
    "taskbar_brave": {"app": "taskbar", "capture_size": [72, 72]},
    "taskbar_word": {"app": "taskbar", "capture_size": [72, 72]},
    "taskbar_spotify": {"app": "taskbar", "capture_size": [72, 72]},
    "document_body": {"app": "document", "capture_size": [720, 440]},
}


class ScreenVision:
    BROWSER_APPS = {"brave", "chrome", "edge", "firefox"}

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        base_dir: Optional[Path] = None,
    ) -> None:
        self._config = config or {}
        self.base_dir = Path(base_dir or Path.cwd())
        self.paths = DataPaths.from_base_dir(self.base_dir)
        self.assets_dir = self.base_dir / "assets" / "ui" / "default"
        self.profile_dir = self.paths.default_ui_profile_dir
        self.default_manifest_path = self.assets_dir / "manifest.json"
        self.profile_manifest_path = self.paths.default_ui_profile_manifest_path
        ensure_directory(self.assets_dir)
        ensure_directory(self.profile_dir)

        self._last_capture = None
        self._latest_snapshot: Optional[VisionSnapshot] = None
        self._snapshot_lock = threading.Lock()
        self._listeners: List[Callable[[VisionSnapshot], None]] = []
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._interval = float(self._config.get("interval_seconds", 1.5))
        self._ocr_enabled = bool(self._config.get("light_ocr", True))

        self._target_definitions = self._load_target_definitions()
        self._ensure_profile_manifest()

    def add_snapshot_listener(self, callback: Callable[[VisionSnapshot], None]) -> None:
        self._listeners.append(callback)

    def start_monitor(
        self,
        interval_seconds: Optional[float] = None,
        light_ocr: Optional[bool] = None,
    ) -> bool:
        if self.is_monitoring:
            return False

        self._interval = float(interval_seconds or self._interval or 1.5)
        if light_ocr is not None:
            self._ocr_enabled = bool(light_ocr)

        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        return True

    def stop_monitor(self) -> bool:
        if not self.is_monitoring:
            return False
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.5)
        self._monitor_thread = None
        return True

    @property
    def is_monitoring(self) -> bool:
        return bool(self._monitor_thread and self._monitor_thread.is_alive())

    def get_latest_snapshot(self, refresh: bool = False) -> VisionSnapshot:
        if refresh or self._latest_snapshot is None:
            snapshot = self.scan_desktop()
            self._store_snapshot(snapshot)
            return snapshot
        with self._snapshot_lock:
            return self._latest_snapshot

    def get_target_definition(self, name: str) -> Dict[str, Any]:
        normalized = normalize_text(name)
        return dict(self._target_definitions.get(normalized, {}))

    def list_ui_targets(
        self,
        prefix: str,
        snapshot: Optional[VisionSnapshot] = None,
    ) -> List[UIElement]:
        current = snapshot or self.get_latest_snapshot()
        normalized_prefix = normalize_text(prefix)
        results = []
        for element in current.elements:
            if normalize_text(element.name).startswith(normalized_prefix):
                results.append(element)
        return results

    def scan_desktop(self) -> VisionSnapshot:
        windows = self._collect_windows()
        active_window = next((window for window in windows if window.is_active), None)
        notes: List[str] = []
        ocr_excerpt = ""

        if active_window and self._ocr_enabled and active_window.app_name in self.BROWSER_APPS:
            try:
                ocr_excerpt = self._ocr_active_browser_header(active_window)
            except VisionDependencyError as exc:
                notes.append(str(exc))
            except Exception as exc:  # pragma: no cover
                notes.append(f"OCR ligero no disponible: {exc}")

        active_title = active_window.title if active_window else None
        active_app = active_window.app_name if active_window else None
        active_site = self._infer_site(active_title or "", ocr_excerpt)

        elements = self._build_ui_hints(active_window, active_site)
        browser_windows = [window.app_name for window in windows if window.app_name in self.BROWSER_APPS]

        snapshot = VisionSnapshot(
            captured_at=datetime.now().isoformat(timespec="seconds"),
            monitor_interval=self._interval,
            active_window=active_title,
            active_app=active_app,
            active_site=active_site,
            browsers_open=[name for name in browser_windows if name],
            youtube_visible=any(self._window_matches(window, "youtube") for window in windows)
            or "youtube" in normalize_text(ocr_excerpt),
            gmail_visible=any(self._window_matches(window, "gmail") for window in windows)
            or "gmail" in normalize_text(ocr_excerpt),
            spotify_visible=any(self._window_matches(window, "spotify") for window in windows),
            windows=windows,
            elements=elements,
            ocr_excerpt=ocr_excerpt,
            notes=notes,
            confidence=self._estimate_confidence(active_window, active_site, ocr_excerpt),
        )
        return snapshot

    def find_ui_element(
        self,
        name: str,
        snapshot: Optional[VisionSnapshot] = None,
    ) -> Optional[UIElement]:
        current = snapshot or self.get_latest_snapshot()
        target = normalize_text(name)
        for element in current.elements:
            if normalize_text(element.name) == target:
                return element
        for element in current.elements:
            if target in normalize_text(element.name):
                return element
        return None

    def capture_screen(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
        save_path: Optional[str] = None,
    ):
        mss = _import_mss()
        Image = _import_pil_image()

        with mss.MSS() as sct:
            monitor = (
                {"left": region[0], "top": region[1], "width": region[2], "height": region[3]}
                if region
                else sct.monitors[0]
            )
            shot = sct.grab(monitor)
            image = Image.frombytes("RGB", shot.size, shot.rgb)
            self._last_capture = image
            if save_path:
                Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                image.save(save_path)
            return image

    def capture_screen_cv(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
        grayscale: bool = False,
    ):
        np = _import_numpy()
        cv2 = _import_cv2()
        image = self.capture_screen(region=region)
        bgr = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        if grayscale:
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        return bgr

    def locate_image(
        self,
        template_path: str,
        confidence: float = 0.85,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[MatchResult]:
        return self._locate_template_path(
            template_path=Path(template_path),
            confidence=confidence,
            region=region,
            grayscale=False,
            template_name=Path(template_path).stem,
        )

    def locate_template(
        self,
        template_name: str,
        app: Optional[str] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
        confidence: float = 0.8,
        grayscale: bool = True,
    ) -> Optional[MatchResult]:
        direct_path = Path(template_name)
        if direct_path.exists():
            return self._locate_template_path(
                template_path=direct_path,
                confidence=confidence,
                region=region,
                grayscale=grayscale,
                template_name=direct_path.stem,
            )

        for path, source in self._candidate_template_paths(template_name, app):
            match = self._locate_template_path(
                template_path=path,
                confidence=confidence,
                region=region,
                grayscale=grayscale,
                template_name=template_name,
                source=source,
            )
            if match:
                return match
        return None

    def wait_for_template(
        self,
        template_name: str,
        app: Optional[str] = None,
        confidence: float = 0.8,
        timeout: float = 10,
        poll_interval: float = 0.4,
        scroll_plan: Optional[Any] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[MatchResult]:
        start = time.time()
        attempts = 0
        scoped_region = region or self._infer_active_search_region(app)
        while time.time() - start <= timeout:
            attempts += 1
            match = self.locate_template(
                template_name=template_name,
                app=app,
                region=scoped_region,
                confidence=confidence,
                grayscale=True,
            )
            if match:
                return match

            if attempts % 2 == 0 and scroll_plan:
                self._execute_scroll_plan(scroll_plan)

            if attempts >= 3 and scoped_region is not None:
                scoped_region = None
            time.sleep(poll_interval)
        return None

    def locate_ui_target(
        self,
        target_name: str,
        snapshot: Optional[VisionSnapshot] = None,
        timeout: float = 0,
    ) -> Optional[UIElement | MatchResult]:
        current = snapshot or self.get_latest_snapshot()
        active_site = getattr(current, "active_site", None)
        active_app = getattr(current, "active_app", None)
        app_hint = active_site or active_app

        match = self.locate_template(
            template_name=target_name,
            app=app_hint,
            confidence=0.8,
            region=self._infer_active_search_region(app_hint),
            grayscale=True,
        )
        if match:
            return match

        if timeout > 0:
            waited = self.wait_for_template(
                template_name=target_name,
                app=app_hint,
                confidence=0.8,
                timeout=timeout,
            )
            if waited:
                return waited

        element = self.find_ui_element(target_name, snapshot=current)
        if element:
            return element

        return self._ocr_fallback_target(target_name, current)

    def calibrate_template(
        self,
        name: str,
        region: Tuple[int, int, int, int],
        app: str,
        save_local: bool = True,
    ) -> str:
        target_name = normalize_text(name)
        app_name = normalize_text(app)
        directory = self.profile_dir / app_name
        ensure_directory(directory)
        filename = f"{target_name}.png"
        output_path = directory / filename
        self.capture_screen(region=region, save_path=str(output_path))

        if save_local:
            manifest = self._load_manifest(self.profile_manifest_path)
            targets = manifest.setdefault("targets", {})
            target_entry = targets.setdefault(target_name, {})
            target_entry.update(
                {
                    "app": app_name,
                    "path": f"{app_name}/{filename}",
                    "preferred_region": list(region),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            with self.profile_manifest_path.open("w", encoding="utf-8") as handle:
                json.dump(manifest, handle, indent=2, ensure_ascii=False)
        return str(output_path)

    def calibrate_template_from_point(
        self,
        name: str,
        center_x: int,
        center_y: int,
        app: str,
        size: Optional[Tuple[int, int]] = None,
    ) -> str:
        definition = self.get_target_definition(name)
        capture_width, capture_height = size or tuple(definition.get("capture_size", [220, 80]))
        region = (
            max(0, int(center_x - capture_width / 2)),
            max(0, int(center_y - capture_height / 2)),
            int(capture_width),
            int(capture_height),
        )
        return self.calibrate_template(name=name, region=region, app=app, save_local=True)

    def extract_text(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
        lang: str = "eng",
    ) -> str:
        pytesseract = _import_tesseract()
        image = self.capture_screen(region=region)
        try:
            return pytesseract.image_to_string(image, lang=lang).strip()
        except pytesseract.TesseractNotFoundError as exc:
            raise VisionDependencyError(
                "pytesseract esta instalado, pero falta el ejecutable de Tesseract OCR en el PATH."
            ) from exc

    def extract_text_regions(
        self,
        regions: Dict[str, Tuple[int, int, int, int]],
        lang: str = "eng",
    ) -> Dict[str, str]:
        results: Dict[str, str] = {}
        for name, region in regions.items():
            results[name] = self.extract_text(region=region, lang=lang)
        return results

    def find_text(
        self,
        target_text: str,
        region: Optional[Tuple[int, int, int, int]] = None,
        lang: str = "eng",
    ) -> bool:
        extracted = self.extract_text(region=region, lang=lang)
        return target_text.lower() in extracted.lower()

    def get_pixel_color(self, x: int, y: int) -> Tuple[int, int, int]:
        image = self.capture_screen()
        return image.getpixel((x, y))

    def find_color(
        self,
        target_rgb: Sequence[int],
        tolerance: int = 10,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> List[Tuple[int, int]]:
        np = _import_numpy()
        image = self.capture_screen(region=region)
        pixels = np.array(image)
        target = np.array(target_rgb)
        diff = np.abs(pixels - target)
        mask = np.all(diff <= tolerance, axis=2)
        positions = np.argwhere(mask)

        offset_x = region[0] if region else 0
        offset_y = region[1] if region else 0
        return [
            (int(col + offset_x), int(row + offset_y))
            for row, col in positions[:500]
        ]

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                snapshot = self.scan_desktop()
                self._store_snapshot(snapshot)
            except Exception:
                pass
            self._stop_event.wait(self._interval)

    def _store_snapshot(self, snapshot: VisionSnapshot) -> None:
        with self._snapshot_lock:
            self._latest_snapshot = snapshot
        for callback in list(self._listeners):
            try:
                callback(snapshot)
            except Exception:
                continue

    def _collect_windows(self) -> List[WindowContext]:
        try:
            gw = _import_pygetwindow()
        except VisionDependencyError:
            return []

        active_title = ""
        try:
            active_window = gw.getActiveWindow()
            active_title = active_window.title if active_window else ""
        except Exception:
            active_title = ""

        results: List[WindowContext] = []
        try:
            all_windows = gw.getAllWindows()
        except Exception:
            all_windows = []

        for window in all_windows:
            title = getattr(window, "title", "") or ""
            if not title.strip():
                continue
            try:
                left = int(getattr(window, "left", 0) or 0)
                top = int(getattr(window, "top", 0) or 0)
                width = int(getattr(window, "width", 0) or 0)
                height = int(getattr(window, "height", 0) or 0)
            except Exception:
                left, top, width, height = 0, 0, 0, 0

            app_name = self._infer_app(title)
            site_hint = self._infer_site(title)
            results.append(
                WindowContext(
                    title=title,
                    app_name=app_name,
                    site_hint=site_hint,
                    left=left,
                    top=top,
                    width=width,
                    height=height,
                    is_active=normalize_text(title) == normalize_text(active_title),
                )
            )
        return results

    def _ocr_active_browser_header(self, active_window: WindowContext) -> str:
        region = self._active_header_region(active_window)
        if region is None:
            return ""
        for language in ("eng", "spa+eng", "spa"):
            try:
                extracted = self.extract_text(region=region, lang=language).strip()
            except Exception:
                extracted = ""
            if extracted:
                return extracted
        return ""

    def _build_ui_hints(
        self,
        active_window: Optional[WindowContext],
        active_site: Optional[str],
    ) -> List[UIElement]:
        elements: List[UIElement] = []
        if active_window and active_window.width > 0 and active_window.height > 0:
            left = active_window.left
            top = active_window.top
            width = active_window.width
            height = active_window.height

            elements.append(
                UIElement(
                    name="browser_address_bar",
                    x=left + int(width * 0.48),
                    y=top + int(height * 0.095),
                    width=int(width * 0.58),
                    height=max(30, int(height * 0.05)),
                    confidence=0.68,
                )
            )

            if active_window.app_name in self.BROWSER_APPS:
                elements.extend(
                    [
                        UIElement(
                            name="browser_content_region",
                            x=left + int(width * 0.50),
                            y=top + int(height * 0.56),
                            width=int(width * 0.74),
                            height=int(height * 0.60),
                            confidence=0.70,
                        ),
                        UIElement(
                            name="browser_primary_reading_region",
                            x=left + int(width * 0.46),
                            y=top + int(height * 0.56),
                            width=int(width * 0.58),
                            height=int(height * 0.60),
                            confidence=0.74,
                        ),
                    ]
                )

            if active_site == "youtube":
                search_y = top + int(height * 0.14)
                elements.extend(
                    [
                        UIElement(
                            name="youtube_search_bar",
                            x=left + int(width * 0.49),
                            y=search_y,
                            width=int(width * 0.36),
                            height=max(34, int(height * 0.055)),
                            confidence=0.82,
                        ),
                        UIElement(
                            name="youtube_search_button",
                            x=left + int(width * 0.72),
                            y=search_y,
                            width=max(56, int(width * 0.06)),
                            height=max(34, int(height * 0.055)),
                            confidence=0.72,
                        ),
                        UIElement(
                            name="youtube_results_column",
                            x=left + int(width * 0.33),
                            y=top + int(height * 0.58),
                            width=max(360, int(width * 0.46)),
                            height=int(height * 0.60),
                            confidence=0.74,
                        ),
                        UIElement(
                            name="youtube_results_primary_region",
                            x=left + int(width * 0.33),
                            y=top + int(height * 0.58),
                            width=max(340, int(width * 0.42)),
                            height=int(height * 0.54),
                            confidence=0.76,
                        ),
                        UIElement(
                            name="youtube_watch_primary_region",
                            x=left + int(width * 0.41),
                            y=top + int(height * 0.63),
                            width=max(420, int(width * 0.46)),
                            height=int(height * 0.26),
                            confidence=0.75,
                        ),
                        UIElement(
                            name="youtube_watch_metadata_region",
                            x=left + int(width * 0.41),
                            y=top + int(height * 0.79),
                            width=max(420, int(width * 0.46)),
                            height=int(height * 0.22),
                            confidence=0.72,
                        ),
                        UIElement(
                            name="youtube_watch_sidebar_region",
                            x=left + int(width * 0.79),
                            y=top + int(height * 0.60),
                            width=max(260, int(width * 0.20)),
                            height=int(height * 0.56),
                            confidence=0.68,
                        ),
                        UIElement(
                            name="youtube_captions_region",
                            x=left + int(width * 0.41),
                            y=top + int(height * 0.54),
                            width=max(420, int(width * 0.44)),
                            height=max(58, int(height * 0.08)),
                            confidence=0.69,
                        ),
                        UIElement(
                            name="youtube_more_actions_button",
                            x=left + int(width * 0.58),
                            y=top + int(height * 0.86),
                            width=max(44, int(width * 0.05)),
                            height=max(30, int(height * 0.04)),
                            confidence=0.64,
                        ),
                        UIElement(
                            name="youtube_transcript_toggle",
                            x=left + int(width * 0.63),
                            y=top + int(height * 0.86),
                            width=max(150, int(width * 0.14)),
                            height=max(34, int(height * 0.045)),
                            confidence=0.66,
                        ),
                        UIElement(
                            name="youtube_transcript_region",
                            x=left + int(width * 0.78),
                            y=top + int(height * 0.72),
                            width=max(300, int(width * 0.22)),
                            height=int(height * 0.42),
                            confidence=0.67,
                        ),
                    ]
                )
                elements.extend(self._build_youtube_result_hints(active_window))
            elif active_site == "google":
                elements.extend(
                    [
                        UIElement(
                            name="google_search_bar",
                            x=left + int(width * 0.50),
                            y=top + int(height * 0.39),
                            width=int(width * 0.52),
                            height=max(38, int(height * 0.06)),
                            confidence=0.78,
                        ),
                        UIElement(
                            name="google_results_search_bar",
                            x=left + int(width * 0.42),
                            y=top + int(height * 0.14),
                            width=int(width * 0.42),
                            height=max(34, int(height * 0.05)),
                            confidence=0.74,
                        ),
                        UIElement(
                            name="google_results_column",
                            x=left + int(width * 0.28),
                            y=top + int(height * 0.57),
                            width=max(320, int(width * 0.36)),
                            height=int(height * 0.58),
                            confidence=0.77,
                        ),
                        UIElement(
                            name="google_results_primary_region",
                            x=left + int(width * 0.28),
                            y=top + int(height * 0.57),
                            width=max(300, int(width * 0.32)),
                            height=int(height * 0.52),
                            confidence=0.79,
                        ),
                    ]
                )
                elements.extend(self._build_google_result_hints(active_window))
            elif active_site == "spotify" or active_window.app_name == "spotify":
                elements.append(
                    UIElement(
                        name="spotify_search_bar",
                        x=left + int(width * 0.22),
                        y=top + int(height * 0.18),
                        width=int(width * 0.24),
                        height=max(34, int(height * 0.05)),
                        confidence=0.73,
                    )
                )
            elif active_window.app_name in {"word", "libreoffice writer", "notepad"}:
                elements.append(
                    UIElement(
                        name="document_body",
                        x=left + int(width * 0.50),
                        y=top + int(height * 0.42),
                        width=int(width * 0.70),
                        height=int(height * 0.60),
                        confidence=0.76,
                    )
                )
        elements.extend(self._build_taskbar_hints())
        return elements

    def _build_youtube_result_hints(self, active_window: WindowContext) -> List[UIElement]:
        left = active_window.left
        top = active_window.top
        width = active_window.width
        height = active_window.height
        hints: List[UIElement] = []
        result_center_x = left + int(width * 0.33)
        result_width = max(360, int(width * 0.44))
        title_center_x = left + int(width * 0.30)
        title_width = max(320, int(width * 0.36))
        base_y = top + int(height * 0.31)
        step_y = max(86, int(height * 0.12))
        for index in range(5):
            y = base_y + (index * step_y)
            hints.append(
                UIElement(
                    name=f"youtube_result_title_{index + 1}",
                    x=title_center_x,
                    y=y - max(8, int(height * 0.016)),
                    width=title_width,
                    height=max(34, int(height * 0.05)),
                    confidence=0.72,
                )
            )
            hints.append(
                UIElement(
                    name=f"youtube_result_card_{index + 1}",
                    x=result_center_x,
                    y=y,
                    width=result_width,
                    height=max(84, int(height * 0.12)),
                    confidence=0.70,
                )
            )
        if hints:
            first_title = next((item for item in hints if item.name.startswith("youtube_result_title_")), None)
            first_card = next((item for item in hints if item.name.startswith("youtube_result_card_")), None)
            if first_title:
                hints.append(
                    UIElement(
                        name="youtube_result_title",
                        x=first_title.x,
                        y=first_title.y,
                        width=first_title.width,
                        height=first_title.height,
                        confidence=first_title.confidence,
                    )
                )
            if first_card:
                hints.append(
                    UIElement(
                        name="youtube_result_card",
                        x=first_card.x,
                        y=first_card.y,
                        width=first_card.width,
                        height=first_card.height,
                        confidence=first_card.confidence,
                    )
                )
        return hints

    def _build_google_result_hints(self, active_window: WindowContext) -> List[UIElement]:
        left = active_window.left
        top = active_window.top
        width = active_window.width
        height = active_window.height
        hints: List[UIElement] = []
        result_column_center_x = left + int(width * 0.28)
        result_column_width = max(320, int(width * 0.34))
        title_center_x = left + int(width * 0.24)
        title_width = max(250, int(width * 0.26))
        base_y = top + int(height * 0.33)
        step_y = max(72, int(height * 0.11))
        for index in range(5):
            y = base_y + (index * step_y)
            hints.append(
                UIElement(
                    name=f"google_result_title_{index + 1}",
                    x=title_center_x,
                    y=y - max(8, int(height * 0.014)),
                    width=title_width,
                    height=max(30, int(height * 0.045)),
                    confidence=0.74,
                )
            )
            name = f"google_result_card_{index + 1}"
            hints.append(
                UIElement(
                    name=name,
                    x=result_column_center_x,
                    y=y,
                    width=result_column_width,
                    height=max(66, int(height * 0.09)),
                    confidence=0.70,
                )
            )
        if hints:
            first_title = next((item for item in hints if item.name.startswith("google_result_title_")), None)
            first_card = next((item for item in hints if item.name.startswith("google_result_card_")), None)
            if first_title:
                hints.append(
                    UIElement(
                        name="google_result_title",
                        x=first_title.x,
                        y=first_title.y,
                        width=first_title.width,
                        height=first_title.height,
                        confidence=first_title.confidence,
                    )
                )
            if first_card:
                hints.append(
                    UIElement(
                        name="google_result_card",
                        x=first_card.x,
                        y=first_card.y,
                        width=first_card.width,
                        height=first_card.height,
                        confidence=first_card.confidence,
                    )
                )
        return hints

    def _build_taskbar_hints(self) -> List[UIElement]:
        monitor = self._screen_bounds()
        if not monitor:
            return []
        left, top, width, height = monitor
        bar_y = top + height - 28
        return [
            UIElement("taskbar_brave", left + 130, bar_y, 64, 64, confidence=0.45),
            UIElement("taskbar_word", left + 210, bar_y, 64, 64, confidence=0.40),
            UIElement("taskbar_spotify", left + 290, bar_y, 64, 64, confidence=0.40),
        ]

    def _ocr_fallback_target(
        self,
        target_name: str,
        snapshot: VisionSnapshot,
    ) -> Optional[UIElement]:
        active_window = next((item for item in snapshot.windows if item.is_active), None)
        if not active_window:
            return None
        normalized = normalize_text(target_name)
        if normalized == "browser_address_bar":
            return self.find_ui_element("browser_address_bar", snapshot)
        if normalized in {"youtube_search_bar", "google_search_bar"}:
            return self.find_ui_element("browser_address_bar", snapshot)
        if normalized == "document_body":
            return UIElement(
                name="document_body",
                x=active_window.left + int(active_window.width * 0.5),
                y=active_window.top + int(active_window.height * 0.42),
                width=int(active_window.width * 0.70),
                height=int(active_window.height * 0.60),
                confidence=0.55,
                source="ocr_fallback",
            )
        return None

    def _locate_template_path(
        self,
        template_path: Path,
        confidence: float,
        region: Optional[Tuple[int, int, int, int]],
        grayscale: bool,
        template_name: str,
        source: str = "template",
    ) -> Optional[MatchResult]:
        if not template_path.exists():
            return None

        cv2 = _import_cv2()
        screenshot = self.capture_screen_cv(region=region, grayscale=grayscale)
        read_flag = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
        template = cv2.imread(str(template_path), read_flag)
        if template is None:
            return None

        result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < confidence:
            return None

        h, w = template.shape[:2]
        origin_x = region[0] if region else 0
        origin_y = region[1] if region else 0
        center_x = origin_x + max_loc[0] + w // 2
        center_y = origin_y + max_loc[1] + h // 2
        return MatchResult(
            x=center_x,
            y=center_y,
            confidence=float(max_val),
            width=w,
            height=h,
            source=source,
            template_name=template_name,
            region=region,
        )

    def _candidate_template_paths(
        self,
        template_name: str,
        app: Optional[str],
    ) -> List[Tuple[Path, str]]:
        normalized = normalize_text(template_name)
        candidates: List[Tuple[Path, str]] = []
        profile_manifest = self._load_manifest(self.profile_manifest_path)
        default_manifest = self._load_manifest(self.default_manifest_path)

        for manifest, base_path, source in (
            (profile_manifest, self.profile_dir, "local_profile"),
            (default_manifest, self.assets_dir, "bundled"),
        ):
            targets = manifest.get("targets", {})
            entry = targets.get(normalized, {})
            path_value = entry.get("path")
            if path_value:
                candidates.append((base_path / path_value, source))

        if app:
            normalized_app = normalize_text(app)
            candidates.append((self.profile_dir / normalized_app / f"{normalized}.png", "local_profile"))
            candidates.append((self.assets_dir / normalized_app / f"{normalized}.png", "bundled"))

        candidates.append((self.profile_dir / f"{normalized}.png", "local_profile"))
        candidates.append((self.assets_dir / f"{normalized}.png", "bundled"))

        deduped: List[Tuple[Path, str]] = []
        seen = set()
        for path, source in candidates:
            key = str(path.resolve()) if path.exists() else str(path)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((path, source))
        return deduped

    def _infer_active_search_region(self, app: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
        try:
            snapshot = self.get_latest_snapshot()
        except Exception:
            return None
        active_window = next((item for item in snapshot.windows if item.is_active), None)
        if not active_window:
            normalized_requested = normalize_text(app or "")
            if normalized_requested == "desktop":
                return self._screen_bounds()
            return None
        normalized = normalize_text(app or active_window.app_name or "")
        if normalized == "desktop":
            return self._screen_bounds()
        if normalized in {"youtube", "google", "brave", "chrome", "edge", "firefox", "browser"}:
            return (
                active_window.left,
                active_window.top,
                active_window.width,
                active_window.height,
            )
        return None

    def _execute_scroll_plan(self, scroll_plan: Any) -> None:
        if callable(scroll_plan):
            scroll_plan()
            return
        callback = None
        if isinstance(scroll_plan, dict):
            callback = scroll_plan.get("callback")
        if callable(callback):
            callback()

    def _screen_bounds(self) -> Optional[Tuple[int, int, int, int]]:
        try:
            mss = _import_mss()
            with mss.MSS() as sct:
                monitor = sct.monitors[0]
                return (
                    int(monitor["left"]),
                    int(monitor["top"]),
                    int(monitor["width"]),
                    int(monitor["height"]),
                )
        except Exception:
            return None

    @staticmethod
    def _active_header_region(active_window: WindowContext) -> Optional[Tuple[int, int, int, int]]:
        if active_window.width <= 0 or active_window.height <= 0:
            return None
        return (
            max(0, active_window.left + int(active_window.width * 0.12)),
            max(0, active_window.top + int(active_window.height * 0.03)),
            max(240, int(active_window.width * 0.76)),
            max(60, int(active_window.height * 0.12)),
        )

    @classmethod
    def _infer_app(cls, title: str) -> Optional[str]:
        normalized = normalize_text(title)
        if "brave" in normalized:
            return "brave"
        if "chrome" in normalized or "google chrome" in normalized:
            return "chrome"
        if "edge" in normalized:
            return "edge"
        if "firefox" in normalized:
            return "firefox"
        if "spotify" in normalized:
            return "spotify"
        if "visual studio code" in normalized or "vscode" in normalized:
            return "visual studio code"
        if "word" in normalized and "password" not in normalized:
            return "word"
        if "libreoffice writer" in normalized or "writer" in normalized:
            return "libreoffice writer"
        if "notepad" in normalized or "bloc de notas" in normalized:
            return "notepad"
        if "explorer" in normalized or "file explorer" in normalized:
            return "explorer"
        return None

    @staticmethod
    def _infer_site(title: str, ocr_excerpt: str = "") -> Optional[str]:
        haystack = f"{title} {ocr_excerpt}".strip()
        normalized = normalize_text(haystack)
        site_keywords = {
            "youtube": ("youtube", "studio.youtube"),
            "gmail": ("gmail", "mail.google"),
            "google": ("google", "search"),
            "spotify": ("spotify",),
            "github": ("github",),
            "word": ("word",),
        }
        for canonical, keywords in site_keywords.items():
            if any(keyword in normalized for keyword in keywords):
                return canonical
        return None

    @staticmethod
    def _window_matches(window: WindowContext, token: str) -> bool:
        normalized = normalize_text(window.title)
        return token in normalized or normalize_text(window.site_hint or "") == normalize_text(token)

    @staticmethod
    def _estimate_confidence(
        active_window: Optional[WindowContext],
        active_site: Optional[str],
        ocr_excerpt: str,
    ) -> float:
        score = 0.35
        if active_window:
            score += 0.25
        if active_window and active_window.app_name:
            score += 0.15
        if active_site:
            score += 0.15
        if ocr_excerpt:
            score += 0.10
        return min(score, 0.95)

    def _load_target_definitions(self) -> Dict[str, Dict[str, Any]]:
        definitions = {normalize_text(key): dict(value) for key, value in DEFAULT_TARGET_DEFINITIONS.items()}
        manifest = self._load_manifest(self.default_manifest_path)
        for key, value in manifest.get("targets", {}).items():
            normalized = normalize_text(key)
            definitions.setdefault(normalized, {}).update(value)
        return definitions

    def _ensure_profile_manifest(self) -> None:
        if self.profile_manifest_path.exists():
            return
        manifest = {"profile": "default", "targets": {}}
        with self.profile_manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False)

    @staticmethod
    def _load_manifest(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {"targets": {}}
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return {"targets": {}}
