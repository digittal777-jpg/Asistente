from __future__ import annotations

import re
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote_plus
from xml.sax.saxutils import escape

from core.mouse_controller import MouseController
from core.skills import normalize_text
from core.task_planner import TaskPlan


RESEARCH_SCENE_RULES: Dict[str, Dict[str, str]] = {
    "google_results": {
        "read_policy": "leer titulos, snippets y columna principal",
        "ignore_policy": "ignorar chips, sidebar, footer y chrome de Google",
        "valid_exit_rule": "abrir una fuente real y confirmar salida de Google",
        "selection_phase": "never",
        "message": "Escena google_results: priorizo resultados visibles y evito Ctrl+A.",
    },
    "youtube_watch": {
        "read_policy": "leer transcript, captions, titulo y descripcion visible",
        "ignore_policy": "ignorar comentarios, recomendados y chrome del reproductor",
        "valid_exit_rule": "capturar transcript o texto visible alineado con la consulta",
        "selection_phase": "never",
        "message": "Escena youtube_watch: priorizo transcript y texto visible; evito Ctrl+A.",
    },
    "help_page": {
        "read_policy": "leer cuerpo principal, headings y bloques de ayuda",
        "ignore_policy": "ignorar nav, cookies y paneles laterales",
        "valid_exit_rule": "conservar solo ayuda alineada con la consulta",
        "selection_phase": "fallback",
        "message": "Escena help_page: leo contenido principal y dejo Ctrl+A solo como rescate tardio.",
    },
    "article_page": {
        "read_policy": "leer cuerpo, subtitulos, tablas y texto visible",
        "ignore_policy": "ignorar ads, related, footer y navegacion",
        "valid_exit_rule": "capturar texto util y alineado antes de contar la fuente",
        "selection_phase": "fallback",
        "message": "Escena article_page: leo regiones visibles primero y dejo Ctrl+A como ultimo recurso.",
    },
    "modal": {
        "read_policy": "leer solo titulo y cuerpo del modal",
        "ignore_policy": "ignorar la pagina de fondo",
        "valid_exit_rule": "cerrar o resolver el modal antes de seguir",
        "selection_phase": "never",
        "message": "Escena modal: diagnostico el bloqueo visible y evito Ctrl+A.",
    },
    "file_dialog": {
        "read_policy": "leer titulo y acciones del dialogo",
        "ignore_policy": "ignorar el fondo de la pagina",
        "valid_exit_rule": "cerrar o cancelar el dialogo y recuperar foco",
        "selection_phase": "never",
        "message": "Escena file_dialog: leo el cuadro visible y evito Ctrl+A.",
    },
    "blocked_page": {
        "read_policy": "leer mensaje de error, captcha o bloqueo",
        "ignore_policy": "ignorar chrome, ads y ruido del sitio",
        "valid_exit_rule": "identificar el bloqueo y retirarse a otra fuente",
        "selection_phase": "never",
        "message": "Escena blocked_page: leo el bloqueo visible y evito Ctrl+A.",
    },
}


class TaskExecutor:
    """Ejecutor de tareas complejas con logging paso a paso."""

    def __init__(
        self,
        assistant: Any,
        vision: Any,
        mouse_controller: MouseController,
        automation: Any,
        memory: Any,
        logger: Any,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.assistant = assistant
        self.vision = vision
        self.mouse = mouse_controller
        self.automation = automation
        self.memory = memory
        self.logger = logger
        self.progress_callback = progress_callback
        self._google_result_open_count = 0

    def run_task(self, plan: TaskPlan) -> str:
        self._emit(f"Iniciando task executor para intent '{plan.intent}'...", "info")
        if plan.intent == "research_document":
            return self.run_research_document(
                topic=plan.topic or plan.goal,
                browser=plan.browser or self.assistant.memory.get_preference("preferred_browser", "brave"),
                document_app=plan.document_app or "word",
                result_count=plan.result_count or 5,
            )

        results: List[str] = []
        for step in plan.steps:
            if step.requires_confirmation and not self.assistant.confirm_action(f"{step.summary}. Continuar?"):
                cancelled = f"Accion cancelada: {step.summary}"
                self.memory.record_step_log(plan.intent, step.summary or step.action, "cancelled", cancelled)
                results.append(cancelled)
                continue
            self._emit(f"Ejecutando paso: {step.summary or step.action}", "info")
            result = self.assistant.execute_action(step.action, step.params)
            self.memory.record_step_log(
                task_intent=plan.intent,
                step_name=step.summary or step.action,
                status="completed",
                detail=result,
            )
            results.append(result)
        return "\n".join(results)

    def run_search_flow(
        self,
        destination: str,
        query: str,
        browser: Optional[str] = None,
        private: bool = False,
    ) -> str:
        normalized_destination = normalize_text(destination)
        resolved_browser = browser or self.assistant.memory.get_preference("preferred_browser", "brave")
        self.assistant._current_action_trace.append(
            {
                "action": "smart_site_search",
                "params": {
                    "destination": normalized_destination,
                    "query": query,
                    "browser": resolved_browser,
                    "private": private,
                },
            }
        )

        if normalized_destination == "youtube":
            self._emit("Preparando YouTube...", "info")
            self.assistant.ensure_site("youtube", browser=resolved_browser, private=private)
            youtube_bar = self._preferred_strategy(
                "search:youtube",
                ["youtube_search_bar", "browser_address_bar"],
            )
            try:
                target_name = youtube_bar if youtube_bar in {"youtube_search_bar", "browser_address_bar"} else "youtube_search_bar"
                text_to_send = query
                press_enter = False
                if target_name == "browser_address_bar":
                    text_to_send = self.assistant.config.get("youtube_search_url").format(query=quote_plus(query))
                    press_enter = True
                entry_strategy = self._type_into_target(
                    domain="text_entry:search",
                    target_name=target_name,
                    text=text_to_send,
                    confidence=0.78,
                    timeout=8,
                    select_all=True,
                    press_enter=press_enter,
                )
                if target_name == "youtube_search_bar":
                    try:
                        self.mouse.click_ui_target("youtube_search_button", timeout=2.5, app="youtube")
                        self._record_strategy("search:youtube", "youtube_search_button", True)
                    except Exception:
                        self._emit("Boton de busqueda no encontrado; usando Enter.", "warning")
                        self._record_strategy("search:youtube", "youtube_search_button", False)
                        self.automation.press_keys(["enter"])
                result = f"Busqueda autonoma enviada a YouTube: {query}"
                self._record_strategy("search:youtube", target_name, True)
                self._record_action_outcome(
                    action="smart_site_search",
                    payload={
                        "destination": normalized_destination,
                        "query": query,
                        "browser": resolved_browser,
                        "private": private,
                        "preferred_target": target_name,
                        "text_entry_strategy": entry_strategy,
                    },
                    result=result,
                    success=True,
                )
                self.memory.record_step_log("search", "youtube_search", "completed", result)
                return result
            except Exception as exc:
                self._record_strategy("search:youtube", youtube_bar or "youtube_search_bar", False)
                self._emit(f"Fallo la barra de YouTube: {exc}. Aplicando fallback por URL.", "warning")
                search_url = self.assistant.config.get("youtube_search_url").format(query=quote_plus(query))
                try:
                    entry_strategy = self._type_into_target(
                        domain="text_entry:search",
                        target_name="browser_address_bar",
                        text=search_url,
                        confidence=0.72,
                        timeout=6,
                        select_all=True,
                        press_enter=True,
                    )
                    result = f"Busqueda enviada a YouTube por barra de direcciones: {query}"
                    self._record_strategy("search:youtube", "browser_address_bar", True)
                    self._record_action_outcome(
                        action="smart_site_search",
                        payload={
                            "destination": normalized_destination,
                            "query": query,
                            "browser": resolved_browser,
                            "private": private,
                            "preferred_target": "browser_address_bar",
                            "text_entry_strategy": entry_strategy,
                        },
                        result=result,
                        success=True,
                    )
                    self.memory.record_step_log("search", "youtube_search_fallback", "completed", result)
                    return result
                except Exception as fallback_exc:
                    self._record_action_outcome(
                        action="smart_site_search",
                        payload={
                            "destination": normalized_destination,
                            "query": query,
                            "browser": resolved_browser,
                            "private": private,
                            "preferred_target": youtube_bar or "youtube_search_bar",
                        },
                        result=str(fallback_exc),
                        success=False,
                    )
                    raise

        self._emit("Preparando Google...", "info")
        self.assistant.ensure_site("google", browser=resolved_browser, private=private)
        google_targets = self._rank_strategies(
            "search:google",
            ["google_results_search_bar", "google_search_bar", "browser_address_bar"],
        )
        for target_name in google_targets:
            try:
                text_to_send = query
                if target_name == "browser_address_bar":
                    text_to_send = self.assistant.config.get("google_url").format(query=quote_plus(query))
                entry_strategy = self._type_into_target(
                    domain="text_entry:search",
                    target_name=target_name,
                    text=text_to_send,
                    confidence=0.74,
                    timeout=6,
                    select_all=True,
                    press_enter=True,
                )
                result = f"Busqueda autonoma enviada a Google: {query}"
                self._record_strategy("search:google", target_name, True)
                self._record_action_outcome(
                    action="smart_site_search",
                    payload={
                        "destination": normalized_destination,
                        "query": query,
                        "browser": resolved_browser,
                        "private": private,
                        "preferred_target": target_name,
                        "text_entry_strategy": entry_strategy,
                    },
                    result=result,
                    success=True,
                )
                self.memory.record_step_log("search", f"google_search_{target_name}", "completed", result)
                return result
            except Exception as exc:
                self._record_strategy("search:google", target_name, False)
                self._emit(f"No se pudo usar {target_name}: {exc}", "warning")
        message = f"No se pudo completar la busqueda en Google: {query}"
        self._record_action_outcome(
            action="smart_site_search",
            payload={
                "destination": normalized_destination,
                "query": query,
                "browser": resolved_browser,
                "private": private,
            },
            result=message,
            success=False,
        )
        raise RuntimeError(message)

    def run_research_document(
        self,
        topic: str,
        browser: str,
        document_app: str,
        result_count: int = 5,
    ) -> str:
        self.assistant._current_action_trace.append(
            {
                "action": "run_research_document",
                "params": {
                    "topic": topic,
                    "browser": browser,
                    "document_app": document_app,
                    "result_count": result_count,
                },
            }
        )
        self._emit(f"Iniciando investigacion profunda sobre: {topic}", "info")
        try:
            research_result = self.perform_research(
                topic=topic,
                browser=browser,
                result_count=result_count,
            )
            merged_text = str(research_result.get("merged_text", ""))
            reviewed_sources = list(research_result.get("reviewed_sources", []))
            report_content = self._compose_report(topic, merged_text, reviewed_sources)
            title = f"Resumen - {topic}"
            output_path = self._build_document_path(topic, document_app)
            saved_path = self.save_document(
                title=title,
                content=report_content,
                application=document_app,
                output_path=output_path,
            )
            self.assistant._artifacts["last_research_topic"] = topic
            self.assistant._artifacts["last_summary"] = report_content
            final_result = (
                f"Investigacion completada sobre {topic}. "
                f"Fuentes revisadas: {len(reviewed_sources)}. Documento: {saved_path}"
            )
            self._record_action_outcome(
                action="run_research_document",
                payload={
                    "topic": topic,
                    "browser": browser,
                    "document_app": document_app,
                    "result_count": result_count,
                    "sources_reviewed": len(reviewed_sources),
                },
                result=final_result,
                success=True,
            )
            self.memory.record_step_log("research", "finalize_report", "completed", final_result)
            return final_result
        except Exception as exc:
            self._record_action_outcome(
                action="run_research_document",
                payload={
                    "topic": topic,
                    "browser": browser,
                    "document_app": document_app,
                    "result_count": result_count,
                },
                result=str(exc),
                success=False,
            )
            raise

    def perform_research(
        self,
        topic: str,
        browser: str,
        result_count: int = 3,
    ) -> Dict[str, Any]:
        self._emit(f"Investigando fuentes visibles sobre: {topic}", "info")
        self.run_search_flow("google", topic, browser=browser, private=False)
        time.sleep(1.0)

        collected_texts: List[str] = []
        reviewed_sources: List[str] = []
        useful_sources: List[Dict[str, Any]] = []
        discarded_titles: List[str] = []
        discard_reasons: List[str] = []
        for index in range(1, max(1, result_count) + 1):
            self._emit(f"Abriendo resultado {index}...", "info")
            opened = self._open_google_result(index)
            if not opened:
                self.memory.record_step_log("research", f"open_result_{index}", "skipped", "No se pudo abrir")
                continue

            time.sleep(1.2)
            page_title = self.automation.get_active_window_title() or f"resultado_{index}"
            page_text = self.collect_page_text(max_scrolls_per_page=2)
            snapshot = self.vision.get_latest_snapshot(refresh=True) if self.vision else None
            source_quality = self.classify_research_source(
                topic,
                page_title,
                page_text,
                capture_context={
                    "window_title": page_title,
                    "active_site": str(getattr(snapshot, "active_site", "") or "") if snapshot else "",
                    "visible_text_verified": len(page_text.strip()) >= 500,
                },
                snapshot=snapshot,
            )
            if not source_quality.get("counts_as_useful"):
                self._emit(f"Resultado {index} descartado por contenido pobre o muro de acceso.", "warning")
                self.memory.record_step_log("research", f"collect_result_{index}", "skipped", page_title)
                discarded_titles.append(page_title)
                discard_reasons.append(str(source_quality.get("reason", "") or "Contenido pobre o muro de acceso."))
            else:
                collected_texts.append(page_text)
                reviewed_sources.append(page_title)
                useful_sources.append(
                    {
                        "index": index,
                        "title": page_title,
                        "captured_chars": len(page_text),
                        "source_kind": str(source_quality.get("source_kind", "web_page") or "web_page"),
                        "scene_id": str(source_quality.get("scene_id", "") or ""),
                        "scene_variant": str(source_quality.get("scene_variant", "") or ""),
                        "emergency_feedback": str(source_quality.get("emergency_feedback", "") or ""),
                    }
                )
                self.memory.record_step_log("research", f"collect_result_{index}", "completed", page_title)

            self._emit("Volviendo a resultados de Google...", "info")
            self._return_to_google_results()

        merged_text = self._merge_texts(collected_texts)
        summary = self.assistant.task_planner.summarize_text(merged_text, max_sentences=6)
        findings = self.assistant.task_planner.summarize_text(merged_text, max_sentences=5)
        return {
            "topic": topic,
            "queries_used": [topic],
            "reviewed_sources": reviewed_sources,
            "visited_titles": list(reviewed_sources),
            "discarded_titles": discarded_titles,
            "discard_reasons": discard_reasons,
            "useful_sources": useful_sources,
            "useful_source_count": len(useful_sources),
            "merged_text": merged_text,
            "summary": summary,
            "findings": findings,
            "search_method": "smart_site_search_google",
        }

    def _return_to_google_results(self) -> bool:
        if self._wait_for_google_results(timeout_seconds=0.1):
            return True
        try:
            self.automation.hotkey("alt", "left")
        except Exception:
            return False
        if self._wait_for_google_results():
            return True
        try:
            self.automation.hotkey("ctrl", "w")
        except Exception:
            return False
        return self._wait_for_google_results()

    def _wait_for_google_results(self, timeout_seconds: float = 1.0) -> bool:
        deadline = time.time() + max(0.15, float(timeout_seconds or 0.0))
        while time.time() < deadline:
            if self._active_page_is_google_results():
                return True
            time.sleep(0.15)
        return False

    def _active_page_is_google_results(self) -> bool:
        snapshot = self.vision.get_latest_snapshot(refresh=True) if self.vision else None
        active_site = normalize_text(getattr(snapshot, "active_site", "") or "")
        if active_site == "google":
            return True
        active_title = normalize_text(self.automation.get_active_window_title() or "")
        return bool(active_title) and (
            active_title in {"google", "google - brave"}
            or "buscar con google" in active_title
            or "search - google" in active_title
        )

    def collect_page_text(self, max_scrolls_per_page: int = 2) -> str:
        self._emit("Extrayendo texto relevante de la pagina...", "info")
        chunks: List[str] = []
        seen_signatures = set()
        snapshot = self.vision.get_latest_snapshot(refresh=True) if self.vision else None
        active = next((item for item in snapshot.windows if item.is_active), None) if snapshot else None
        scene = self._detect_active_research_scene(snapshot)
        capture_plan = self._page_capture_plan(snapshot, scene)
        self._emit(capture_plan["message"], "info")

        if capture_plan["selection_phase"] == "first":
            self._append_selected_text_chunk(chunks, seen_signatures, select_all=True)

        for scroll_index in range(max_scrolls_per_page + 1):
            if scroll_index > 0:
                snapshot = self.vision.get_latest_snapshot(refresh=True) if self.vision else snapshot
                active = next((item for item in snapshot.windows if item.is_active), None) if snapshot else active
                scene = self._detect_active_research_scene(snapshot)
            for region_name, region in self._preferred_text_regions(snapshot, active, str(scene.get("scene_id", "") or "")):
                try:
                    extracted = self._extract_text_with_fallbacks(
                        region=region,
                        languages=self._ocr_languages_for_snapshot(snapshot),
                    )
                except Exception as exc:
                    self._emit(f"OCR fallo en {region_name} (scroll {scroll_index}): {exc}", "warning")
                    extracted = ""
                signature = normalize_text(extracted[:200])
                if extracted and signature and signature not in seen_signatures:
                    chunks.append(extracted)
                    seen_signatures.add(signature)
                if extracted and len(normalize_text(extracted)) >= 260 and region_name in {
                    "google_results_primary_region",
                    "browser_primary_reading_region",
                }:
                    break

            if scroll_index < max_scrolls_per_page:
                self._emit("Aplicando scroll para capturar mas contexto...", "info")
                self.automation.scroll(-520)
                time.sleep(0.25)

        if capture_plan["selection_phase"] == "fallback" and not chunks:
            self._emit("OCR insuficiente; intento Ctrl+A solo como ultimo recurso en pagina generica.", "warning")
            self._append_selected_text_chunk(chunks, seen_signatures, select_all=True)

        return self._merge_texts(chunks)

    def _append_selected_text_chunk(
        self,
        chunks: List[str],
        seen_signatures: set,
        select_all: bool,
    ) -> None:
        try:
            selected = self.automation.capture_selected_text(select_all=select_all)
            signature = normalize_text(selected[:200])
            if selected and len(selected.strip()) >= 120 and signature and signature not in seen_signatures:
                chunks.append(selected)
                seen_signatures.add(signature)
        except Exception as exc:
            self._emit(f"No se pudo usar portapapeles directo: {exc}", "warning")

    def _detect_active_research_scene(self, snapshot: Any) -> Dict[str, Any]:
        window_title = ""
        try:
            window_title = str(self.automation.get_active_window_title() or "")
        except Exception:
            window_title = ""
        capture_context = {
            "active_site": str(getattr(snapshot, "active_site", "") or "") if snapshot else "",
            "active_window": str(getattr(snapshot, "active_window", "") or "") if snapshot else "",
        }
        return self.detect_research_scene(
            title=window_title,
            capture_context=capture_context,
            snapshot=snapshot,
        )

    def _page_capture_plan(self, snapshot: Any, scene: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        scene_id = str((scene or {}).get("scene_id", "") or "")
        if scene_id:
            rules = RESEARCH_SCENE_RULES.get(scene_id, RESEARCH_SCENE_RULES["article_page"])
            return {
                "selection_phase": str(rules.get("selection_phase", "fallback") or "fallback"),
                "message": str(rules.get("message", "Leo regiones visibles antes de usar Ctrl+A.") or ""),
            }
        if snapshot and self.vision:
            return {
                "selection_phase": "fallback",
                "message": "Pagina generica detectada: primero leo regiones visibles y dejo Ctrl+A como recurso de emergencia.",
            }
        return {
            "selection_phase": "first",
            "message": "Sin mapa visual confiable: intento portapapeles directo antes del OCR.",
        }

    def _ocr_languages_for_snapshot(self, snapshot: Any) -> List[str]:
        active_site = normalize_text(getattr(snapshot, "active_site", "") or "")
        if active_site in {"google", "wikipedia", "youtube"}:
            return ["spa+eng", "eng", "spa"]
        return ["spa+eng", "eng"]

    def _preferred_text_regions(
        self,
        snapshot: Any,
        active_window: Any,
        scene_id: str = "",
    ) -> List[tuple[str, tuple[int, int, int, int]]]:
        regions: List[tuple[str, tuple[int, int, int, int]]] = []
        if self.vision and snapshot:
            preferred_names: List[str] = []
            normalized_scene = normalize_text(scene_id)
            if normalized_scene == "youtube_watch":
                preferred_names.extend(
                    [
                        "youtube_transcript_region",
                        "youtube_captions_region",
                        "youtube_watch_primary_region",
                        "youtube_watch_metadata_region",
                        "youtube_watch_sidebar_region",
                        "youtube_results_primary_region",
                        "youtube_results_column",
                    ]
                )
            elif normalized_scene == "google_results":
                preferred_names.extend(
                    [
                        "google_results_primary_region",
                        "google_results_column",
                    ]
                )
            preferred_names.extend(
                [
                    "browser_primary_reading_region",
                    "browser_content_region",
                ]
            )
            for name in preferred_names:
                try:
                    element = self.vision.find_ui_element(name, snapshot=snapshot)
                except Exception:
                    element = None
                region = self._region_from_ui_element(element)
                if region:
                    regions.append((name, region))
        if active_window:
            regions.append(
                (
                    "active_window_full",
                    (active_window.left, active_window.top, active_window.width, active_window.height),
                )
            )
        return regions

    @staticmethod
    def _region_from_ui_element(element: Any) -> Optional[tuple[int, int, int, int]]:
        if not element:
            return None
        try:
            width = int(getattr(element, "width", 0) or 0)
            height = int(getattr(element, "height", 0) or 0)
            center_x = int(getattr(element, "x", 0) or 0)
            center_y = int(getattr(element, "y", 0) or 0)
        except Exception:
            return None
        if width <= 0 or height <= 0:
            return None
        left = max(0, center_x - (width // 2))
        top = max(0, center_y - (height // 2))
        return (left, top, width, height)

    def _extract_text_with_fallbacks(
        self,
        region: tuple[int, int, int, int],
        languages: List[str],
    ) -> str:
        if not self.vision:
            return ""
        last_error: Optional[Exception] = None
        for language in languages:
            try:
                extracted = self.vision.extract_text(region=region, lang=language)
            except Exception as exc:
                last_error = exc
                continue
            if extracted and extracted.strip():
                return extracted.strip()
        if last_error is not None:
            raise last_error
        return ""

    def save_document(
        self,
        title: str,
        content: str,
        application: str,
        output_path: Path,
    ) -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_app = self.assistant._resolve_application_name(application)
        fallback_path = self._write_local_document_backup(
            output_path=output_path,
            title=title,
            content=content,
            application=resolved_app,
        )
        taskbar_target = {
            "word": "taskbar_word",
            "spotify": "taskbar_spotify",
            "brave": "taskbar_brave",
        }.get(resolved_app)

        try:
            self._emit(f"Preparando {resolved_app} para escribir el documento...", "info")
            self.mouse.focus_or_launch_app(
                app_name=resolved_app,
                taskbar_target=taskbar_target,
                launch_callback=lambda: self.assistant.open_application(resolved_app),
            )
            time.sleep(1.2)
            try:
                self.automation.hotkey("ctrl", "n")
                time.sleep(0.6)
            except Exception:
                self._emit("No se pudo forzar documento nuevo; continuando.", "warning")

            try:
                self.mouse.click_ui_target("document_body", timeout=4, app=resolved_app)
            except Exception:
                self._emit("No se encontro document_body; escribiendo en el foco actual.", "warning")

            self._emit("Escribiendo contenido del documento...", "info")
            content_strategy = self._write_document_content(content)
            time.sleep(0.5)

            self._emit("Intentando guardado automatizado...", "info")
            try:
                self.automation.hotkey("ctrl", "shift", "s")
            except Exception:
                self.automation.hotkey("ctrl", "s")
            time.sleep(1.4)
            self.automation.write_text(str(output_path), use_clipboard=True)
            self.automation.press_keys(["enter"])
            time.sleep(1.0)
            active_title = normalize_text(self.automation.get_active_window_title() or "")
            if "save as" in active_title or "guardar como" in active_title:
                self._emit("Confirmando dialogo de guardado...", "info")
                self.automation.press_keys(["enter"])
                time.sleep(0.8)

            final_path = str(output_path)
            self.memory.record_document_output(final_path, resolved_app, "saved", title)
            self.memory.record_step_log("document", "save_document", "completed", final_path)
            self._record_action_outcome(
                action="create_document",
                payload={
                    "application": resolved_app,
                    "title": title,
                    "output_path": final_path,
                    "text_entry_strategy": content_strategy,
                },
                result=final_path,
                success=True,
            )
            return final_path
        except Exception as exc:
            self._emit(f"Guardado automatizado fallo: {exc}. Usando fallback local.", "warning")
            self.memory.record_document_output(str(fallback_path), resolved_app, "fallback", title)
            self.memory.record_step_log("document", "save_document_fallback", "completed", str(fallback_path))
            self._record_action_outcome(
                action="create_document",
                payload={
                    "application": resolved_app,
                    "title": title,
                    "output_path": str(output_path),
                },
                result=str(exc),
                success=False,
            )
            return str(fallback_path)

    def _write_local_document_backup(
        self,
        output_path: Path,
        title: str,
        content: str,
        application: str,
    ) -> Path:
        resolved = normalize_text(application)
        if resolved == "word" and output_path.suffix.lower() == ".docx":
            self._write_minimal_docx(output_path, title=title, content=content)
            return output_path
        fallback_path = output_path.with_suffix(".txt")
        fallback_path.write_text(content, encoding="utf-8")
        return fallback_path

    def _write_minimal_docx(self, output_path: Path, title: str, content: str) -> None:
        paragraphs = [title, "", *str(content or "").replace("\r\n", "\n").split("\n")]
        body = "\n".join(self._docx_paragraph(paragraph) for paragraph in paragraphs)
        document_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{body}<w:sectPr><w:pgSz w:w=\"12240\" w:h=\"15840\"/>"
            '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>'
            "</w:sectPr></w:body></w:document>"
        )
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        )
        rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>'
            "</Relationships>"
        )
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr("[Content_Types].xml", content_types)
            package.writestr("_rels/.rels", rels)
            package.writestr("word/document.xml", document_xml)

    @staticmethod
    def _docx_paragraph(text: str) -> str:
        safe = escape(str(text))
        if not safe:
            return "<w:p/>"
        return f'<w:p><w:r><w:t xml:space="preserve">{safe}</w:t></w:r></w:p>'

    def _open_google_result(self, index: int) -> bool:
        snapshot = self.vision.get_latest_snapshot(refresh=True)
        if not snapshot:
            return False

        target_candidates = [f"google_result_title_{index}", f"google_result_card_{index}"]
        if index == 1:
            target_candidates.extend(["google_result_title", "google_result_card"])

        for target_name in target_candidates:
            target = self.vision.find_ui_element(target_name, snapshot=snapshot)
            if not target:
                continue
            try:
                self._google_result_open_count += 1
                click_x, click_y = self._google_result_click_point(target, index=index, target_name=target_name)
                self.mouse.click_at(click_x, click_y, button="left")
                return True
            except Exception:
                continue
        return False

    def _google_result_click_point(self, target: Any, index: int, target_name: str = "") -> tuple[int, int]:
        width = max(24, int(getattr(target, "width", 0) or 0))
        height = max(24, int(getattr(target, "height", 0) or 0))
        center_x = int(getattr(target, "x", 0) or 0)
        center_y = int(getattr(target, "y", 0) or 0)
        normalized_target = normalize_text(target_name or getattr(target, "name", ""))
        if "title" in normalized_target:
            patterns = [
                (-0.20, -0.04),
                (-0.12, 0.00),
                (-0.06, 0.04),
                (0.02, 0.00),
            ]
        else:
            patterns = [
                (-0.24, -0.22),
                (-0.18, -0.16),
                (-0.12, -0.10),
                (-0.06, -0.04),
                (0.02, 0.02),
            ]
        pattern_index = (self._google_result_open_count + max(1, int(index)) - 1) % len(patterns)
        offset_x_ratio, offset_y_ratio = patterns[pattern_index]
        max_x_offset = max(8, (width // 2) - 8)
        max_y_offset = max(8, (height // 2) - 8)
        offset_x = max(-max_x_offset, min(max_x_offset, int(width * offset_x_ratio)))
        offset_y = max(-max_y_offset, min(max_y_offset, int(height * offset_y_ratio)))
        return center_x + offset_x, center_y + offset_y

    def _compose_report(
        self,
        topic: str,
        merged_text: str,
        reviewed_sources: List[str],
    ) -> str:
        summary = self.assistant.task_planner.summarize_text(merged_text, max_sentences=6)
        findings = self.assistant.task_planner.summarize_text(merged_text, max_sentences=5)
        conclusion_lines = [
            "- La informacion visible apunta a patrones recurrentes entre las fuentes abiertas.",
            "- Conviene validar manualmente fechas exactas o spoilers si el tema cambia rapido.",
        ]
        sources_block = "\n".join(f"- {source}" for source in reviewed_sources) or "- Sin fuentes capturadas"
        return (
            f"{topic}\n\n"
            f"Titulo\n- {topic}\n\n"
            f"Resumen\n{summary or '- Sin resumen disponible'}\n\n"
            f"Hallazgos clave\n{findings or '- Sin hallazgos consistentes'}\n\n"
            f"Conclusiones\n{chr(10).join(conclusion_lines)}\n\n"
            f"Fuentes revisadas\n{sources_block}\n"
        )

    @staticmethod
    def _looks_unhelpful(text: str) -> bool:
        normalized = normalize_text(text)
        if len(normalized) < 120:
            return True
        blocked_tokens = (
            "sign in",
            "inicia sesion",
            "login",
            "subscribe to continue",
            "404",
            "page not found",
            "enable javascript",
        )
        return any(token in normalized for token in blocked_tokens)

    @staticmethod
    def _looks_like_google_results_title(title: str) -> bool:
        normalized = normalize_text(title)
        if not normalized:
            return False
        return normalized in {"google", "google - brave"} or "buscar con google" in normalized or "search - google" in normalized

    @staticmethod
    def _research_source_kind_from_title(title: str) -> str:
        raw = str(title or "").strip().lower()
        normalized = normalize_text(title)
        if "youtube" in normalized or "youtube.com/watch" in raw or "youtu.be/" in raw:
            return "youtube_video"
        return "web_page"

    @staticmethod
    def _research_title_is_ambiguous(title: str) -> bool:
        raw = str(title or "").strip().lower()
        normalized = normalize_text(title)
        if not raw or not normalized:
            return True
        if "sin titulo" in normalized or "untitled" in raw:
            return True
        if raw.startswith("http://") or raw.startswith("https://"):
            return True
        return "youtube.com/watch" in raw or "youtu.be/" in raw

    @staticmethod
    def _research_title_is_noise(title: str) -> bool:
        normalized = normalize_text(title)
        if not normalized:
            return False
        noise_tokens = (
            "politica de privacidad",
            "privacidad y condiciones",
            "mi centro de anuncios",
            "ayuda de busqueda web de google",
            "search help",
            "cookies",
            "terms",
            "condiciones",
        )
        return any(token in normalized for token in noise_tokens)

    @staticmethod
    def _looks_like_help_page(title: str, text: str) -> bool:
        normalized_title = normalize_text(title)
        normalized_text = normalize_text(text)
        help_tokens = (
            "help",
            "ayuda",
            "support",
            "soporte",
            "documentation",
            "documentacion",
            "docs",
            "manual",
            "reference",
            "faq",
            "knowledge base",
        )
        return any(token in normalized_title for token in help_tokens) or any(token in normalized_text[:320] for token in help_tokens)

    @staticmethod
    def _looks_like_file_dialog_scene(title: str, text: str) -> bool:
        normalized_title = normalize_text(title)
        normalized_text = normalize_text(text)
        if normalized_title in {"abrir", "open"}:
            return True
        dialog_tokens = (
            "open file",
            "abrir archivo",
            "choose file",
            "select file",
            "nombre de archivo",
            "file name",
        )
        return any(token in normalized_title for token in dialog_tokens) or any(token in normalized_text[:240] for token in dialog_tokens)

    @staticmethod
    def _looks_like_modal_scene(title: str, text: str, capture_context: Optional[Dict[str, Any]] = None) -> bool:
        if capture_context and capture_context.get("modal_reason"):
            return True
        normalized_title = normalize_text(title)
        normalized_text = normalize_text(text)
        modal_tokens = (
            "confirm form resubmission",
            "salir del sitio web",
            "leave site",
            "do you want to save",
            "quieres guardar",
            "esta pagina dice",
            "this page says",
            "permitir",
            "allow notifications",
        )
        compact_text = normalized_text[:360]
        return any(token in normalized_title for token in modal_tokens) or (
            len(normalized_text) <= 700 and any(token in compact_text for token in modal_tokens)
        )

    @staticmethod
    def _looks_like_blocked_page_scene(title: str, text: str) -> bool:
        normalized_title = normalize_text(title)
        normalized_text = normalize_text(text)
        blocked_title_tokens = (
            "access denied",
            "captcha",
            "too many requests",
            "blocked",
            "site cant be reached",
            "this site cant be reached",
            "page not found",
            "error 404",
            "error 403",
            "error 500",
            "not found",
        )
        blocked_text_tokens = (
            "access denied",
            "captcha",
            "too many requests",
            "page not found",
            "site cant be reached",
            "enable javascript",
            "request blocked",
            "temporarily unavailable",
        )
        if any(token in normalized_title for token in blocked_title_tokens):
            return True
        return len(normalized_text) <= 500 and any(token in normalized_text for token in blocked_text_tokens)

    @classmethod
    def _research_scene_payload(
        cls,
        scene_id: str,
        scene_variant: str = "",
        emergency_feedback: str = "",
    ) -> Dict[str, Any]:
        rules = RESEARCH_SCENE_RULES.get(scene_id, RESEARCH_SCENE_RULES["article_page"])
        return {
            "scene_id": scene_id,
            "scene_variant": scene_variant or "standard",
            "emergency_feedback": emergency_feedback,
            "read_policy": str(rules.get("read_policy", "") or ""),
            "ignore_policy": str(rules.get("ignore_policy", "") or ""),
            "valid_exit_rule": str(rules.get("valid_exit_rule", "") or ""),
        }

    @classmethod
    def detect_research_scene(
        cls,
        title: str,
        text: str = "",
        capture_context: Optional[Dict[str, Any]] = None,
        snapshot: Any = None,
    ) -> Dict[str, Any]:
        context = capture_context or {}
        resolved_title = (
            str(title or "")
            or str(context.get("window_title", "") or "")
            or str(context.get("active_window", "") or "")
            or str(getattr(snapshot, "active_window", "") or "")
        )
        active_site = normalize_text(
            str(context.get("active_site", "") or getattr(snapshot, "active_site", "") or "")
        )
        normalized_title = normalize_text(resolved_title)
        normalized_text = normalize_text(text)

        if bool(context.get("file_dialog_detected")) or cls._looks_like_file_dialog_scene(resolved_title, text):
            return cls._research_scene_payload("file_dialog", "browser_or_system_dialog", "hay dialogo de archivo")
        if bool(context.get("modal_detected")) or cls._looks_like_modal_scene(resolved_title, text, context):
            return cls._research_scene_payload("modal", "blocking_modal", "hay modal")
        if cls._looks_like_blocked_page_scene(resolved_title, text):
            return cls._research_scene_payload("blocked_page", "access_or_error", "pagina bloqueada o vacia")
        if cls._research_title_is_noise(resolved_title):
            return cls._research_scene_payload("help_page", "lateral_help_noise", "abrimos ayuda lateral")
        if cls._looks_like_help_page(resolved_title, text):
            return cls._research_scene_payload("help_page", "documentation_or_support", "")
        if cls._looks_like_google_results_title(resolved_title) or active_site == "google":
            return cls._research_scene_payload("google_results", "search_results", "seguimos en resultados")
        if cls._research_source_kind_from_title(resolved_title) == "youtube_video" or active_site == "youtube":
            return cls._research_scene_payload("youtube_watch", "transcript_or_visible_text", "")
        if not normalized_title and not normalized_text:
            return cls._research_scene_payload("blocked_page", "empty_capture", "pagina bloqueada o vacia")
        return cls._research_scene_payload("article_page", "general_web_page", "")

    @staticmethod
    def _research_signal_tokens(text: str) -> List[str]:
        normalized = normalize_text(text)
        if not normalized:
            return []
        stopwords = {
            "de", "del", "la", "las", "el", "los", "para", "por", "con", "sin", "una", "uno", "unos", "unas",
            "como", "what", "with", "from", "that", "this", "your", "their", "sobre", "into", "through", "desde",
            "guia", "overview", "manual", "explicacion", "explicacion practica", "resumen", "historia", "conceptos",
            "fundamentos", "tecnicas", "analisis", "comparacion", "contexto", "ejemplos", "documentacion",
            "errores", "pasos", "practico", "tutorial", "official", "wiki", "video", "videos", "youtube", "google",
            "brave", "search", "buscar",
        }
        tokens = re.findall(r"[a-z0-9]+", normalized)
        return [token for token in tokens if len(token) >= 4 and token not in stopwords and not token.isdigit()]

    @classmethod
    def _research_title_matches_query(cls, query: str, title: str) -> bool:
        query_tokens = set(cls._research_signal_tokens(query))
        if not query_tokens:
            return True
        title_tokens = set(cls._research_signal_tokens(title))
        if not title_tokens:
            return False
        return bool(query_tokens & title_tokens)

    @classmethod
    def classify_research_source(
        cls,
        query: str,
        title: str,
        text: str,
        capture_context: Optional[Dict[str, Any]] = None,
        snapshot: Any = None,
    ) -> Dict[str, Any]:
        captured_chars = len(str(text or "").strip())
        scene = cls.detect_research_scene(title, text, capture_context=capture_context, snapshot=snapshot)
        scene_id = str(scene.get("scene_id", "") or "article_page")
        scene_variant = str(scene.get("scene_variant", "") or "standard")
        emergency_feedback = str(scene.get("emergency_feedback", "") or "")
        source_kind = "youtube_video" if scene_id == "youtube_watch" else cls._research_source_kind_from_title(title)
        title_matches_query = cls._research_title_matches_query(query, title)
        visible_text_verified = bool((capture_context or {}).get("visible_text_verified"))
        transcript_available = bool((capture_context or {}).get("transcript_available"))
        useful_chars = captured_chars >= 500

        def result(
            counts_as_useful: bool,
            page_usefulness_label: str,
            reason: str,
            feedback_override: str = "",
        ) -> Dict[str, Any]:
            payload = dict(scene)
            payload.update(
                {
                    "counts_as_useful": counts_as_useful,
                    "page_usefulness_label": page_usefulness_label,
                    "useful_source_count": 1 if counts_as_useful else 0,
                    "source_kind": source_kind,
                    "title_matches_query": bool(title_matches_query),
                    "reason": reason,
                    "scene_id": scene_id,
                    "scene_variant": scene_variant,
                    "emergency_feedback": feedback_override or emergency_feedback,
                }
            )
            return payload

        if scene_id == "google_results":
            return result(False, "poor", "La pagina sigue en resultados de Google.")
        if scene_id == "file_dialog":
            return result(False, "poor", "Hay un dialogo de archivo activo; no cuenta como fuente util.")
        if scene_id == "modal":
            return result(False, "poor", "Hay un modal o confirmacion encima de la pagina; no cuenta como fuente util.")
        if cls._looks_unhelpful(text) or scene_id == "blocked_page":
            return result(False, "poor", "Contenido pobre, vacio o bloqueado.", "pagina bloqueada o vacia")
        if cls._research_title_is_ambiguous(title) and scene_id not in {"youtube_watch"}:
            return result(
                False,
                "poor" if captured_chars < 500 else "mixed",
                "El titulo de la pagina es ambiguo o no identificable; no cuenta como fuente util.",
            )
        if scene_id == "help_page" and scene_variant == "lateral_help_noise":
            return result(
                False,
                "poor" if captured_chars < 500 else "mixed",
                "La pagina abierta es ruido de plataforma o ayuda lateral, no una fuente util.",
                "abrimos ayuda lateral",
            )
        if scene_id == "youtube_watch" and not (transcript_available or visible_text_verified):
            return result(
                False,
                "mixed" if useful_chars else "poor",
                "YouTube sin transcript o texto verificable no cuenta como fuente util de investigar.",
            )
        if not title_matches_query and scene_id in {"article_page", "help_page", "youtube_watch"}:
            return result(
                False,
                "mixed" if useful_chars else "poor",
                "La fuente abierta no parece alinearse con la consulta.",
                "la pagina sirve pero no coincide con la consulta",
            )
        if not useful_chars:
            return result(False, "poor", "No se capto suficiente texto util.", "pagina bloqueada o vacia")
        return result(True, "useful", "")

    @staticmethod
    def _merge_texts(chunks: List[str]) -> str:
        merged: List[str] = []
        seen = set()
        for chunk in chunks:
            clean = re.sub(r"\s+", " ", chunk).strip()
            signature = normalize_text(clean[:240])
            if not clean or signature in seen:
                continue
            seen.add(signature)
            merged.append(clean)
        return "\n\n".join(merged)

    def _build_document_path(self, topic: str, document_app: str) -> Path:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", normalize_text(topic)).strip("_") or "raphel_document"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        extension = ".odt" if normalize_text(document_app) == "libreoffice writer" else ".docx"
        output_dir = Path(self.assistant.config.get("document_output_dir"))
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / f"{timestamp}_{slug}{extension}"

    def _preferred_strategy(self, domain: str, candidates: List[str]) -> Optional[str]:
        learning = getattr(self.assistant, "learning", None)
        if not learning:
            return candidates[0] if candidates else None
        return learning.preferred_strategy(domain, candidates)

    def _rank_strategies(self, domain: str, candidates: List[str]) -> List[str]:
        preferred = self._preferred_strategy(domain, candidates)
        if not preferred:
            return list(candidates)
        return [preferred, *[item for item in candidates if item != preferred]]

    def _record_strategy(self, domain: str, strategy: str, success: bool) -> None:
        learning = getattr(self.assistant, "learning", None)
        if learning:
            learning.record_strategy_result(domain, strategy, success)

    def _record_action_outcome(
        self,
        action: str,
        payload: Dict[str, Any],
        result: str,
        success: bool,
    ) -> None:
        history = getattr(self.assistant, "history", None)
        if history:
            try:
                history.record(action, {"payload": payload, "result": result})
            except Exception:
                pass
        learning = getattr(self.assistant, "learning", None)
        if learning:
            context = {}
            if hasattr(self.assistant, "get_context_payload"):
                try:
                    context = self.assistant.get_context_payload()
                except Exception:
                    context = {}
            learning.record_action_result(
                action=action,
                params=payload,
                result=result,
                success=success,
                context=context,
            )

    def _research_settings(self) -> Dict[str, Any]:
        settings = self.assistant.config.get("research_automation", {})
        return settings if isinstance(settings, dict) else {}

    def _rank_text_entry_strategies(self, domain: str, default_order: List[str]) -> List[str]:
        preferred = self._preferred_strategy(domain, default_order)
        if not preferred or preferred not in default_order:
            return list(default_order)
        return [preferred, *[item for item in default_order if item != preferred]]

    def _type_into_target(
        self,
        domain: str,
        target_name: str,
        text: str,
        confidence: float,
        timeout: float,
        select_all: bool,
        press_enter: bool,
        app: Optional[str] = None,
    ) -> str:
        settings = self._research_settings()
        prefer_direct = bool(settings.get("prefer_direct_typing_for_search", True))
        direct_interval = float(settings.get("search_direct_typing_interval", 0.01))
        default_order = ["direct_typing", "clipboard_paste"] if prefer_direct else ["clipboard_paste", "direct_typing"]
        last_error: Optional[Exception] = None

        for strategy in self._rank_text_entry_strategies(domain, default_order):
            use_clipboard = strategy == "clipboard_paste"
            try:
                self.mouse.locate_and_type(
                    target_name=target_name,
                    text=text,
                    confidence=confidence,
                    timeout=timeout,
                    select_all=select_all,
                    press_enter=press_enter,
                    use_clipboard=use_clipboard,
                    interval=direct_interval,
                    app=app,
                )
                self._record_strategy(domain, strategy, True)
                return strategy
            except Exception as exc:
                last_error = exc
                self._record_strategy(domain, strategy, False)
                self._emit(f"Entrada de texto fallo con {strategy} en {target_name}: {exc}", "warning")

        raise RuntimeError(
            f"No se pudo escribir en {target_name} con ninguna estrategia de texto."
        ) from last_error

    def _write_document_content(self, content: str) -> str:
        settings = self._research_settings()
        direct_interval = float(settings.get("document_direct_typing_interval", 0.006))
        direct_limit = max(1, int(settings.get("document_direct_typing_max_chars", 1800)))
        default_order = ["direct_typing", "clipboard_paste"] if len(content) <= direct_limit else [
            "clipboard_paste",
            "direct_typing",
        ]
        last_error: Optional[Exception] = None
        domain = "text_entry:document_body"

        for strategy in self._rank_text_entry_strategies(domain, default_order):
            try:
                if strategy == "direct_typing":
                    self._type_document_content_direct(content, interval=direct_interval)
                else:
                    self.automation.write_text(content, use_clipboard=True)
                self._record_strategy(domain, strategy, True)
                return strategy
            except Exception as exc:
                last_error = exc
                self._record_strategy(domain, strategy, False)
                self._emit(f"Escritura de documento fallo con {strategy}: {exc}", "warning")

        raise RuntimeError("No se pudo escribir el contenido del documento.") from last_error

    def _type_document_content_direct(self, content: str, interval: float) -> None:
        normalized_content = content.replace("\r\n", "\n")
        lines = normalized_content.split("\n")
        for index, line in enumerate(lines):
            if line:
                self.automation.write_text(line, interval=interval, use_clipboard=False)
            if index < len(lines) - 1:
                self.automation.press_keys(["enter"])

    def _emit(self, message: str, level: str = "info") -> None:
        log_method = getattr(self.logger, level if hasattr(self.logger, level) else "info")
        log_method(message)
        if self.progress_callback:
            self.progress_callback(message, level)
