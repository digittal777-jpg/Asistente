from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from core.skills import normalize_text


ACTION_CONFIDENCE_THRESHOLD = 0.70
REACQUIRE_DELTA_THRESHOLD = 24
SCENE_KINDS = (
    "desktop",
    "explorer",
    "browser_serp",
    "browser_article",
    "youtube_results",
    "youtube_watch",
    "unknown",
)


@dataclass
class PerceptionTarget:
    target_id: str
    semantic_role: str
    bbox: List[int]
    confidence: float
    source: str
    scene_tags: List[str] = field(default_factory=list)
    state_tags: List[str] = field(default_factory=list)
    stable_signature: str = ""
    verification_role: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ObservationBundle:
    timestamp: str
    active_app: str
    active_site: str
    window_title: str
    scene_kind: str
    targets: List[PerceptionTarget]
    selected_target_id: Optional[str]
    regions: Dict[str, List[int]]
    ocr_text: str
    confidence: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    blocking_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "active_app": self.active_app,
            "active_site": self.active_site,
            "window_title": self.window_title,
            "scene_kind": self.scene_kind,
            "targets": [item.to_dict() for item in self.targets],
            "selected_target_id": self.selected_target_id,
            "regions": self.regions,
            "ocr_text": self.ocr_text,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "blocking_reason": self.blocking_reason,
        }


class PerceptionEngine:
    BROWSER_APPS = {"brave", "chrome", "edge", "firefox"}

    def __init__(self, vision: Any) -> None:
        self.vision = vision

    def observe(self, refresh: bool = False) -> ObservationBundle:
        snapshot = self.vision.get_latest_snapshot(refresh=refresh)
        return self.observe_snapshot(snapshot)

    def observe_snapshot(self, snapshot: Any) -> ObservationBundle:
        if snapshot is None:
            return ObservationBundle(
                timestamp="",
                active_app="",
                active_site="",
                window_title="",
                scene_kind="unknown",
                targets=[],
                selected_target_id=None,
                regions={},
                ocr_text="",
                confidence=0.0,
                evidence={"target_count": 0, "actable_target_count": 0},
                blocking_reason="no_snapshot",
            )

        active_app = str(getattr(snapshot, "active_app", "") or "")
        active_site = str(getattr(snapshot, "active_site", "") or "")
        window_title = str(getattr(snapshot, "active_window", "") or "")
        ocr_text = str(getattr(snapshot, "ocr_excerpt", "") or "")
        scene_kind = self._classify_scene(snapshot)
        targets = self._build_targets(snapshot, scene_kind)
        selected_target = self._choose_selected_target(scene_kind, targets)
        actable_targets = [item for item in targets if item.confidence >= ACTION_CONFIDENCE_THRESHOLD]
        confidence = self._bundle_confidence(snapshot, selected_target, actable_targets)
        blocking_reason = self._blocking_reason(scene_kind, targets, selected_target, confidence)
        evidence = {
            "scene_confirmed": scene_kind != "unknown",
            "target_count": len(targets),
            "actable_target_count": len(actable_targets),
            "selected_semantic_role": selected_target.semantic_role if selected_target else "",
            "selected_verification_role": selected_target.verification_role if selected_target else "",
            "raw_target_names": [item.target_id for item in targets[:12]],
            "scene_tags": sorted({tag for item in targets for tag in item.scene_tags}),
        }
        regions = {
            item.target_id: list(item.bbox)
            for item in targets
            if item.semantic_role.endswith("_region") or item.semantic_role == "window_surface"
        }
        return ObservationBundle(
            timestamp=str(getattr(snapshot, "captured_at", "") or ""),
            active_app=active_app,
            active_site=active_site,
            window_title=window_title,
            scene_kind=scene_kind,
            targets=targets,
            selected_target_id=selected_target.target_id if selected_target else None,
            regions=regions,
            ocr_text=ocr_text,
            confidence=confidence,
            evidence=evidence,
            blocking_reason=blocking_reason,
        )

    def evaluate_target_reacquire(
        self,
        previous: ObservationBundle,
        current: ObservationBundle,
        preferred_target_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        previous_target = self._preferred_target(previous, preferred_target_id)
        current_target = self._match_current_target(previous_target, current) if previous_target else None
        if not previous_target:
            return {
                "matched": False,
                "reason": "no_previous_target",
                "delta_px": None,
                "stable_signature_match": False,
                "previous_target_id": "",
                "current_target_id": "",
            }
        if not current_target:
            return {
                "matched": False,
                "reason": "target_not_found",
                "delta_px": None,
                "stable_signature_match": False,
                "previous_target_id": previous_target.target_id,
                "current_target_id": "",
            }

        delta_px = self._bbox_center_distance(previous_target.bbox, current_target.bbox)
        stable_signature_match = previous_target.stable_signature == current_target.stable_signature
        confidence_ok = (
            previous_target.confidence >= ACTION_CONFIDENCE_THRESHOLD
            and current_target.confidence >= ACTION_CONFIDENCE_THRESHOLD
        )
        matched = confidence_ok and (stable_signature_match or delta_px <= REACQUIRE_DELTA_THRESHOLD)
        return {
            "matched": matched,
            "reason": "" if matched else "delta_or_signature_mismatch",
            "delta_px": round(delta_px, 3),
            "stable_signature_match": stable_signature_match,
            "confidence_ok": confidence_ok,
            "previous_target_id": previous_target.target_id,
            "current_target_id": current_target.target_id,
            "previous_signature": previous_target.stable_signature,
            "current_signature": current_target.stable_signature,
        }

    def _classify_scene(self, snapshot: Any) -> str:
        active_app = normalize_text(getattr(snapshot, "active_app", "") or "")
        active_site = normalize_text(getattr(snapshot, "active_site", "") or "")
        title = normalize_text(getattr(snapshot, "active_window", "") or "")
        names = {normalize_text(getattr(item, "name", "")) for item in getattr(snapshot, "elements", [])}

        if active_app == "explorer":
            return "explorer"
        if active_site == "youtube":
            if any(
                name in names
                for name in (
                    "youtube_watch_primary_region",
                    "youtube_watch_metadata_region",
                    "youtube_transcript_region",
                    "youtube_captions_region",
                )
            ):
                return "youtube_watch"
            if any(name in names for name in ("youtube_results_primary_region", "youtube_results_column")):
                return "youtube_results"
            if any(token in title for token in ("resultado", "search", "buscar")):
                return "youtube_results"
            return "youtube_watch"
        if active_app in self.BROWSER_APPS or active_site in {"google", "github", "gmail"}:
            if active_site == "google" or any(name.startswith("google_result_") for name in names):
                return "browser_serp"
            if active_site:
                return "browser_article"
            if any(name in names for name in ("browser_primary_reading_region", "browser_content_region")):
                return "browser_article"
        if not active_app and (not title or title in {"desktop", "program manager"}):
            return "desktop"
        return "unknown"

    def _build_targets(self, snapshot: Any, scene_kind: str) -> List[PerceptionTarget]:
        targets: List[PerceptionTarget] = []
        active_window = next(
            (window for window in getattr(snapshot, "windows", []) if getattr(window, "is_active", False)),
            None,
        )
        if active_window and getattr(active_window, "width", 0) > 0 and getattr(active_window, "height", 0) > 0:
            bbox = [
                int(getattr(active_window, "left", 0) or 0),
                int(getattr(active_window, "top", 0) or 0),
                int(getattr(active_window, "width", 0) or 0),
                int(getattr(active_window, "height", 0) or 0),
            ]
            window_role = "window_surface" if scene_kind != "desktop" else "desktop_surface"
            targets.append(
                PerceptionTarget(
                    target_id=f"{scene_kind}_window",
                    semantic_role=window_role,
                    bbox=bbox,
                    confidence=max(float(getattr(snapshot, "confidence", 0.0) or 0.0), 0.70),
                    source="window_context",
                    scene_tags=[scene_kind],
                    state_tags=["visible", "context_anchor"],
                    stable_signature=f"{scene_kind}:{window_role}",
                    verification_role="context_anchor",
                )
            )

        seen_ids = {item.target_id for item in targets}
        for element in getattr(snapshot, "elements", []):
            target = self._target_from_element(element, scene_kind)
            if target.target_id in seen_ids:
                continue
            seen_ids.add(target.target_id)
            targets.append(target)
        return targets

    def _target_from_element(self, element: Any, scene_kind: str) -> PerceptionTarget:
        target_id = str(getattr(element, "name", "") or "")
        bbox = [
            int(getattr(element, "x", 0) or 0),
            int(getattr(element, "y", 0) or 0),
            int(getattr(element, "width", 0) or 0),
            int(getattr(element, "height", 0) or 0),
        ]
        metadata = self._metadata_for_target(target_id, scene_kind)
        scene_tags = list(dict.fromkeys([scene_kind, *metadata.get("scene_tags", [])]))
        state_tags = list(dict.fromkeys(metadata.get("state_tags", [])))
        semantic_role = str(metadata.get("semantic_role") or "ui_target")
        return PerceptionTarget(
            target_id=target_id,
            semantic_role=semantic_role,
            bbox=bbox,
            confidence=float(getattr(element, "confidence", 0.0) or 0.0),
            source=str(getattr(element, "source", "") or metadata.get("source", "heuristic")),
            scene_tags=scene_tags,
            state_tags=state_tags,
            stable_signature=self._stable_signature(target_id, semantic_role, scene_kind),
            verification_role=str(metadata.get("verification_role") or semantic_role),
        )

    def _metadata_for_target(self, target_name: str, scene_kind: str) -> Dict[str, Any]:
        candidates = self._definition_candidates(target_name)
        getter = getattr(self.vision, "get_target_definition", None)
        for candidate in candidates:
            definition = getter(candidate) if callable(getter) else {}
            if definition:
                return {
                    "semantic_role": str(definition.get("semantic_role") or self._fallback_role(candidate)),
                    "scene_tags": list(definition.get("scene_tags", []) or [scene_kind]),
                    "state_tags": list(definition.get("state_tags", []) or []),
                    "verification_role": str(definition.get("verification_role") or self._fallback_role(candidate)),
                    "source": "manifest",
                }
        return {
            "semantic_role": self._fallback_role(target_name),
            "scene_tags": [scene_kind],
            "state_tags": self._fallback_state_tags(target_name),
            "verification_role": self._fallback_verification_role(target_name),
            "source": "derived",
        }

    @staticmethod
    def _definition_candidates(target_name: str) -> List[str]:
        normalized = normalize_text(target_name)
        candidates = [normalized]
        numbered_base = re.sub(r"_\d+$", "", normalized)
        if numbered_base != normalized:
            candidates.append(numbered_base)
        for prefix in ("google_result_title", "google_result_card", "youtube_result_title", "youtube_result_card"):
            if normalized.startswith(prefix):
                candidates.append(prefix)
        return list(dict.fromkeys(candidate for candidate in candidates if candidate))

    @staticmethod
    def _fallback_role(target_name: str) -> str:
        normalized = normalize_text(target_name)
        if "search_bar" in normalized or normalized == "browser_address_bar":
            return "search_bar" if normalized != "browser_address_bar" else "address_bar"
        if "result_title" in normalized:
            return "search_result_title"
        if "result_card" in normalized:
            return "search_result_card"
        if "transcript_toggle" in normalized:
            return "transcript_toggle"
        if "transcript_region" in normalized:
            return "transcript_region"
        if "captions_region" in normalized:
            return "captions_region"
        if "metadata_region" in normalized:
            return "metadata_region"
        if "primary_region" in normalized:
            return "primary_reading_region"
        if "content_region" in normalized:
            return "content_region"
        if "sidebar_region" in normalized:
            return "sidebar_region"
        if "document_body" in normalized:
            return "document_body"
        if "taskbar_" in normalized:
            return "taskbar_app"
        return "ui_target"

    @staticmethod
    def _fallback_state_tags(target_name: str) -> List[str]:
        normalized = normalize_text(target_name)
        tags = ["visible"]
        if "search_bar" in normalized or normalized == "browser_address_bar":
            tags.append("query_input")
        if "result_" in normalized:
            tags.append("search_result")
        if "transcript" in normalized:
            tags.append("transcript")
        if "captions" in normalized:
            tags.append("captions")
        if "document_body" in normalized:
            tags.append("editable_surface")
        return tags

    @staticmethod
    def _fallback_verification_role(target_name: str) -> str:
        normalized = normalize_text(target_name)
        if "result_title" in normalized or "result_card" in normalized:
            return "result_open_candidate"
        if "search_bar" in normalized or normalized == "browser_address_bar":
            return "query_entry"
        if "transcript_region" in normalized:
            return "transcript_capture"
        if "captions_region" in normalized:
            return "captions_capture"
        if "document_body" in normalized:
            return "document_surface"
        return PerceptionEngine._fallback_role(target_name)

    @staticmethod
    def _stable_signature(target_id: str, semantic_role: str, scene_kind: str) -> str:
        normalized_id = normalize_text(target_id)
        normalized_id = re.sub(r"_\d+$", "", normalized_id)
        return f"{scene_kind}:{semantic_role}:{normalized_id}"

    @staticmethod
    def _bundle_confidence(snapshot: Any, selected_target: Optional[PerceptionTarget], actable_targets: List[PerceptionTarget]) -> float:
        snapshot_confidence = float(getattr(snapshot, "confidence", 0.0) or 0.0)
        best_target = selected_target.confidence if selected_target else 0.0
        density_bonus = 0.05 if actable_targets else 0.0
        return round(min(0.98, (snapshot_confidence * 0.55) + (best_target * 0.40) + density_bonus), 4)

    @staticmethod
    def _blocking_reason(
        scene_kind: str,
        targets: List[PerceptionTarget],
        selected_target: Optional[PerceptionTarget],
        confidence: float,
    ) -> str:
        if scene_kind == "unknown":
            return "scene_unknown"
        if not targets:
            return "no_targets"
        if not selected_target:
            return "no_actionable_target"
        if confidence < ACTION_CONFIDENCE_THRESHOLD:
            return "perception_below_threshold"
        return ""

    def _choose_selected_target(
        self,
        scene_kind: str,
        targets: List[PerceptionTarget],
    ) -> Optional[PerceptionTarget]:
        if not targets:
            return None
        priorities = {
            "browser_serp": ["search_result_title", "search_result_card", "search_bar", "primary_reading_region"],
            "browser_article": ["primary_reading_region", "content_region", "address_bar"],
            "youtube_results": ["search_result_title", "search_result_card", "search_bar", "primary_reading_region"],
            "youtube_watch": ["transcript_toggle", "transcript_region", "captions_region", "primary_reading_region"],
            "explorer": ["window_surface", "ui_target"],
            "desktop": ["desktop_surface", "taskbar_app"],
            "unknown": ["window_surface", "ui_target"],
        }
        order = priorities.get(scene_kind, priorities["unknown"])
        order_index = {name: index for index, name in enumerate(order)}
        sorted_targets = sorted(
            targets,
            key=lambda item: (
                0 if item.confidence >= ACTION_CONFIDENCE_THRESHOLD else 1,
                order_index.get(item.semantic_role, len(order_index) + 1),
                -item.confidence,
                item.target_id,
            ),
        )
        return sorted_targets[0] if sorted_targets else None

    @staticmethod
    def _preferred_target(bundle: ObservationBundle, preferred_target_id: Optional[str]) -> Optional[PerceptionTarget]:
        if preferred_target_id:
            for item in bundle.targets:
                if item.target_id == preferred_target_id:
                    return item
        if bundle.selected_target_id:
            for item in bundle.targets:
                if item.target_id == bundle.selected_target_id:
                    return item
        return bundle.targets[0] if bundle.targets else None

    def _match_current_target(
        self,
        previous_target: PerceptionTarget,
        current: ObservationBundle,
    ) -> Optional[PerceptionTarget]:
        for item in current.targets:
            if item.target_id == previous_target.target_id:
                return item
        for item in current.targets:
            if item.stable_signature == previous_target.stable_signature:
                return item
        semantic_matches = [
            item
            for item in current.targets
            if item.semantic_role == previous_target.semantic_role
        ]
        if not semantic_matches:
            return None
        return min(
            semantic_matches,
            key=lambda item: self._bbox_center_distance(previous_target.bbox, item.bbox),
        )

    @staticmethod
    def _bbox_center_distance(left: List[int], right: List[int]) -> float:
        left_center_x = left[0] + (left[2] / 2.0)
        left_center_y = left[1] + (left[3] / 2.0)
        right_center_x = right[0] + (right[2] / 2.0)
        right_center_y = right[1] + (right[3] / 2.0)
        return math.hypot(left_center_x - right_center_x, left_center_y - right_center_y)
